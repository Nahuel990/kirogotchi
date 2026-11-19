import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KIROGOTCHI_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("BRAKET_DEVICE_ARN", raising=False)
    import app.main as main

    importlib.reload(main)
    # hold the ring still so each test knows the exact angle; tests/test_spin.py covers the motion
    monkeypatch.setattr(main, "_spin", lambda g, now: g.spin_base)
    return TestClient(main.app)


def hatch(client, name="Boo"):
    r = client.post("/api/ghosts", json={"name": name})
    assert r.status_code == 200
    d = r.json()
    return d["id"], d["secret"]


def hatch_full(client, name="Boo"):
    """A ghost born fully alive, for tests that need a known starting point."""
    import app.main as main
    gid, secret = hatch(client, name)
    g = main.store.get(gid)
    g.birth_angle = 0.0
    main.store.save(g)
    return gid, secret


def test_hatch_and_status(client):
    gid, secret = hatch(client)
    r = client.get(f"/api/ghosts/{gid}", headers={"X-Ghost-Secret": secret})
    assert r.status_code == 200
    d = r.json()
    assert d["alive"] is True
    assert d["owned"] is True
    assert "secret" not in d


def test_status_without_secret_is_not_owned(client):
    gid, _ = hatch(client)
    assert client.get(f"/api/ghosts/{gid}").json()["owned"] is False


def test_care_requires_secret(client):
    gid, _ = hatch(client)
    assert client.post(f"/api/ghosts/{gid}/care/feed").status_code == 403


def test_care_queues_a_gate(client):
    gid, secret = hatch(client)
    d = client.post(f"/api/ghosts/{gid}/care/feed", headers={"X-Ghost-Secret": secret}).json()
    assert d["care_gates"] == ["feed"]
    assert d["pending_gates"][0].endswith("[feed]")


def test_unknown_care_rejected(client):
    gid, secret = hatch(client)
    r = client.post(f"/api/ghosts/{gid}/care/hug", headers={"X-Ghost-Secret": secret})
    assert r.status_code == 400


def test_fresh_look_is_alive_and_returns_circuit(client):
    gid, secret = hatch_full(client)
    d = client.post(f"/api/ghosts/{gid}/look", headers={"X-Ghost-Secret": secret}).json()
    assert d["alive"] is True
    assert d["odds_alive_before"] == pytest.approx(1.0, abs=1e-6)
    assert "X" in d["circuit"] and "Ry(0.00)" not in d["circuit"]
    assert d["looks"] == 1
    assert d["care_gates"] == []


def test_four_feeds_then_look_kills_by_overfeeding(client):
    gid, secret = hatch_full(client)
    for _ in range(4):
        client.post(f"/api/ghosts/{gid}/care/feed", headers={"X-Ghost-Secret": secret})
    d = client.post(f"/api/ghosts/{gid}/look", headers={"X-Ghost-Secret": secret}).json()
    assert d["alive"] is False
    assert d["odds_alive_before"] == pytest.approx(0.0, abs=1e-6)
    r = client.post(f"/api/ghosts/{gid}/care/feed", headers={"X-Ghost-Secret": secret})
    assert r.status_code == 409


def test_bind_and_shared_fate(client):
    a, sa = hatch(client, "A")
    b, sb = hatch(client, "B")
    r = client.post(f"/api/ghosts/{a}/bind", json={"other_id": b}, headers={"X-Ghost-Secret": sa})
    assert r.status_code == 200 and r.json()["bound_to"] == b
    d = client.post(f"/api/ghosts/{a}/look", headers={"X-Ghost-Secret": sa}).json()
    assert d["bound_outcome"]["id"] == b
    assert d["alive"] == d["bound_outcome"]["alive"]
    # Measurement breaks the bond on both sides.
    assert d["bound_to"] is None
    assert client.get(f"/api/ghosts/{b}").json()["bound_to"] is None


def test_cannot_bind_to_self_or_twice(client):
    a, sa = hatch(client)
    b, _ = hatch(client)
    c, _ = hatch(client)
    h = {"X-Ghost-Secret": sa}
    assert client.post(f"/api/ghosts/{a}/bind", json={"other_id": a}, headers=h).status_code == 400
    assert client.post(f"/api/ghosts/{a}/bind", json={"other_id": b}, headers=h).status_code == 200
    assert client.post(f"/api/ghosts/{a}/bind", json={"other_id": c}, headers=h).status_code == 409


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Kirogotchi" in r.text


def test_device_endpoint_is_honest(client):
    d = client.get("/api/device").json()
    assert d["is_qpu"] is False
    assert "simulator" in d["name"].lower()


def test_hours_no_longer_change_the_odds(client):
    """No hunger and no drift: only the ring and the presses move the ghost."""
    import app.main as main
    gid, secret = hatch_full(client)
    g = main.store.get(gid)
    g.last_look_at -= 24 * 3600
    g.last_care_at -= 24 * 3600
    main.store.save(g)
    d = client.post(f"/api/ghosts/{gid}/look", headers={"X-Ghost-Secret": secret}).json()
    assert d["odds_alive_before"] == pytest.approx(1.0, abs=1e-6)


