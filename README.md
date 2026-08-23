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
- **A verified direct-dial number is shown when available; otherwise the
  verified Nagpur Police HQ number is used as a fallback, never a
  fabricated one.** `data/nagpur_police_contacts.csv` provides real
  station-specific numbers for some areas; entries marked `"Available"`
  in that file are placeholders, not verified numbers, and are
  deliberately excluded. As of this writing, 13 of the 30 areas have a
  matched, station-specific verified number; the remaining 17 fall back to
  the Nagpur City Police headquarters line (0712-2560601, verified against
  the official listing at nagpur.gov.in/police/) rather than showing no
  number or a guessed one. The SOS response and UI clearly label which
  case applies. If you have verified numbers for more specific stations,
  add them to that CSV (`Type` must be `Police Station`, `Contact Number`
  a real number) and they'll be picked up automatically on the next
  server start.
- **No website can silently auto-dial a phone.** Browsers block that on
  purpose (it's exactly how a malicious site would auto-dial a premium
  number). The closest honest equivalent — and what's implemented here —
  is: everything else happens automatically on hold, then a pre-filled
  call button needs one tap to actually place the call.

### Trip check-in and live tracking

After finding a route, a **Trip Safety Check-In** card lets you set how
many minutes until you expect to arrive. Starting it:
1. Starts a countdown you can see in the app.
2. Generates a shareable tracking link (`/track/<share_id>`) — open it in
   any browser, no login needed, and it shows the trip's live location on
   a map, updating every 5 seconds. Send this to a trusted contact so they
   can watch you get there.
3. If you tap **"I'm Safe — Arrived"** before time runs out, the trip ends
   normally.
4. If you *don't* check in before the deadline, an alert fires
   automatically — same nearest-jurisdiction lookup and SMS pipeline as
   the SOS button, using your last known location.

Two things worth knowing about the current implementation:
- **Trips are stored in memory, not a database.** This is fine for a demo
  running as a single process (the Procfile already uses `--workers 1`
  for this reason), but a trip is lost if the server restarts, and this
  wouldn't scale to multiple worker processes without moving to a real
  datastore (Redis, a database).
- **The share link's `share_id` acts as the only access control** — it's
  an unguessable random token, not a login. Anyone who has the exact link
  can view that trip's live location. This is the same tradeoff most
  consumer trip-sharing features make, but worth knowing before treating
  the link as something to post publicly.

### Emergency contact

The shield icon in the top-right header opens a small form for a name and
phone number, stored **only in that browser's localStorage** — never sent
to the server unless you actually trigger SOS or a trip's auto-alert. When
one is set, both SOS and the trip check-in timeout send the SMS (and, on
SOS, provide a tap-to-call link) to this specific person instead of only
the server's globally-configured `EMERGENCY_CONTACT_NUMBER`. Both SOS and
trip auto-alerts also now include a live-tracking link in the message, not
just a one-time map pin — this reuses the same trip-tracking mechanism
described above.

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
- **Real per-street road classification as a risk signal**, when using the
  real road network. The crime dataset only has resolution at the level of
  30 broad areas, so it can't tell a dark side street apart from a
  well-lit main road in the same neighborhood — both would get the exact
  same risk score. OSM road classification (primary/secondary/residential/
  footway/etc.) is a genuine per-street signal that doesn't have this
  limitation, and is now blended in as a bonus/penalty on top of the
  area-based risk: major, well-traveled roads get safer scores, small or
  isolated ways (footpaths, service roads, tracks) get a penalty,
  independent of which area they're geographically nearest to.

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

- `data/localities.json` is generated from the real crime dataset
  (`nagpur_women_safety_2025_RECREATED_1446.csv`), but that dataset itself
  is only 1,446 records across 30 areas — a modest sample, not an
  official, continuously-updated crime feed. Treat scores as illustrative
  of relative risk, not as precise real-world figures.
- Road classification is used as a *proxy* for lighting/visibility (major
  roads assumed better-lit and more overlooked than small ones) — it's
  not directly measured streetlight data, which doesn't exist in any
  dataset used here. It's a reasonable approximation, not ground truth.
- The sparse fallback graph is a reasonable approximation, not real street
  geometry; run `graph_builder.py` somewhere with unrestricted internet
  access to get the actual OSM road network. Road classification (and its
  risk-modifier benefit) is only available in that mode, not the sparse
  fallback.
- Twilio's free trial tier can only send SMS to verified numbers — fine for
  a demo, not for production use.
- There's no persistence layer (database) — SOS records and routes aren't
  stored anywhere beyond the response.
