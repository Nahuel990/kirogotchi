"""Kirogotchi API. The only route that measures anything is /look."""

from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .quantum import (
    Backend,
    CARE_ANGLES,
    GhostState,
    gate_angle,
    probability_alive,
)
from . import spin
from .store import Ghost, Store

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Kirogotchi", version="0.1.0")
store = Store(os.environ.get("KIROGOTCHI_DB", str(ROOT / "kirogotchi.db")))
backend = Backend()



def _spin(g: Ghost, now: float) -> float:
    """How far the ring has turned for this ghost at `now`. Tests replace this to stop the motion."""
    return spin.angle(g.spin_seed, g.spin_t0, g.spin_base, now)


def _anchor(g: Ghost, now: float) -> None:
    """Start a new stretch of motion from where the ring is now; the angle does not jump."""
    g.spin_base = _spin(g, now)
    g.spin_t0 = now


def _state(g: Ghost, now: float) -> GhostState:
    # The birth, then the ring's own turning at this second; presses are added by the circuit.
    return GhostState(
        care_gates=list(g.care_gates),
        birth_angle=g.birth_angle,  # the birth stays its own step: X and H
        spin=math.remainder(_spin(g, now), 2 * math.pi),
    )


def _owned(ghost_id: str, secret: str | None) -> Ghost:
    g = store.get(ghost_id)
    if g is None:
        raise HTTPException(404, "No such ghost")
    if secret != g.secret:
        raise HTTPException(403, "Not your ghost")
    return g


def _view(g: Ghost, now: float) -> dict:
    d = g.public()
    d["birth_angle"] = g.birth_angle
    if g.bound_to:
        other = store.get(g.bound_to)
        d["bound_name"] = other.name if other else None
    d["pending_gates"] = [f"RY(-{gate_angle(x):.3f}) [{x.split(':')[0]}]" for x in g.care_gates]
    d["device"] = backend.name
    d["now"] = now  # the page uses this to compute the ring on the server's clock
    return d


class HatchBody(BaseModel):
    name: str = "Kiro"


class BindBody(BaseModel):
    other_id: str


@app.get("/api/device")
def device():
    """Which machine runs the looks. Honest by construction."""
    return {"name": backend.name, "is_qpu": backend.is_qpu, "arn": backend.device_arn}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/ghosts")
def hatch(body: HatchBody):
    g = store.hatch(body.name)
    d = _view(g, time.time())
    d["secret"] = g.secret
    return d


@app.get("/api/ghosts/{ghost_id}")
def status(ghost_id: str, x_ghost_secret: str | None = Header(default=None)):
    """Classical record only. Reading this is not a measurement."""
    g = store.get(ghost_id)
    if g is None:
        raise HTTPException(404, "No such ghost")
    d = _view(g, time.time())
    d["owned"] = x_ghost_secret == g.secret
    return d


@app.post("/api/ghosts/{ghost_id}/care/{action}")
def care(ghost_id: str, action: str, x_ghost_secret: str | None = Header(default=None)):
    if action not in CARE_ANGLES and action != "fire":
        raise HTTPException(400, f"Unknown care action {action!r}")
    g = _owned(ghost_id, x_ghost_secret)
    if not g.alive:
        raise HTTPException(409, "This ghost has departed")
    now = time.time()
    # the candle's fire is a turn of unknown size, drawn once and stored
    gate = f"fire:{random.uniform(0, 2 * math.pi):.4f}" if action == "fire" else action
    targets = [g]
    if g.bound_to:
        other = store.get(g.bound_to)
        if other is not None and other.alive and other.bound_to == g.id:
            targets.append(other)  # one spot for both: a press from either side moves it
    for x in targets:
        _anchor(x, now)
        x.last_care_at = now
        x.care_gates.append(gate)
        x.history.append({"t": now, "event": action, "by": g.name, "by_id": g.id})
        store.save(x)
    return _view(g, now)


