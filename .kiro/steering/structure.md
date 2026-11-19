# Structure

```
app/
  quantum.py   circuits, Backend, closed form
  spin.py      the ghost's constant turning (same as static/app.js)
  store.py     SQLite Ghost store
  main.py      FastAPI routes, serves static/
static/
  index.html style.css app.js kiro-ghost.svg kiro-wordmark.png
tests/
  test_quantum.py test_api.py test_spin.py
.kiro/
  specs/kirogotchi/{requirements,design,tasks}.md
  steering/{product,tech,structure}.md
  hooks/*.kiro.hook
```

Run: `uvicorn app.main:app --reload`
