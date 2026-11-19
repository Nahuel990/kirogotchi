# Kirogotchi: Requirements

## Introduction

Kirogotchi is a virtual pet whose alive-or-dead state is a qubit. Between
looks the ghost is in superposition. Opening the app prepares the state from
the ghost's care record, runs it on Amazon Braket, and measures once. The
pet is the Kiro ghost.

Kiroween 2026 categories: Resurrection (the Tamagotchi), Frankenstein
(a quantum SDK stitched to a virtual pet), Costume Contest (a haunting UI
with the Kiro ghost as the pet and a "kiro" easter egg).

## Requirements

### R1. Hatching
**User story:** As a player, I want to hatch a named ghost so that I have
one qubit to keep alive.
- 1.1 WHEN the player submits a name THEN the system SHALL create a ghost
  with `alive = true`, zero looks, and `last_care_at = last_look_at = now`.
- 1.2 WHEN a ghost is created THEN the system SHALL return an owner secret
  that is required for care, bind and look.
- 1.3 Names SHALL be trimmed to 24 characters; an empty name SHALL become
  "Kiro".

### R2. Reading is not measuring
**User story:** As a player, I want to see my ghost's care record without
collapsing it.
- 2.1 `GET /api/ghosts/{id}` SHALL return the classical record only and
  SHALL NOT run any circuit.
- 2.2 The UI SHALL render an unobserved ghost as two translucent copies
  (alive and gone) and never as a single solid ghost. Their brightness is the
  only hint to the odds; no number is shown.

### R3. Care as gates
**User story:** As a player, I want feeding and playing to be real rotations
on the qubit.
- 3.1 `feed` SHALL queue `RY(-π/4)`; `play` SHALL queue `RY(-π/6)`.
- 3.2 A care gate is the same fixed turn wherever the ghost is, so it can
  raise or lower the odds depending on the moment.
- 3.3 Queued gates SHALL be applied, in order, in the next look's circuit,
  then cleared.
- 3.4 Four consecutive feeds on a ghost that is fully alive SHALL rotate it
  to P(alive)=0 (overfeeding kills, as on a Tamagotchi).
- 3.5 Dragging the candle onto the ghost SHALL add a turn of random size,
  drawn once on the server and stored.

### R4. Constant turning
- 4.1 The ghost SHALL keep turning on its own: a seeded random walk with a new
  speed and direction every 3 seconds, one lap every 10 to 20 seconds.
- 4.2 The page and the server SHALL compute the same angle at the same moment.
- 4.3 There SHALL be no hours, no hunger and no drift.

### R5. The look
**User story:** As a player, I want "Look" to be a single real measurement.
- 5.1 `POST /api/ghosts/{id}/look` SHALL run the prepared circuit with
  `shots = 1` and SHALL use bit `1` as alive, `0` as dead.
- 5.2 The response SHALL include the circuit diagram, the device name, the
  measured bitstring and the exact P(alive) before measurement.
- 5.3 IF the outcome is dead THEN the ghost SHALL be marked departed and
  further care SHALL be rejected with 409.
- 5.4 A look SHALL increment `looks` and clear queued gates.

### R6. Binding (entanglement)
**User story:** As a player, I want to bind my ghost to a friend's so that
we share one fate.
- 6.1 Binding SHALL require both ghosts alive and unbound, and SHALL reject
  self-binding.
- 6.2 A look on a bound ghost SHALL run a two-qubit circuit: first ghost
  prepared, second ghost initialised dead, then `CNOT(0 → 1)`.
- 6.3 Both ghosts SHALL receive the same outcome and the bond SHALL be
  broken by the measurement.

### R7. Costume
- 7.1 The pet SHALL be the Kiro ghost, used under the Kiroween 2026
  Official Rules, with a trademark notice in README and the page footer.
- 7.2 Typing `k i r o` outside an input SHALL trigger the easter egg: a
  swarm of Kiro ghosts and the Kiro wordmark.
- 7.3 The page SHALL work at phone width with no horizontal scroll.

### R8. Honesty
- 8.1 The UI SHALL state that the qubit is re-prepared from the record on
  each look, and that only the single-shot measurement is real.
