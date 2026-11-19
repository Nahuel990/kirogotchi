"""Quantum model of a Kirogotchi.

One qubit per ghost. |1> is alive, |0> is gone. Between looks nobody measures
the qubit, so the ghost is in a superposition. Each Look prepares the state from
the ghost's classical record, runs it on Amazon Braket and measures once.

Physics used:

* Birth is X then H: exactly half and half.
* The ghost keeps turning on its own: an RY whose angle is a seeded random walk
  (app/spin.py), the same on the page and on the server.
* Feed and Play are fixed RY turns (gates). The candle is an RY of random size.
* Two ghosts are bound with a CNOT: one answer for both.

The hours/hunger and depolarizing helpers below are kept for the tests and a
possible QPU mode; the game passes zero hours, so they do nothing in play.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from braket.circuits import Circuit
from braket.devices import LocalSimulator

ALIVE = 1
DEAD = 0

# Hours of hunger before P(dead) reaches 1 with no care at all.
LIFETIME_HOURS = 24.0
# Hours of not looking before the state is fully depolarized.
COHERENCE_HOURS = 72.0
# Care rotations, in radians, applied toward |1>.
CARE_ANGLES = {
    "feed": math.pi / 4,
    "play": math.pi / 6,
}


@dataclass
class GhostState:
    """Classical record a circuit is built from."""

    hours_since_care: float
    hours_since_look: float
    care_gates: list[str] = field(default_factory=list)
    birth_angle: float = 0.0  # a newborn ghost is already somewhere between alive and dead
    spin: float = 0.0  # how far its own constant turning has taken it since the last Look (app/spin.py)


def hunger_angle(hours_since_care: float) -> float:
    frac = max(0.0, min(1.0, hours_since_care / LIFETIME_HOURS))
    return math.pi * frac


def depolarizing_probability(hours_since_look: float) -> float:
    if hours_since_look <= 0:
        return 0.0
    # Three quarters is the maximum for a single-qubit depolarizing channel.
    return 0.75 * (1.0 - math.exp(-hours_since_look / COHERENCE_HOURS))


def gate_angle(gate: str) -> float:
    """Turn of one press. The candle's fire is stored as 'fire:<radians>', a random turn."""
    if gate.startswith("fire:"):
        return float(gate[5:])
    return CARE_ANGLES.get(gate, 0.0)


def effective_hunger(state: GhostState) -> float:
    """Hunger cannot roll a ghost past the bottom: birth + hunger is capped at pi."""
    return max(0.0, min(hunger_angle(state.hours_since_care), math.pi - state.birth_angle))


def net_rotation(state: GhostState) -> float:
    """Total RY angle after birth, hunger and all queued care gates."""
    theta = state.birth_angle + state.spin + effective_hunger(state)
    for gate in state.care_gates:
        theta -= gate_angle(gate)
    return theta


def prepare(circuit: Circuit, qubit: int, state: GhostState, *, noise: bool) -> Circuit:
    """Append the preparation of one ghost on `qubit`."""
    circuit.x(qubit)  # alive...
    if abs(state.birth_angle - math.pi / 2) < 1e-9:
        circuit.h(qubit)  # ...born halfway: Hadamard on |1> is the even mix, same state as Ry(pi/2) up to a phase
    elif state.birth_angle:
        circuit.ry(qubit, state.birth_angle)
    if abs(state.spin) >= 0.005:
        circuit.ry(qubit, state.spin)  # its own turning, a box of its own after the birth
    h = effective_hunger(state)
    if h >= 0.005:  # under 0.005 (about 2 minutes of hunger) it prints as Ry(0.00); leaving it out moves the odds by at most a quarter of one percent
        circuit.ry(qubit, h)  # hunger; a zero turn is left out so every box did something
    for gate in state.care_gates:
        circuit.ry(qubit, -gate_angle(gate))
    if noise:
        p = depolarizing_probability(state.hours_since_look)
        if p > 0:
            circuit.depolarizing(qubit, p)
    return circuit


