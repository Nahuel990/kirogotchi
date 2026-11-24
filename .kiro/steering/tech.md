# Tech steering

- Python 3.12, FastAPI, amazon-braket-sdk. Default device is
  `LocalSimulator("braket_dm")` because it gives the exact probability with
  `shots=0` and a single shot for the Look.
- `BRAKET_DEVICE_ARN` switches to a real device; never ship a default ARN
  (it costs money).
- Front end is plain HTML/CSS/JS in `static/`. No bundler, no framework.
- Tests: `pytest -q -W ignore`. Keep the closed-form cross-check
  (`probability_alive_closed_form`) in sync with any circuit change.
- Angles are radians everywhere in code. The UI shows no angles except inside
  the real circuit in "Show me what happened", where the key explains them.
- app/spin.py and the matching functions in static/app.js must stay identical.
- Secrets: owner secret only in the `X-Ghost-Secret` header and
  `localStorage`. Never log it.
