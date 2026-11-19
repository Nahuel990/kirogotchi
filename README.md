# Kirogotchi

**Schrödinger's Kiro.** A ghost pet that is alive and gone until you look.
Every look is a single-shot run of a quantum circuit on Amazon Braket: on
the local simulator by default, or on a real quantum computer when the
server is pointed at one.

A Kiroween 2026 entry. Resurrection (the 90s pocket pet, back), Frankenstein
(a quantum SDK stitched to a virtual pet), Costume Contest (the Kiro ghost is
the pet).

## How it works

Your ghost is one qubit. `|1⟩` is alive, `|0⟩` is gone.

| You do | The qubit gets |
|---|---|
| Hatch | `X` then `H` (Hadamard): born exactly half alive, half gone |
| nothing | it keeps turning on its own: an `Ry` whose angle comes from a seeded random walk, with a new speed and direction every 3 seconds |
| Feed | `Ry(−π/4)`: a fixed turn, a gate |
| Play | `Ry(−π/6)`: a smaller fixed turn, a gate |
| Candle on the ghost | an `Ry` of a random size nobody knows: the game's picture of decoherence |
| Bind with a friend | both records become one; on the look, `CNOT`: both alive or both gone |
| **Look** | **one shot. The ghost collapses. Found alive, it is `\|1⟩` exactly and keeps turning from there. Gone is final.** |

A gate is the same turn wherever the ghost is, so the same press can raise
the odds at one moment and lower them at the next. The goal is to survive as
many Looks as you can.

Reading the care record is not a measurement. Only *Look* runs a circuit.
The page and the server compute the same turning from the same seed, so the
two ghosts on screen (the only hint) show the odds the Look will use.

Honest note: real qubits decohere in microseconds, so the state is prepared
fresh from the record each time you look, on the Amazon Braket local
simulator. The single-shot measurement is real.

## For people who are not physicists

The ghost circles a ring that never stops turning. Two ghosts are drawn, one
alive and one gone: they are the only hint. Feed and Play
turn it a fixed amount, the candle turns it by an amount nobody knows, and
Look forces one answer. "What is quantum?" explains qubit, superposition,
gate, measurement, decoherence and entanglement. "How to play" explains the
game. After each Look, "Show me what happened" shows the real circuit with a
label under every box.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Tests:

```bash
.venv/bin/python -m pytest -q -W ignore
```

### Real quantum hardware

Set `BRAKET_DEVICE_ARN` and AWS credentials and every look becomes a task on
that device. This costs money per look.

```bash
BRAKET_DEVICE_ARN=arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1 .venv/bin/uvicorn app.main:app
```

### Docker

```bash
docker build -t kirogotchi . && docker run -p 8000:8000 -v kirogotchi-data:/data kirogotchi
```

## Easter egg

Type `k i r o` anywhere outside an input.

## How Kiro was used

- The idea and the plan came out of Kiro, written as a spec before any code.
- `.kiro/specs/kirogotchi/` holds the requirements (EARS-style), the design
  and the task list the build followed.
- `.kiro/steering/` fixes the rules: only `/look` measures, every mechanic
  maps to a real gate or channel, honest copy, no fake quantum.
- `.kiro/hooks/test-on-save.kiro.hook` reruns the suite on any change under
  `app/` and keeps the closed-form probability in sync with the circuit.
- `.kiro/hooks/spec-sync.kiro.hook` checks UI claims against the model
  whenever page copy changes.

## License

Apache-2.0, see `LICENSE`.

The Kiro ghost and wordmark (`static/kiro-ghost.svg`, `static/kiro-wordmark.png`)
are trademarks of Amazon Web Services, Inc., used in this Kiroween 2026
submission under the Kiroween 2026 Official Rules. They are not covered by
the Apache license and must not be reused outside this context.
