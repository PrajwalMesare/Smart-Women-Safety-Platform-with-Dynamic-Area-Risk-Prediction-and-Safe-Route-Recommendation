# Smart Women Safety Platform — Dynamic Area Risk Prediction & Safe Route Recommendation

A prototype backend implementing a transparent, explainable area-risk model and
risk-aware route recommendation, based on the paper "Development of a Smart
Women Safety Platform with Dynamic Area Risk Prediction and Safe Route
Recommendation."

## What's here

- `app.py` — Flask backend: risk prediction, route recommendation, SOS.
- `graph_builder.py` — builds the routing graph (real road network via OSMnx,
  or a sparse fallback graph if OSM isn't reachable).
- `train_model.py` — generates synthetic training data and trains/saves the
  RandomForest risk model.
- `data/localities.json` — 18 Nagpur localities with distinct coordinates and
  environmental features (lighting, dark-spot flag, crowd density, police
  proximity).
- `static/index.html` — a small Leaflet-based map demo that talks directly to
  the Flask API, so you can see routes rendered without setting up Flutter.
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
