# SafeRoute Nagpur

**Smart Women Safety Platform — Dynamic Area Risk Prediction & Safe Route Recommendation**

A full-stack safety platform that predicts area-level risk from real crime data and recommends routes that balance travel time against safety exposure — not just the shortest path. Built around a transparent, explainable risk model and backed by real Nagpur crime and police-contact data.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <img alt="Flask" src="https://img.shields.io/badge/backend-flask-black.svg">
  <img alt="scikit-learn" src="https://img.shields.io/badge/model-random%20forest-orange.svg">
  <img alt="Leaflet" src="https://img.shields.io/badge/maps-leaflet-green.svg">
</p>

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [How the Risk Model Works](#how-the-risk-model-works)
- [Safety Features in Detail](#safety-features-in-detail)
- [Deployment](#deployment)
- [Known Limitations](#known-limitations)
- [References](#references)

---

## Overview

Standard navigation apps optimize for one thing: getting there fastest. **SafeRoute Nagpur** optimizes for a second, equally important variable — how safe the journey actually is — using real environmental and historical crime data specific to Nagpur, India.

The platform:
- Scores 30 real Nagpur areas for risk using street lighting, crowd density, time-of-day, and proximity to police, trained on a real 1,446-record crime dataset
- Computes genuinely different fastest / safest / recommended routes across the real Nagpur road network, not just relabeled copies of the same path
- Provides emergency response tools — one-tap SOS with verified police contacts, a trip check-in timer with automatic alerting, and live location sharing — designed with realistic safety tradeoffs in mind rather than overpromising

## Features

**🗺️ Risk-Aware Map**
All 30 Nagpur areas rendered as color-coded markers (green/yellow/red) reflecting real-time computed risk, with a live/dark map style toggle.

**🧭 Safe Route Recommendation**
Computes real k-shortest-paths (Yen's algorithm) across the actual Nagpur road network, scored by a blend of travel time and area/street-level risk exposure — producing genuinely distinct fastest, safest, and recommended routes rather than one path with three labels.

**📊 Crime Analytics Dashboard**
Live charts and tables built directly from the real crime dataset — risk by area, crime type distribution, time-of-day breakdown, and a sortable area risk table.

**🆘 One-Tap SOS**
A 3-second press-and-hold triggers an alert with your live location, the nearest police jurisdiction (looked up from real per-area data), and a verified direct-dial number where one exists — falling back to the Nagpur Police HQ line rather than a guessed number.

**⏱️ Trip Check-In Timer**
Set an expected arrival time before a trip. If you don't confirm arrival, an alert fires automatically with your last known location — no manual intervention needed.

**📍 Live Trip Sharing**
Every trip generates a shareable, no-login-required tracking link a trusted contact can open to watch your location update in real time.

**👤 Emergency Contact**
Configure a specific person's name and number (stored locally in your browser) to be notified directly — with a live tracking link — if SOS or a trip alert ever triggers.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask, Gunicorn |
| ML Model | scikit-learn (RandomForestRegressor) |
| Routing | NetworkX (k-shortest-paths), OSMnx (real road network) |
| Data | pandas, real Nagpur crime & police-contact CSVs |
| Frontend | Vanilla JS, Leaflet.js, Chart.js |
| Messaging | Twilio (optional, for real SOS SMS) |

## Getting Started

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
git clone https://github.com/PrajwalMesare/Smart-Women-Safety-Platform-with-Dynamic-Area-Risk-Prediction-and-Safe-Route-Recommendation.git
cd Smart-Women-Safety-Platform-with-Dynamic-Area-Risk-Prediction-and-Safe-Route-Recommendation

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Build the routing graph

```bash
python graph_builder.py
```

With normal internet access, this downloads the real Nagpur drivable road network via OSMnx and caches it locally. In network-restricted environments, it automatically falls back to a sparse, strongly-connected k-nearest-neighbor graph over the 30 areas — routes still genuinely diverge, just without full street-level geometry.

### Train the risk model

```bash
python train_model.py
```

Trains on the real crime dataset (falls back to a synthetic generator only if that CSV is missing) and saves the model so the server doesn't retrain on every restart.

### Run it

```bash
python app.py
```

Open **http://127.0.0.1:5000** for the full app, or hit the API directly:

```bash
curl http://127.0.0.1:5000/api/health
```

> **macOS note:** if port 5000 is already in use (AirPlay Receiver commonly claims it), either disable AirPlay Receiver in System Settings, or run on a different port:
> ```bash
> python3 -c "import app; app.app.run(host='0.0.0.0', port=5051, debug=False)"
> ```

## Configuration

All configuration is optional — the app runs fully functional without any of it, with graceful fallbacks. Copy `.env.example` to `.env` to enable:

| Variable | Purpose |
|---|---|
| `TWILIO_ACCOUNT_SID` | Enables real SOS/trip-alert SMS via Twilio |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | Your Twilio sending number |
| `EMERGENCY_CONTACT_NUMBER` | Default SMS recipient if no per-browser Emergency Contact is set |

Without these, SOS and trip alerts still work — they simply skip the real SMS send and say so in the response.

## API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Server status, active routing graph mode, model load state |
| `/api/localities` | GET | All 30 areas with coordinates and current risk score/band |
| `/api/predict_risk` | POST | Risk score/band from `lighting`, `dark_spot`, `crowd`, `police_km`, `hour` |
| `/api/optimize_route` | POST | Fastest / safest / recommended routes between `origin` and `destination` |
| `/api/analytics` | GET | Aggregated real crime-dataset statistics powering the Analytics dashboard |
| `/api/sos` | POST | Trigger an SOS: nearest station lookup, optional SMS, live tracking link |
| `/api/trip/start` | POST | Start a trip check-in timer with an expected-arrival deadline |
| `/api/trip/<id>/checkin` | POST | Confirm safe arrival, canceling the auto-alert |
| `/api/trip/<id>/location` | POST | Push a live location update for an active trip |
| `/api/trip/share/<share_id>` | GET | Public, read-only trip status for the live-tracking page |
| `/track/<share_id>` | GET | Standalone live-tracking page (no login required) |

## Project Structure

```
├── app.py                          # Flask backend — all API endpoints
├── graph_builder.py                 # Builds the routing graph (real OSM or sparse fallback)
├── train_model.py                   # Trains and saves the risk model from real data
├── model_notebook.py                # Generates the walkthrough notebook
├── data/
│   ├── localities.json              # Per-area features (regenerated from the CSV)
│   └── nagpur_police_contacts.csv   # Verified real police station numbers
├── nagpur_women_safety_2025_RECREATED_1446.csv   # Real crime dataset
├── static/
│   ├── index.html / app.js / style.css   # Main app: map, analytics, about, SOS
│   └── track.html                   # Standalone live trip-tracking page
├── Smart_Women_Safety_Model.ipynb   # Executed model/training notebook
├── requirements.txt
├── Procfile / build.sh              # Deployment config (Render/Railway-style platforms)
└── .env.example                     # Optional Twilio configuration template
```

## How the Risk Model Works

Each area's risk score blends:
- **50%** crime proxy (derived from historical incident data)
- **30%** street lighting
- **20%** crowd density

adjusted by a time-of-day multiplier (risk rises in the evening and at night), then classified into **Green / Yellow / Red** bands. A RandomForestRegressor trained on the real dataset achieves **R² = 0.886**, with street lighting as the strongest predictor.

For route scoring, when the real road network is available, per-street risk is refined further using two signals the area-level dataset alone can't provide:
- **Distance-weighted blending** across nearby areas, so risk changes smoothly moving away from a hotspot instead of jumping abruptly at an area boundary
- **Real OSM road classification** (primary/residential/footway/etc.) as a proxy for lighting and visibility, since a dark side street and a well-lit main road in the same neighborhood would otherwise score identically

## Safety Features in Detail

### SOS
Holding the SOS button for 3 seconds captures your location, looks up the nearest real police jurisdiction, and shows a verified direct-dial number where one exists (13 of 30 areas currently), falling back to the verified Nagpur Police HQ line otherwise — never a fabricated number. True silent auto-dialing isn't possible from any website (a deliberate browser security restriction), so the flow automates everything except the final tap to place the call.

### Trip Check-In
Set an expected arrival time before a trip; if you don't confirm arrival, an automatic alert fires using the same verified-contact pipeline as SOS. Trip state is stored in-memory (not a database) — appropriate for a single-process demo deployment, but not yet built for horizontal scaling or restart persistence.

### Live Trip Sharing
Every trip generates a shareable link anyone can open to watch it live, no login required. The link's random token is the only access control — the same tradeoff most consumer trip-sharing tools make.

### Emergency Contact
A name and number entered via the header's shield icon, stored only in your browser's local storage, used to override the default SMS recipient for that browser's SOS/trip alerts.

## Deployment

The Flask dev server is for local use only. For production:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

`Procfile` and `build.sh` are ready for Render, Railway, and similar platforms.

**Render.com (free tier):**
1. New Web Service → connect this repo
2. Build command: `bash build.sh`
3. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add Twilio env vars if real SMS is wanted (optional)

> **Memory note:** the real road network (~110,000 edges) can exceed the
> free tier's 512MB limit and crash on startup. `graph_builder.py` only
> downloads the real network when it can reach OpenStreetMap — if your
> host's network can't reach it, it automatically falls back to the
> lighter sparse graph instead, which fits comfortably. If your host *can*
> reach OSM but doesn't have enough RAM, the practical fix is a paid tier
> with more memory, or removing `data/nagpur_graph.graphml` before deploy
> so the sparse fallback is used deliberately.

Free-tier instances sleep after inactivity — the first request afterward can take ~30 seconds.

## Known Limitations

- The crime dataset (1,446 records / 30 areas) is a modest sample, not a live official feed — treat risk scores as illustrative, not precise.
- Road-classification risk weighting is a proxy for lighting/visibility, not directly measured streetlight data (which doesn't exist in any available dataset).
- Only available in real-road-network mode; the sparse fallback graph doesn't have individual street geometry to draw from.
- 17 of 30 areas don't yet have an independently verified police contact number and use the HQ fallback.
- No persistence layer — trips and SOS events live in server memory only.
- Twilio's free trial tier can only send SMS to pre-verified numbers.

## References

This project is inspired by and references research including:
- Sohrabi et al., *"Safe Route-Finding: A Review of Literature and Future Directions,"* Accident Analysis & Prevention, 2022
- Levy et al., *"SafeRoute: Learning to Navigate Streets Safely in an Urban Environment,"* ACM TIST, 2020
- Agrawal et al., *"SafeRoutes: A Holistic Approach to Women's Safety through Advanced Clustering and GPS Integration,"* IEEE Access, 2024
- *"Women Safety Platform with Safe Route Prediction Using Crime Data,"* IEEE IDCIoT, 2025
- Sohrabi et al., *"Navigating to Safety: Necessity, Requirements and Barriers,"* Transportation Research Part C, 2022

---

*Built as a prototype demonstrating risk-aware navigation with real data. Not a substitute for official emergency services — always call 100 / 112 / 1091 directly in a genuine emergency.*
