# Smart Women Safety Platform — Dynamic Area Risk Prediction & Safe Route Recommendation

A prototype backend implementing a transparent, explainable area-risk model and
risk-aware route recommendation, based on the paper "Development of a Smart
Women Safety Platform with Dynamic Area Risk Prediction and Safe Route
Recommendation."

## What's here

- `app.py` — Flask backend: risk prediction, route recommendation, SOS, analytics.
- `graph_builder.py` — builds the routing graph (real road network via OSMnx,
  or a sparse fallback graph if OSM isn't reachable).
- `train_model.py` — trains/saves the RandomForest risk model. If
  `nagpur_women_safety_2025_RECREATED_1446.csv` (the real crime dataset) is
  present, trains on real data and regenerates `data/localities.json` from
  real per-area averages (30 actual Nagpur areas); otherwise falls back to
  a synthetic generator.
- `nagpur_women_safety_2025_RECREATED_1446.csv` — the real dataset: 1,446
  crime records across 30 Nagpur areas with coordinates, crime type, time
  slot, lighting, crowd density, and police/hospital proximity.
- `data/nagpur_police_contacts.csv` — real Nagpur police station contact
  numbers, used by the SOS feature to show a verified direct-dial number
  for the nearest jurisdiction when one is available (see the SOS section
  below for how partial/unverified entries are handled).
- `data/localities.json` — per-area features, regenerated from the real CSV.
- `static/` — full frontend: risk-colored map (Map tab), a crime analytics
  dashboard with charts (Analytics tab) built from the real CSV, and an
  About tab. Live location tracking, an SOS bar with quick-dial numbers,
  and dark/light theme are all wired to the real API — no Flutter needed.
- `Smart_Women_Safety_Model.ipynb` — notebook version of the model/training
  walkthrough, already executed with outputs, for browsing on GitHub.

## Setup

```bash
pip install -r requirements.txt

# 1. Build the routing graph (run once)
python graph_builder.py
# With normal internet access this downloads the real Nagpur road network
# via OSMnx and caches it to data/nagpur_graph.graphml.
# In network-restricted environments (CI, sandboxes) it automatically falls
# back to a sparse k-nearest-neighbor graph over the 18 localities
# (data/locality_graph.json) instead of a naive complete graph — this still
# lets fastest/safest/recommended routes genuinely differ, unlike a complete
# graph where every pair of points is one direct hop apart.

# 2. Train and save the risk model (run once)
python train_model.py
# Produces data/safety_data.pkl and models/risk_model.joblib.
# app.py loads the saved model on startup instead of retraining scikit-learn
# every time the server restarts.

# 3. Start the backend
python app.py
```

Open **http://127.0.0.1:5000** in a browser for the built-in map demo, or hit
the API directly (see below). Health check:

```bash
curl http://127.0.0.1:5000/api/health
```

### SOS: 3-second hold, nearest station, and why calling uses national numbers

Pressing and holding the SOS button for 3 seconds:
1. Captures your current GPS location (one-shot, doesn't require "Use My
   Live Location" to already be active).
2. Identifies the nearest police jurisdiction by name, using real per-area
   data from `nagpur_women_safety_2025_RECREATED_1446.csv` (each area's
   `Police_Station` value matches its own `Area` name in the real dataset).
3. Sends an SMS with your location to your configured emergency contact,
   if Twilio is set up (see below).
4. Shows one-tap **Call Police (100)** / **Call Emergency (112)** buttons.

Two deliberate choices worth knowing about:
- **A verified direct-dial number is shown only for areas with one.**
  `data/nagpur_police_contacts.csv` provides real station phone numbers for
  some areas; entries marked `"Available"` in that file are placeholders,
  not verified numbers, and are deliberately excluded. As of this writing,
  11 of the 30 areas have a matched, verified number; the rest show no
  station-specific number and fall back to the national lines below. If
  you have verified numbers for more stations, add them to that CSV
  (`Type` must be `Police Station`, `Contact Number` a real number) and
  they'll be picked up automatically on the next server start.
- **No website can silently auto-dial a phone.** Browsers block that on
  purpose (it's exactly how a malicious site would auto-dial a premium
  number). The closest honest equivalent — and what's implemented here —
  is: everything else happens automatically on hold, then a pre-filled
  call button needs one tap to actually place the call.

### Optional: real SOS SMS via Twilio

By default, `/api/sos` returns an acknowledgment JSON only. To actually send
an SMS, copy `.env.example` to `.env` and fill in Twilio credentials (a free
trial account works for testing), then load it before starting the server
(e.g. `export $(cat .env | xargs)` or use `python-dotenv` in your own entry
point). Without credentials configured, the endpoint still works exactly as
before — it just skips the real SMS send and says so in the response.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Status, which routing graph mode is active, whether the ML model loaded |
| `/api/localities` | GET | List of localities with coordinates (for maps/dropdowns) |
| `/api/predict_risk` | POST | Predict a risk score/band from `lighting`, `dark_spot`, `crowd`, `police_km`, `hour` |
| `/api/optimize_route` | POST | Recommended/fastest/safest routes between `origin` and `destination` localities at a given `departure_time` |
| `/api/analytics` | GET | Aggregated stats from the real crime dataset (totals, per-area breakdown, chart data) — powers the Analytics tab |
| `/api/sos` | POST | Activate an SOS with `lat`/`lng`; sends a real SMS if Twilio is configured |

## What changed from the original prototype

The first version of this backend had a routing graph where every locality
connected directly to every other locality (a complete graph), and every
edge in the city was assigned the exact same hardcoded risk value. Together
those meant the "3 alternative routes" feature could never actually produce
different routes — the shortest path between any two points was always the
single direct edge, at the same computed risk.

This version fixes that at the root:

- **Real (or realistically sparse) road graph** instead of a complete graph,
  so routes must pass through intermediate localities and can genuinely
  diverge.
- **Distinct per-locality risk features** instead of one feature set copied
  onto every edge, so risk actually varies by location.
- **Real k-shortest-paths** (`networkx.shortest_simple_paths`, Yen's
  algorithm) for both time and risk weighting, instead of a single
  perturbed-weight hack that usually just reproduced the same path.
- **Pretrained, saved model** (`models/risk_model.joblib`) instead of
  refitting scikit-learn on every server restart.
- **`police_km` now actually affects the response** (evidence-coverage
  confidence) — previously accepted by the API but silently unused.
- **Specific exception handling + logging** instead of bare `except:`
  clauses that silently swallowed all errors.
- **A demoable frontend** (`static/index.html`) so the project can be shown
  working in a browser without a Flutter environment.

## Deployment

The Flask dev server (`python app.py`) is fine for local testing but isn't
meant for production. For an actual deploy:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

`Procfile` and `build.sh` are included for platforms that use them
(Render, Railway, and similar). `build.sh` runs `pip install`,
`graph_builder.py`, and `train_model.py` as one build step — if the
platform's network can't reach OpenStreetMap, `graph_builder.py` still
succeeds by falling back to the sparse locality graph automatically, so the
build won't fail either way.

### Render.com (free tier, simplest option)

1. Push this repo to GitHub (already done).
2. On [render.com](https://render.com) → **New** → **Web Service** → connect
   this repo.
3. Settings:
   - **Build Command**: `bash build.sh`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Instance type**: Free is fine for a demo.
4. If you want real SOS SMS, add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_FROM_NUMBER`, `EMERGENCY_CONTACT_NUMBER` under **Environment**
   (never commit these to the repo — see `.env.example`).
5. Deploy. Render gives you a public URL like
   `https://your-app.onrender.com` — open it directly for the map demo, or
   point a Flutter/other frontend at it instead of `10.0.2.2:5000`.

Free-tier services on Render sleep after inactivity, so the first request
after idling can take ~30s to wake up — expected, not a bug.

### Alternatives

- **Railway** — same `build.sh` / gunicorn start command pattern, usually
  detects Python automatically.
- **Fly.io** — needs a `Dockerfile` instead of `Procfile`/`build.sh` if you
  go this route.
- **PythonAnywhere** — good free option for Flask specifically, but it
  proxies WSGI directly rather than using gunicorn/Procfile; follow their
  "Manual configuration" Flask guide and point it at `app.py`'s `app` object.

## Known limitations / next steps

- The per-locality environmental features in `data/localities.json` are
  illustrative, not sourced from an official crime dataset — replace with
  real municipal/police data for anything beyond a prototype.
- The sparse fallback graph is a reasonable approximation, not real street
  geometry; run `graph_builder.py` somewhere with unrestricted internet
  access to get the actual OSM road network.
- Twilio's free trial tier can only send SMS to verified numbers — fine for
  a demo, not for production use.
- There's no persistence layer (database) — SOS records and routes aren't
  stored anywhere beyond the response.