def box_labels(state: GhostState, *, noise: bool) -> list[str]:
    """What each box of the single-ghost circuit was, in the order prepare() draws them."""
    labels = ["X"]
    if abs(state.birth_angle - math.pi / 2) < 1e-9:
        labels.append("H")
    elif state.birth_angle:
        labels.append("start")
    if abs(state.spin) >= 0.005:
        labels.append("spin")
    if effective_hunger(state) >= 0.005:
        labels.append("hunger")
    for gate in state.care_gates:
        labels.append("candle" if gate.startswith("fire:") else gate)
    if noise and depolarizing_probability(state.hours_since_look) > 0:
        labels.append("noise")
    return labels


def ghost_circuit(state: GhostState, *, noise: bool = True) -> Circuit:
    return prepare(Circuit(), 0, state, noise=noise)


def bound_circuit(a: GhostState, b: GhostState, *, noise: bool = True) -> Circuit:
    """Two ghosts bound by a CNOT: qubit 0 decides, qubit 1 follows."""
    c = Circuit()
    prepare(c, 0, a, noise=noise)
    # The second ghost starts dead and is flipped alive only if the first is
    # alive. Its own record is irrelevant while bound; it shares a fate. No
    # noise on q1: a bump there before the CNOT would give the pair two
    # different answers, and the game promises one.
    c.cnot(0, 1)
    return c


def _p(theta: float, p_noise: float = 0.0) -> float:
    return (1 - 4 * p_noise / 3) * math.cos(theta / 2) ** 2 + 2 * p_noise / 3


def cause(state: GhostState) -> str:
    """What mostly decided the odds: 'fresh', 'hunger', 'full_care' or 'neglect'."""
    theta = net_rotation(state)
    p_noise = depolarizing_probability(state.hours_since_look)
    if p_noise > 0.3:
        return "neglect"
    if state.care_gates and theta < -0.05:
        return "full_care"
    if effective_hunger(state) > 0.05:
        return "hunger"
    if state.birth_angle > 0.05:
        return "birth"
    return "fresh"


def marks(angle: float) -> int:
    """Angle to steps on the wheel: top to bottom is 24 steps, one per hour."""
    return round(abs(angle) / math.pi * LIFETIME_HOURS)


def explain(state: GhostState, *, noise: bool) -> list[dict]:
    """One line per step that did something, in wheel steps a child can add up."""
    theta = state.birth_angle
    if abs(theta - math.pi / 2) < 1e-9:
        # X and H belong together: they are the birth
        steps = [{"gate": "X H", "plain": "Born: a qubit starts at 0, gone. X flips it to 1, alive. H, the Hadamard gate, turns that into an exact half-and-half mix. That is a superposition."}]
    else:
        steps = [{"gate": "X", "plain": "Start: the ghost fully alive."}]
        if abs(theta) > 0.01:
            steps.append({"gate": f"Ry({theta:.2f})", "plain": "Start: where it began."})
    if abs(state.spin) > 0.01:
        theta += state.spin
        steps.append({"gate": f"Ry({state.spin:.2f})", "plain": "Spinning: where its own turning had taken it by the moment you looked."})
    h = effective_hunger(state)
    if h > 0.01:
        theta += h
        steps.append({"gate": f"Ry({h:.2f})", "plain": f"Hours: nothing holds it up, so every hour turns it 1 step down. {state.hours_since_care:.0f} hours = {marks(h)} steps. Now {marks(theta)} from the top."})
    if state.care_gates:
        feeds = state.care_gates.count("feed")
        plays = state.care_gates.count("play")
        n = len(state.care_gates)
        total = sum(gate_angle(g) for g in state.care_gates)
        fires = sum(1 for g in state.care_gates if g.startswith("fire:"))
        theta -= total
        parts = [f"{feeds} Feed{'s' if feeds > 1 else ''}" if feeds else "", f"{plays} Play{'s' if plays > 1 else ''}" if plays else "", "the candle" if fires == 1 else (f"the candle {fires} times" if fires else "")]
        presses = " and ".join(x for x in parts if x)
        plain = f"Your presses: {presses}. Each one is a gate, a turn of a fixed size."
        if fires:
            plain += " The candle's turn was a size nobody knew."
        steps.append({"gate": f"Ry({-total:.2f})" if n == 1 else f"{n} x Ry", "plain": plain})
    p_noise = 0.0
    if noise:
        p_noise = depolarizing_probability(state.hours_since_look)
        if p_noise / 0.75 >= 0.01:
            steps.append({"gate": f"DEPO({p_noise:.2g})", "plain": f"Bumps: nobody looked for {state.hours_since_look:.0f} hours, and the world bumps a ghost nobody is watching. Each bump moves it a random step. After {p_noise / 0.75 * 100:.0f}% scrambling the ghost has drifted toward the middle of the wheel, where a look finds it alive about half the time, whatever you did."})
    pct = _p(theta, p_noise) * 100
    if pct >= 99.95:
        odds = "it was alive for sure"
    elif pct <= 0.05:
        odds = "it was gone for sure"
    else:
        odds = f"it was alive {pct:.0f} times in 100, gone {100 - pct:.0f}"
    steps.append({"gate": "measure", "plain": f"Look: the ghost is forced to be alive or gone. At that moment {odds}."})
    return steps


