"""SQLite storage for ghosts. One table, JSON for the small lists."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict

HALFWAY = 1.5707963267948966  # pi/2, twelve steps down: the 50/50 superposition

SCHEMA = """
CREATE TABLE IF NOT EXISTS ghosts (
    id TEXT PRIMARY KEY,
    secret TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_care_at REAL NOT NULL,
    last_look_at REAL NOT NULL,
    care_gates TEXT NOT NULL,
    alive INTEGER NOT NULL,
    departed_at REAL,
    looks INTEGER NOT NULL,
    bound_to TEXT,
    history TEXT NOT NULL,
    birth_angle REAL NOT NULL DEFAULT 0,
    spin_seed INTEGER NOT NULL DEFAULT 0,
    spin_t0 REAL NOT NULL DEFAULT 0,
    spin_base REAL NOT NULL DEFAULT 0
);
"""
# columns added after the first release; older databases get them on start
NEW_COLUMNS = {
    "spin_seed": "INTEGER NOT NULL DEFAULT 0",
    "spin_t0": "REAL NOT NULL DEFAULT 0",
    "spin_base": "REAL NOT NULL DEFAULT 0",
}


@dataclass
class Ghost:
    id: str
    secret: str
    name: str
    created_at: float
    last_care_at: float
    last_look_at: float
    care_gates: list[str]
    alive: bool
    departed_at: float | None
    looks: int
    bound_to: str | None
    history: list[dict]
    birth_angle: float = 0.0  # radians from alive, unknown to the player until they look
    spin_seed: int = 0  # the ring's random motion comes from this seed (app/spin.py)
    spin_t0: float = 0.0  # when the current stretch of motion started
    spin_base: float = 0.0  # how far the ring had turned at spin_t0

    def public(self) -> dict:
        d = asdict(self)
        d.pop("secret")
        return d


class Store:
    def __init__(self, path: str = "kirogotchi.db"):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)
            have = {r["name"] for r in c.execute("PRAGMA table_info(ghosts)")}
            for col, decl in NEW_COLUMNS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE ghosts ADD COLUMN {col} {decl}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_ghost(row: sqlite3.Row) -> Ghost:
        return Ghost(
            id=row["id"],
            secret=row["secret"],
            name=row["name"],
            created_at=row["created_at"],
            last_care_at=row["last_care_at"],
            last_look_at=row["last_look_at"],
            care_gates=json.loads(row["care_gates"]),
            alive=bool(row["alive"]),
            departed_at=row["departed_at"],
            looks=row["looks"],
            bound_to=row["bound_to"],
            history=json.loads(row["history"]),
            birth_angle=row["birth_angle"],
            spin_seed=row["spin_seed"],
            spin_t0=row["spin_t0"],
            spin_base=row["spin_base"],
        )

    def hatch(self, name: str, now: float | None = None) -> Ghost:
        now = now or time.time()
        ghost = Ghost(
            id=secrets.token_urlsafe(6),
            secret=secrets.token_urlsafe(24),
            name=name.strip()[:24] or "Kiro",
            created_at=now,
            last_care_at=now,
            last_look_at=now,
            care_gates=[],
            alive=True,
            departed_at=None,
            looks=0,
            bound_to=None,
            history=[{"t": now, "event": "hatched"}],
            birth_angle=HALFWAY,  # born exactly halfway: half alive, half dead (a Hadamard)
            spin_seed=secrets.randbits(32),
            spin_t0=now,
            spin_base=0.0,
        )
        self.save(ghost)
        return ghost

    def get(self, ghost_id: str) -> Ghost | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM ghosts WHERE id = ?", (ghost_id,)).fetchone()
        return self._row_to_ghost(row) if row else None

    def save(self, g: Ghost) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO ghosts (id, secret, name, created_at, last_care_at, last_look_at,
                    care_gates, alive, departed_at, looks, bound_to, history, birth_angle,
                    spin_seed, spin_t0, spin_base)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, last_care_at=excluded.last_care_at,
                    last_look_at=excluded.last_look_at, care_gates=excluded.care_gates,
                    alive=excluded.alive, departed_at=excluded.departed_at,
                    looks=excluded.looks, bound_to=excluded.bound_to,
                    history=excluded.history, birth_angle=excluded.birth_angle,
                    spin_seed=excluded.spin_seed, spin_t0=excluded.spin_t0, spin_base=excluded.spin_base
                """,
                (
                    g.id,
                    g.secret,
                    g.name,
                    g.created_at,
                    g.last_care_at,
                    g.last_look_at,
                    json.dumps(g.care_gates),
                    int(g.alive),
                    g.departed_at,
                    g.looks,
                    g.bound_to,
                    json.dumps(g.history[-50:]),
                    g.birth_angle,
                    g.spin_seed,
                    g.spin_t0,
                    g.spin_base,
                ),
            )
