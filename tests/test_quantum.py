import math
import pytest
from app.quantum import (
    Backend,
    CARE_ANGLES,
    GhostState,
    bound_circuit,
    box_labels,
    explain,
    ghost_circuit,
    net_rotation,
    probability_alive,
    probability_alive_closed_form,
)
HALF = math.pi / 2
def test_fresh_ghost_is_certainly_alive():
    assert probability_alive(GhostState()) == pytest.approx(1.0, abs=1e-6)
def test_overfeeding_wraps_past_alive():
    # Four feeds is pi: rotates a fully alive ghost all the way to gone.
    s = GhostState(care_gates=["feed"] * 4)
    assert probability_alive(s) == pytest.approx(0.0, abs=1e-6)
@pytest.mark.parametrize("gates,birth,spin", [
    ([], 0.0, 0.0),
    ([], HALF, 0.0),
    (["feed", "play"], HALF, 0.0),
    (["play"], 0.0, 1.3),
    (["feed", "fire:2.1000"], HALF, -2.4),
])
def test_simulator_matches_closed_form(gates, birth, spin):
    s = GhostState(gates, birth_angle=birth, spin=spin)
    assert probability_alive(s) == pytest.approx(probability_alive_closed_form(s), abs=1e-6)
def test_bound_ghosts_share_a_fate():
    a = GhostState(birth_angle=HALF)
    b = GhostState()
    backend = Backend()
    outcomes = {backend.look_bound(a, b)["bitstring"] for _ in range(40)}
    # Only correlated outcomes are possible: both gone (00) or both alive (11).
    assert outcomes <= {"00", "11"}
    assert len(outcomes) == 2, "a half-and-half ghost should give both outcomes in 40 shots"
def test_bound_ghosts_agree_whatever_the_partner_record():
    a = GhostState(["play"], birth_angle=HALF, spin=0.4)
    b = GhostState(["feed"] * 3, spin=2.0)
    be = Backend()
    for _ in range(30):
        r = be.look_bound(a, b)
        assert r["alive_a"] == r["alive_b"], r["bitstring"]
def test_bound_circuit_contains_cnot():
    a = GhostState()
    text = str(bound_circuit(a, a))
    assert "●" in text and "q1" in text  # control dot on q0, target X on q1
def test_single_look_is_one_shot():
    r = Backend().look(GhostState())
    assert r["alive"] is True
    assert r["bitstring"] == "1"
    assert "local" in r["device"].lower()
def test_circuit_has_no_noise_channel():
    s = GhostState(["feed", "fire:1.0000"], birth_angle=HALF, spin=0.7)
    assert "DEPO" not in str(ghost_circuit(s))
def test_care_angles_are_positive_and_small():
    for angle in CARE_ANGLES.values():
        assert 0 < angle < math.pi / 2
def test_explain_matches_circuit_order():
    s = GhostState(["play", "feed"], spin=0.5)
    steps = explain(s)
    assert [st["gate"] for st in steps] == ["X", "Ry(0.50)", "2 x Ry", "measure"]
    assert "1 Feed and 1 Play" in steps[2]["plain"]
    assert "gate" in steps[2]["plain"]
def test_explain_drops_steps_that_change_nothing():
    steps = explain(GhostState(["feed"], spin=0.001))
    assert [st["gate"] for st in steps] == ["X", "Ry(-0.79)", "measure"]
def test_birth_angle_sets_the_starting_odds():
    assert probability_alive(GhostState(birth_angle=0.0)) == pytest.approx(1.0, abs=1e-6)
    assert probability_alive(GhostState(birth_angle=HALF)) == pytest.approx(0.5, abs=1e-6)
    assert probability_alive(GhostState(birth_angle=math.pi)) == pytest.approx(0.0, abs=1e-6)
def test_feeding_a_half_born_ghost_helps():
    s = GhostState(["feed"], birth_angle=HALF)
    assert probability_alive(s) == pytest.approx(math.cos(math.pi / 8) ** 2, abs=1e-6)
def test_many_presses_are_one_step_with_laps():
    steps = explain(GhostState(["play"] * 14 + ["feed"] * 13))
    assert [st["gate"] for st in steps] == ["X", "27 x Ry", "measure"]
    assert "13 Feeds and 14 Plays" in steps[1]["plain"]
def test_candle_is_a_turn_of_its_stored_size():
    s = GhostState(["fire:1.2345"])
    assert net_rotation(s) == pytest.approx(-1.2345)
    assert box_labels(s) == ["X", "candle"]
    assert "nobody knew" in explain(s)[1]["plain"]
def test_born_halfway_is_a_hadamard_and_fifty_fifty():
    s = GhostState(birth_angle=HALF)
    assert probability_alive(s) == pytest.approx(0.5, abs=1e-6)
    assert "H" in str(ghost_circuit(s))
    feed = GhostState(["feed"], birth_angle=HALF)
    assert probability_alive(feed) == pytest.approx(probability_alive_closed_form(feed), abs=1e-6)
    assert explain(s)[0]["gate"] == "X H"  # X and H are one step: the birth
def test_spin_is_its_own_box_after_the_birth():
    s = GhostState(["feed"], birth_angle=HALF, spin=0.7)
    text = str(ghost_circuit(s))
    assert "H" in text and "Ry(0.70)" in text
    assert box_labels(s) == ["X", "H", "spin", "feed"]
    assert [st["gate"] for st in explain(s)] == ["X H", "Ry(0.70)", "Ry(-0.79)", "measure"]
    assert probability_alive(s) == pytest.approx(probability_alive_closed_form(s), abs=1e-6)
