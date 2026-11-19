import math
import shutil
import subprocess
from pathlib import Path

import pytest

from app import spin


def test_speed_is_one_lap_every_10_to_20_seconds():
    for k in range(200):
        v = abs(spin.velocity(12345, k))
        assert 2 * math.pi / 20 <= v <= 2 * math.pi / 10


def test_direction_and_speed_change_between_segments():
    vs = [spin.velocity(777, k) for k in range(40)]
    assert any(v > 0 for v in vs) and any(v < 0 for v in vs)
    assert len({round(v, 6) for v in vs}) > 30


def test_motion_is_continuous_across_a_change():
    seed, t0 = 99, 1000.0
    edge = t0 + spin.SEGMENT
    a = spin.angle(seed, t0, 0.0, edge - 1e-6)
    b = spin.angle(seed, t0, 0.0, edge + 1e-6)
    assert a == pytest.approx(b, abs=1e-4)


def test_never_stops():
    seed, t0 = 5, 0.0
    samples = [spin.angle(seed, t0, 0.0, t0 + 0.5 * i) for i in range(60)]
    assert all(abs(samples[i + 1] - samples[i]) > 0.1 for i in range(59))


def test_same_angle_as_the_page():
    """app.js and app/spin.py must give the same angle, or the hint and the Look disagree."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    src = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text()
    start = src.index("const SEGMENT = 3;")
    end = src.index("function serverNow()")
    script = src[start:end] + (
        "const g = {spin_seed: 3141592653, spin_t0: 100, spin_base: 0.4};"
        "console.log(JSON.stringify([101.3, 107.9, 160.2, 1000.5].map((t) => spinAt(g, t))));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    js = [float(x) for x in out.strip()[1:-1].split(",")]
    py = [spin.angle(3141592653, 100, 0.4, t) for t in (101.3, 107.9, 160.2, 1000.5)]
    assert js == pytest.approx(py, abs=1e-9)