def test_fire_is_a_stored_random_turn(client):
    gid, secret = hatch_full(client)
    h = {"X-Ghost-Secret": secret}
    d = client.post(f"/api/ghosts/{gid}/care/fire", headers=h).json()
    assert len(d["care_gates"]) == 1 and d["care_gates"][0].startswith("fire:")
    turn = float(d["care_gates"][0][5:])
    assert 0 <= turn < 2 * 3.14159266
    import math
    look = client.post(f"/api/ghosts/{gid}/look", headers=h).json()
    assert look["odds_alive_before"] == pytest.approx(math.cos(turn / 2) ** 2, abs=1e-3)


def test_the_look_uses_the_ring_at_that_second(client, monkeypatch):
    import math
    import app.main as main
    gid, secret = hatch_full(client)
    monkeypatch.setattr(main, "_spin", lambda g, now: math.pi / 3)
    d = client.post(f"/api/ghosts/{gid}/look", headers={"X-Ghost-Secret": secret}).json()
    assert d["odds_alive_before"] == pytest.approx(math.cos(math.pi / 6) ** 2, abs=1e-6)


def test_a_press_does_not_make_the_ring_jump(client, monkeypatch):
    import app.main as main
    from app import spin
    monkeypatch.setattr(main, "_spin", lambda g, now: spin.angle(g.spin_seed, g.spin_t0, g.spin_base, now))
    gid, secret = hatch(client)
    g = main.store.get(gid)
    g.spin_t0 -= 7.5  # the ring has been turning for 7.5 seconds
    main.store.save(g)
    before = spin.angle(g.spin_seed, g.spin_t0, g.spin_base, g.spin_t0 + 7.5)
    client.post(f"/api/ghosts/{gid}/care/play", headers={"X-Ghost-Secret": secret})
    after = main.store.get(gid)
    assert after.spin_base == pytest.approx(before, abs=0.05)  # anchored where it was, within the test's own few ms


def test_hatch_is_random_and_look_resets_it(client):
    import app.main as main
    import math
    for _ in range(3):
        gid, secret = hatch(client)
        assert main.store.get(gid).birth_angle == pytest.approx(math.pi / 2)
    gid, secret = hatch(client)
    g = main.store.get(gid); g.birth_angle = 0.3; main.store.save(g)
    h = {"X-Ghost-Secret": secret}
    assert client.get(f"/api/ghosts/{gid}", headers=h).json()["birth_angle"] == pytest.approx(0.3)
    d = client.post(f"/api/ghosts/{gid}/look", headers=h).json()
    if d["alive"]:
        assert d["birth_angle"] == 0.0


def test_friend_gets_the_same_reveal_in_their_record(client):
    a, sa = hatch(client, "A")
    b, sb = hatch(client, "B")
    client.post(f"/api/ghosts/{a}/bind", json={"other_id": b}, headers={"X-Ghost-Secret": sa})
    d = client.post(f"/api/ghosts/{a}/look", headers={"X-Ghost-Secret": sa}).json()
    other = client.get(f"/api/ghosts/{b}", headers={"X-Ghost-Secret": sb}).json()
    ev = other["history"][-1]
    assert ev["event"] == "looked" and ev["by"] == "A"
    assert ev["alive"] == d["bound_outcome"]["alive"] == other["alive"]
    assert ev["bitstring"] == d["bitstring"] and ev["circuit"] == d["circuit"]
    assert other["looks"] == 1 and other["bound_to"] is None


def test_bind_puts_both_ghosts_on_one_spot(client):
    a, sa = hatch(client, "Ana")
    b, sb = hatch(client, "Ben")
    client.post(f"/api/ghosts/{b}/care/feed", headers={"X-Ghost-Secret": sb})
    client.post(f"/api/ghosts/{a}/bind", json={"other_id": b}, headers={"X-Ghost-Secret": sa})
    va = client.get(f"/api/ghosts/{a}").json()
    vb = client.get(f"/api/ghosts/{b}").json()
    # The binder adopts the friend's spot: same birth, same presses, same clock.
    assert va["birth_angle"] == pytest.approx(vb["birth_angle"])
    assert va["care_gates"] == vb["care_gates"] == ["feed"]
    assert va["bound_name"] == "Ben" and vb["bound_name"] == "Ana"
    # A press from either side moves both.
    client.post(f"/api/ghosts/{a}/care/play", headers={"X-Ghost-Secret": sa})
    assert client.get(f"/api/ghosts/{b}").json()["care_gates"] == ["feed", "play"]
    client.post(f"/api/ghosts/{b}/care/feed", headers={"X-Ghost-Secret": sb})
    assert client.get(f"/api/ghosts/{a}").json()["care_gates"] == ["feed", "play", "feed"]


def test_bind_refusal_names_the_friend(client):
    a, sa = hatch(client, "Ana")
    b, sb = hatch(client, "Ben")
    c, sc = hatch(client, "Cal")
    client.post(f"/api/ghosts/{a}/bind", json={"other_id": b}, headers={"X-Ghost-Secret": sa})
    r = client.post(f"/api/ghosts/{c}/bind", json={"other_id": b}, headers={"X-Ghost-Secret": sc})
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Ben is already bound to someone else")
