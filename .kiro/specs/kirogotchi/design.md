# Kirogotchi: Design

## Overview

```
browser (static/)  ──fetch──▶  FastAPI (app/main.py)
                               ├── store.py   SQLite: ghosts table
                               └── quantum.py Braket circuits + Backend
                                              ├── LocalSimulator("braket_dm")  default
                                              └── AwsDevice(BRAKET_DEVICE_ARN)  optional QPU
```

One qubit per ghost. `|1⟩` alive, `|0⟩` gone.

## Quantum model (quantum.py, spin.py)

Preparation for a ghost with record `(birth_angle, spin_seed, spin_t0, spin_base, care_gates)` at time t:

```
X                      start alive
H                      born exactly half and half (Hadamard), until the first look
RY(spin(t))            its own turning: seeded random walk, new speed and direction every 3 s
RY(-a) per care gate   feed a = pi/4, play a = pi/6, candle a = random, stored as "fire:<a>"
```

Closed form used by tests: `P(alive) = cos^2(theta_net/2)` (no noise channel; hours are gone).

spin(t) is computed by the same seeded function in app/spin.py and static/app.js,
so the two ghosts on the page show the odds the Look uses. A press anchors the
motion (spin_base, spin_t0) so the angle never jumps.

Bound pair: on bind the binder adopts the friend's record and ring, and every care
press applies to both records. On look, prepare qubit 0 from that record, qubit 1
stays `|0>`, then `CNOT(0, 1)`. Outcomes are `00` or `11` only.

### Why density matrix
The local density-matrix simulator gives the exact P(alive) with `shots=0`
(`probability_alive`) and one shot for `look`.

### QPU mode
`BRAKET_DEVICE_ARN` switches `Backend` to `AwsDevice`. Noise channels are
not QPU instructions, so `noise_supported = False` drops them; the hardware
supplies real decoherence. This costs money per task and needs AWS
credentials; it is meant for the demo video, not the public URL.

## Storage (store.py)

SQLite, one table. The owner secret is a 24-byte urlsafe token returned
once at hatch and sent back as `X-Ghost-Secret`. History is capped at 50
events.

## API (main.py)

| Method | Path | Measures? |
|---|---|---|
| POST | /api/ghosts | no |
| GET | /api/ghosts/{id} | no |
| POST | /api/ghosts/{id}/care/{feed\|play\|fire} | no |
| POST | /api/ghosts/{id}/bind | no |
| POST | /api/ghosts/{id}/look | **yes, one shot** |

## UI (static/)

- Unobserved: `.superposed` renders two translucent copies with
  `mix-blend-mode: screen`, one hovering, one sinking with closed eyes.
- Look: `.collapsing` converges the copies for 950 ms while the request
  runs, then `.alive-collapsed` (solid, bounce, blink) or `.dead-collapsed`
  (tombstone rises).
- Final screen says what turned the ghost (its own turning, the gates, the
  candle), then the measurement. Behind "Show me what happened": the real
  Braket circuit with a label under each box, a key, and the bitstring.
  Closing the box re-renders as unobserved if alive.
- Animations: Feed (the ghost chews a hamburger, the bits fall through it),
  Play (jump and spin), the candle (the ghost glows as fire, sparks, smoke),
  eyes that glance at the viewer.
- Easter egg: keydown buffer of the last four keys equals `kiro`.

## Error handling

404 unknown ghost, 403 wrong secret, 409 departed or already bound, 400 bad
care action or self-bind. A bound partner that has since departed silently
unbinds and the look proceeds single-qubit.

## Testing

- `tests/test_quantum.py`: closed form vs simulator, birth, gates, entanglement
  correlations (40 shots, only `00`/`11`).
- `tests/test_spin.py`: speed bounds, direction changes, continuity, and the
  page's JavaScript giving the same angle as the server.
- `tests/test_api.py`: full flows through FastAPI's TestClient with a temp
  database.