def probability_alive(state: GhostState) -> float:
    """Exact P(alive) from the density-matrix simulator (no measurement)."""
    c = ghost_circuit(state).probability(target=[0])
    result = LocalSimulator("braket_dm").run(c, shots=0).result()
    probs = result.values[0]
    return float(probs[ALIVE])


def probability_alive_closed_form(state: GhostState) -> float:
    """P(alive) by hand, used by the tests to check the simulator."""
    theta = net_rotation(state)
    coherent_alive = math.cos(theta / 2) ** 2
    p = depolarizing_probability(state.hours_since_look)
    # Depolarizing with probability p mixes toward I/2: rho -> (1-p) rho + p I/2
    # Braket's channel with parameter p applies X, Y or Z each with p/3,
    # which maps a diagonal element d to (1 - 4p/3) d + 2p/3.
    return (1 - 4 * p / 3) * coherent_alive + 2 * p / 3


class Backend:
    """Runs circuits on the local density-matrix simulator or a Braket device."""

    def __init__(self, device_arn: str | None = None):
        self.device_arn = device_arn or os.environ.get("BRAKET_DEVICE_ARN")
        if self.device_arn:
            from braket.aws import AwsDevice  # noqa: WPS433 (optional import)

            self.device = AwsDevice(self.device_arn)
            self.noise_supported = False
            self.name = self.device.name
        else:
            self.device = LocalSimulator("braket_dm")
            self.noise_supported = True
            self.name = "Braket local density-matrix simulator"

    def _run(self, circuit: Circuit, shots: int) -> list[str]:
        result = self.device.run(circuit, shots=shots).result()
        return ["".join(str(b) for b in m) for m in result.measurements]

    def look(self, state: GhostState) -> dict:
        """One shot. Returns the outcome and the circuit that produced it."""
        circuit = ghost_circuit(state, noise=self.noise_supported)
        bits = self._run(circuit, shots=1)[0]
        return {
            "alive": bits[0] == str(ALIVE),
            "bitstring": bits,
            "circuit": str(circuit),
            "steps": explain(state, noise=self.noise_supported),
            "boxes": box_labels(state, noise=self.noise_supported),
            "cause": cause(state),
            "device": self.name,
        }

    def look_bound(self, a: GhostState, b: GhostState) -> dict:
        circuit = bound_circuit(a, b, noise=self.noise_supported)
        bits = self._run(circuit, shots=1)[0]
        steps = explain(a, noise=self.noise_supported)
        steps.insert(-1, {
            "gate": "CNOT",
            "plain": "Bound: both ghosts are one thing on one spot, so there is only one answer to find. That is entanglement.",
        })
        steps[-1]["plain"] = "Look: one thing to check, so one look answers both. The computer answers 11 for both alive, 00 for both gone. Nothing travelled between them."
        return {
            "alive_a": bits[0] == str(ALIVE),
            "alive_b": bits[1] == str(ALIVE),
            "bitstring": bits,
            "circuit": str(circuit),
            "steps": steps,
            "cause": cause(a),
            "device": self.name,
        }
