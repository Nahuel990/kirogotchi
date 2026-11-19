import math

import pytest

from app.quantum import (
    Backend,
    CARE_ANGLES,
    GhostState,
    bound_circuit,
    depolarizing_probability,
    ghost_circuit,
    hunger_angle,
    probability_alive,
    probability_alive_closed_form,
)


def test_fresh_ghost_is_certainly_alive():
    s = GhostState(hours_since_care=0, hours_since_look=0)
    assert probability_alive(s) == pytest.approx(1.0, abs=1e-6)


def test_starved_ghost_is_certainly_dead():
    s = GhostState(hours_since_care=24, hours_since_look=0)
    assert probability_alive(s) == pytest.approx(0.0, abs=1e-6)


def test_half_starved_is_half_alive():
    s = GhostState(hours_since_care=12, hours_since_look=0)
    assert probability_alive(s) == pytest.approx(0.5, abs=1e-9)


def test_hunger_angle_saturates():
    assert hunger_angle(0) == 0
    assert hunger_angle(24) == pytest.approx(math.pi)
    assert hunger_angle(240) == pytest.approx(math.pi)


def test_feeding_rotates_back_toward_alive():
    hungry = GhostState(hours_since_care=12, hours_since_look=0)
    fed = GhostState(hours_since_care=12, hours_since_look=0, care_gates=["feed"])
    assert probability_alive(fed) > probability_alive(hungry)


def test_overfeeding_wraps_past_alive():
    # Four feeds is pi: rotates a fresh ghost all the way to dead.
    s = GhostState(hours_since_care=0, hours_since_look=0, care_gates=["feed"] * 4)
    assert probability_alive(s) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("hours_care,hours_look,gates", [
    (0, 0, []),
    (6, 0, []),
    (6, 10, []),
    (20, 100, ["feed", "play"]),
    (3, 400, ["play"]),
])
def test_simulator_matches_closed_form(hours_care, hours_look, gates):
    s = GhostState(hours_care, hours_look, gates)
    assert probability_alive(s) == pytest.approx(probability_alive_closed_form(s), abs=1e-6)


def test_depolarizing_never_exceeds_three_quarters():
    assert depolarizing_probability(0) == 0
    assert depolarizing_probability(1e6) == pytest.approx(0.75)


def test_long_unobserved_ghost_tends_to_the_middle():
    s = GhostState(hours_since_care=0, hours_since_look=10_000)
    assert probability_alive(s) == pytest.approx(0.5, abs=1e-3)


def test_circuit_has_no_noise_when_disabled():
    s = GhostState(hours_since_care=1, hours_since_look=50)
    assert "DEPO" in str(ghost_circuit(s, noise=True))
    assert "DEPO" not in str(ghost_circuit(s, noise=False))


def test_bound_ghosts_share_a_fate():
    a = GhostState(hours_since_care=12, hours_since_look=0)
    b = GhostState(hours_since_care=0, hours_since_look=0)
    backend = Backend()
    outcomes = {backend.look_bound(a, b)["bitstring"] for _ in range(40)}
    # Only correlated outcomes are possible: both dead (00) or both alive (11).
    assert outcomes <= {"00", "11"}
    assert len(outcomes) == 2, "12h hunger should give both outcomes in 40 shots"


def test_bound_circuit_contains_cnot():
    a = GhostState(0, 0)
    text = str(bound_circuit(a, a))
    assert "●" in text and "q1" in text  # control dot on q0, target X on q1


def test_single_look_is_one_shot():
    backend = Backend()
    r = backend.look(GhostState(0, 0))
    assert r["alive"] is True
    assert r["bitstring"] == "1"
    assert "local" in r["device"].lower()


def test_care_angles_are_positive_and_small():
    for angle in CARE_ANGLES.values():
        assert 0 < angle < math.pi / 2


def test_explain_matches_circuit_order():
    from app.quantum import explain
    s = GhostState(hours_since_care=6, hours_since_look=10, care_gates=["play", "feed"])
    steps = explain(s, noise=True)
    gates = [st["gate"] for st in steps]
    assert gates[0] == "X"
    assert gates[1].startswith("Ry(0.79)")       # 6h of 24 = pi/4
    assert gates[2] == "2 x Ry"                   # all presses explained once
    assert gates[3].startswith("DEPO(")
    assert gates[-1] == "measure"
    assert "1 Feed and 1 Play" in steps[2]["plain"]
    assert "gate" in steps[2]["plain"]


