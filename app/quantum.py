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
"""
from __future__ import annotations
import math
import os
from dataclasses import dataclass, field
from braket.circuits import Circuit
from braket.devices import LocalSimulator
ALIVE = 1
DEAD = 0
# Care rotations, in radians, applied toward |1>.
CARE_ANGLES = {
    "feed": math.pi / 4,
    "play": math.pi / 6,
}
@dataclass
class GhostState:
    """Classical record a circuit is built from."""
    care_gates: list[str] = field(default_factory=list)
    birth_angle: float = 0.0  # 0 is fully alive; pi/2 is the newborn half and half
    spin: float = 0.0  # how far its own constant turning has taken it since the last Look (app/spin.py)
def gate_angle(gate: str) -> float:
    """Turn of one press. The candle's fire is stored as 'fire:<radians>', a random turn."""
    if gate.startswith("fire:"):
        return float(gate[5:])
    return CARE_ANGLES.get(gate, 0.0)
def net_rotation(state: GhostState) -> float:
    """Total RY angle after birth, spin and all queued care gates."""
    theta = state.birth_angle + state.spin
    for gate in state.care_gates:
        theta -= gate_angle(gate)
    return theta
def _born_halfway(state: GhostState) -> bool:
    return abs(state.birth_angle - math.pi / 2) < 1e-9
def prepare(circuit: Circuit, qubit: int, state: GhostState) -> Circuit:
    """Append the preparation of one ghost on `qubit`."""
    circuit.x(qubit)  # alive...
    if _born_halfway(state):
        circuit.h(qubit)  # ...born halfway: Hadamard on |1> is the even mix, same state as Ry(pi/2) up to a phase
    elif state.birth_angle:
        circuit.ry(qubit, state.birth_angle)
    if abs(state.spin) >= 0.005:
        circuit.ry(qubit, state.spin)  # its own turning, a box of its own after the birth
    for gate in state.care_gates:
        circuit.ry(qubit, -gate_angle(gate))
    return circuit
def box_labels(state: GhostState) -> list[str]:
    """What each box of the single-ghost circuit was, in the order prepare() draws them."""
    labels = ["X"]
    if _born_halfway(state):
        labels.append("H")
    elif state.birth_angle:
        labels.append("start")
    if abs(state.spin) >= 0.005:
        labels.append("spin")
    for gate in state.care_gates:
        labels.append("candle" if gate.startswith("fire:") else gate)
    return labels
def ghost_circuit(state: GhostState) -> Circuit:
    return prepare(Circuit(), 0, state)
def bound_circuit(a: GhostState, b: GhostState) -> Circuit:
    """Two ghosts bound by a CNOT: qubit 0 decides, qubit 1 follows."""
    c = Circuit()
    prepare(c, 0, a)
    # The second ghost starts gone and is flipped alive only if the first is
    # alive. Its own record is irrelevant while bound; it shares a fate.
    c.cnot(0, 1)
    return c
def explain(state: GhostState) -> list[dict]:
    """One line per step that did something, in plain words."""
    theta = state.birth_angle
    if _born_halfway(state):
        # X and H belong together: they are the birth
        steps = [{"gate": "X H", "plain": "Born: a qubit starts at 0, gone. X flips it to 1, alive. H, the Hadamard gate, turns that into an exact half-and-half mix. That is a superposition."}]
    else:
        steps = [{"gate": "X", "plain": "Start: the ghost fully alive."}]
        if abs(theta) > 0.01:
            steps.append({"gate": f"Ry({theta:.2f})", "plain": "Start: where it began."})
    if abs(state.spin) > 0.01:
        theta += state.spin
        steps.append({"gate": f"Ry({state.spin:.2f})", "plain": "Spinning: where its own turning had taken it by the moment you looked."})
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
    pct = math.cos(theta / 2) ** 2 * 100
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
    """P(alive) by hand, used by the tests to check the simulator: RY(theta) on |1>."""
    return math.cos(net_rotation(state) / 2) ** 2
class Backend:
    """Runs circuits on the local density-matrix simulator or a Braket device."""

    def __init__(self, device_arn: str | None = None):
        self.device_arn = device_arn or os.environ.get("BRAKET_DEVICE_ARN")
        if self.device_arn:
            from braket.aws import AwsDevice  # noqa: WPS433 (optional import)

            self.device = AwsDevice(self.device_arn)
            self.is_qpu = True
            self.name = self.device.name
        else:
            self.device = LocalSimulator("braket_dm")
            self.is_qpu = False
            self.name = "Braket local density-matrix simulator"

    def _run(self, circuit: Circuit, shots: int) -> list[str]:
        result = self.device.run(circuit, shots=shots).result()
        return ["".join(str(b) for b in m) for m in result.measurements]

    def look(self, state: GhostState) -> dict:
        """One shot. Returns the outcome and the circuit that produced it."""
        circuit = ghost_circuit(state)
        bits = self._run(circuit, shots=1)[0]
        return {
            "alive": bits[0] == str(ALIVE),
            "bitstring": bits,
            "circuit": str(circuit),
            "steps": explain(state),
            "boxes": box_labels(state),
            "device": self.name,
        }

    def look_bound(self, a: GhostState, b: GhostState) -> dict:
        circuit = bound_circuit(a, b)
        bits = self._run(circuit, shots=1)[0]
        steps = explain(a)
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
            "device": self.name,
        }