@app.post("/api/ghosts/{ghost_id}/bind")
def bind(ghost_id: str, body: BindBody, x_ghost_secret: str | None = Header(default=None)):
    g = _owned(ghost_id, x_ghost_secret)
    other = store.get(body.other_id)
    if other is None:
        raise HTTPException(404, "No such ghost to bind")
    if other.id == g.id:
        raise HTTPException(400, "A ghost cannot be bound to itself")
    if not (g.alive and other.alive):
        raise HTTPException(409, "Only living ghosts can be bound")
    if g.bound_to:
        raise HTTPException(409, "Your ghost is already bound. A ghost binds to one friend at a time.")
    if other.bound_to:
        raise HTTPException(409, f"{other.name} is already bound to someone else. A ghost binds to one friend at a time.")
    now = time.time()
    g.bound_to, other.bound_to = other.id, g.id
    # Two ghosts, one spot. The friend's spot is the shared one, so the friend's screen does not jump.
    g.birth_angle = other.birth_angle
    g.last_look_at = other.last_look_at
    g.last_care_at = other.last_care_at
    g.care_gates = list(other.care_gates)
    g.spin_seed, g.spin_t0, g.spin_base = other.spin_seed, other.spin_t0, other.spin_base  # one ring for both
    for x in (g, other):
        x.history.append({"t": now, "event": "bound", "with": other.id if x is g else g.id})
        store.save(x)
    return _view(g, now)


@app.post("/api/ghosts/{ghost_id}/look")
def look(ghost_id: str, x_ghost_secret: str | None = Header(default=None)):
    """The measurement. One shot on Braket; the ghost collapses."""
    g = _owned(ghost_id, x_ghost_secret)
    if not g.alive:
        raise HTTPException(409, "This ghost has departed")
    now = time.time()
    state = _state(g, now)
    odds = probability_alive(state)

    if g.bound_to:
        other = store.get(g.bound_to)
        if other is None or not other.alive or other.bound_to != g.id:
            g.bound_to = None
            store.save(g)
            return look(ghost_id, x_ghost_secret)
        shot = backend.look_bound(state, _state(other, now))
        outcomes = {g.id: shot["alive_a"], other.id: shot["alive_b"]}
        for x in (g, other):
            _apply_outcome(x, outcomes[x.id], now)
            x.bound_to = None  # a measurement breaks the bond
        # The friend was not in the room. Leave the whole reveal in their record so
        # their screen can show it: same circuit, same answer, no second measurement.
        other.history[-1].update(
            {
                "by": g.name,
                "odds": odds,
                "circuit": shot["circuit"],
                "steps": shot["steps"],
                "bitstring": shot["bitstring"],
                "partner_alive": g.alive,
            }
        )
        for x in (g, other):
            store.save(x)
        result = _view(g, now)
        result.update(
            {
                "alive": g.alive,
                "odds_alive_before": odds,
                "bound_outcome": {"id": other.id, "name": other.name, "alive": other.alive},
                "circuit": shot["circuit"],
                "steps": shot["steps"],
                "bitstring": shot["bitstring"],
            }
        )
        return result

    shot = backend.look(state)
    _apply_outcome(g, shot["alive"], now)
    store.save(g)
    result = _view(g, now)
    result.update(
        {
            "alive": g.alive,
            "odds_alive_before": odds,
            "circuit": shot["circuit"],
            "boxes": shot["boxes"],
            "steps": shot["steps"],
            "bitstring": shot["bitstring"],
        }
    )
    return result


def _apply_outcome(g: Ghost, alive: bool, now: float) -> None:
    g.looks += 1
    g.last_look_at = now
    g.care_gates = []  # the gates were applied in this preparation
    if alive:
        g.birth_angle = 0.0  # found alive: the qubit is exactly |1>
        g.spin_base, g.spin_t0 = 0.0, now  # and the ring keeps turning from there
        g.history.append({"t": now, "event": "looked", "alive": True})
    else:
        g.alive = False
        g.departed_at = now
        g.history.append({"t": now, "event": "looked", "alive": False})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