def test_explain_drops_steps_that_change_nothing():
    from app.quantum import explain
    steps = explain(GhostState(0, 0.0003, ["feed"]), noise=True)
    assert [st["gate"] for st in steps] == ["X", "Ry(-0.79)", "measure"]
    assert "gate" in steps[1]["plain"]


def test_cause_names_the_real_reason():
    from app.quantum import cause
    assert cause(GhostState(0, 0, ["feed"])) == "full_care"
    assert cause(GhostState(12, 0)) == "hunger"
    assert cause(GhostState(0, 0)) == "fresh"
    assert cause(GhostState(0, 500)) == "neglect"


def test_explain_without_noise_has_no_depo():
    from app.quantum import explain
    assert not any(st["gate"].startswith("DEPO") for st in explain(GhostState(1, 50), noise=False))


def test_one_feed_restores_six_hours_of_hunger_exactly():
    s = GhostState(hours_since_care=6, hours_since_look=0, care_gates=["feed"])
    assert probability_alive(s) == pytest.approx(1.0, abs=1e-6)


def test_one_play_restores_four_hours_exactly():
    s = GhostState(hours_since_care=4, hours_since_look=0, care_gates=["play"])
    assert probability_alive(s) == pytest.approx(1.0, abs=1e-6)


def test_birth_angle_sets_the_starting_odds():
    assert probability_alive(GhostState(0, 0, birth_angle=0.0)) == pytest.approx(1.0, abs=1e-6)
    assert probability_alive(GhostState(0, 0, birth_angle=math.pi / 2)) == pytest.approx(0.5, abs=1e-6)
    assert probability_alive(GhostState(0, 0, birth_angle=math.pi)) == pytest.approx(0.0, abs=1e-6)


def test_feeding_a_half_born_ghost_helps():
    s = GhostState(0, 0, ["feed"], birth_angle=math.pi / 2)
    assert probability_alive(s) == pytest.approx(math.cos(math.pi / 8) ** 2, abs=1e-6)


def test_many_presses_are_one_step_with_laps():
    from app.quantum import explain
    steps = explain(GhostState(0, 0, ["play"] * 14 + ["feed"] * 13), noise=False)
    assert [st["gate"] for st in steps] == ["X", "27 x Ry", "measure"]
    assert "13 Feeds and 14 Plays" in steps[1]["plain"]


def test_hunger_cannot_roll_past_the_bottom():
    """A ghost born low and left a day sits at the bottom, not back near the top."""
    from app.quantum import GhostState, probability_alive_closed_form, probability_alive, net_rotation
    import math
    s = GhostState(hours_since_care=24, hours_since_look=0, birth_angle=3.0)
    assert abs(net_rotation(s) - math.pi) < 1e-9
    assert probability_alive_closed_form(s) < 0.01
    assert probability_alive(s) < 0.01


def test_bound_ghosts_agree_even_when_the_partner_was_neglected():
    from app.quantum import Backend, GhostState
    a = GhostState(hours_since_care=12, hours_since_look=12)
    b = GhostState(hours_since_care=400, hours_since_look=400)
    be = Backend()
    for _ in range(30):
        r = be.look_bound(a, b)
        assert r["alive_a"] == r["alive_b"], r["bitstring"]


def test_born_halfway_is_a_hadamard_and_fifty_fifty():
    from app.quantum import GhostState, ghost_circuit, explain
    s = GhostState(0, 0, birth_angle=math.pi / 2)
    assert probability_alive(s) == pytest.approx(0.5, abs=1e-6)
    assert "H" in str(ghost_circuit(s, noise=False))
    feed = GhostState(0, 0, ["feed"], birth_angle=math.pi / 2)
    assert probability_alive(feed) == pytest.approx(probability_alive_closed_form(feed), abs=1e-6)
    assert explain(s, noise=False)[0]["gate"] == "X H"  # X and H are one step: the birth


def test_spin_is_its_own_box_after_the_birth():
    from app.quantum import explain
    s = GhostState(0, 0, ["feed"], birth_angle=math.pi / 2, spin=0.7)
    text = str(ghost_circuit(s, noise=False))
    assert "H" in text and "Ry(0.70)" in text
    assert [st["gate"] for st in explain(s, noise=False)] == ["X H", "Ry(0.70)", "Ry(-0.79)", "measure"]
    assert probability_alive(s) == pytest.approx(probability_alive_closed_form(s), abs=1e-6)
