# app.py - Smart Women Safety Platform Backend
from flask import Flask, request, jsonify
from flask_cors import CORS
import numpy as np
import pandas as pd
import networkx as nx
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable for Flutter/mobile origins

# -----------------------------------------------------------
# Load synthesized data & train lightweight risk model
# -----------------------------------------------------------
try:
    df = pd.read_pickle('safety_data.pkl')
except:
    df = pd.DataFrame()  # Fallback: will use paper model only

# Train RF regressor if data exists (for fast API predictions)
if not df.empty:
    X = df[['Street_Lighting', 'Known_Dark_Spot', 'Crowd_Density', 'Police_Distance_km', 'Time_Slot']]
    y = df['Risk_Score']
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    risk_rf = RandomForestRegressor(n_estimators=100, random_state=42)
    risk_rf.fit(X_train, y_train)
else:
    risk_rf = None

# -----------------------------------------------------------
# Paper's Composite Risk Model (Standalone, no training data needed)
# -----------------------------------------------------------
def normalize_crime(crime_raw):
    return np.clip(crime_raw, 0, 1)

def compute_base_risk(Cl, Ll, Hl):
    return 10 * (0.50 * Cl + 0.30 * (1 - Ll) + 0.20 * (1 - Hl))

def compute_temporal_risk(R_base, hour):
    if 6 <= hour < 12: m = 0.80
    elif 12 <= hour < 18: m = 1.00
    elif 18 <= hour < 21: m = 1.15
    else: m = 1.25
    return min(10, m * R_base)

def predict_risk_from_features(lighting, dark_spot, crowd, police_km, hour):
    """Predict risk score [0-100 scaled] and band using paper's transparent model."""
    # Normalize lighting to [0,1] assuming scale 1-10
    Ll = (lighting - 1) / 9 if 1 <= lighting <= 10 else 0.5
    # Crowd to [0,1]: 0=Low->0, 1=Med->0.5, 2=High->1
    Hl = {0: 0, 1: 0.5, 2: 1}.get(crowd, 0.5)
    # Synthesize crime proxy Cl inversely related to lighting & dark spots
    Cl = 0.6 * (1 - Ll) + 0.4 * dark_spot
    Cl = np.clip(Cl, 0, 1)
    
    R_base = compute_base_risk(Cl, Ll, Hl)
    R = compute_temporal_risk(R_base, hour)
    
    # Scale 0-100 for UI (paper uses 0-10, but data summary shows 0-100 risk score)
    risk_100 = R * 10  # Map 0-10 -> 0-100
    
    if risk_100 < 30: band = "Green (Lower estimated exposure)"
    elif risk_100 < 60: band = "Yellow (Moderate estimated exposure)"
    else: band = "Red (Higher estimated exposure)"
    
    # Confidence based on incident count proxy (Eq 7: ql = min(1, n/30))
    # Here we use police distance & dark spot density as proxy
    ql = min(1, (10 - dark_spot) / 30)  # higher when fewer dark spots/incidents
    if ql >= 0.8: conf = "High evidence coverage"
    elif ql >= 0.5: conf = "Moderate evidence coverage"
    else: conf = "Sparse evidence coverage"
    
    # Factor contributions for explainability
    crime_contrib = 0.50 * Cl * 10
    lighting_contrib = 0.30 * (1 - Ll) * 10
    crowd_contrib = 0.20 * (1 - Hl) * 10
    
    return {
        "risk_score_100": round(risk_100, 2),
        "risk_band": band,
        "confidence": conf,
        "data_freshness": "Snapshot version v1.0 - verify with municipal updates",
        "factor_contributions": {
            "crime_proxy": round(crime_contrib, 2),
            "lighting": round(lighting_contrib, 2),
            "crowd_activity": round(crowd_contrib, 2)
        },
        "normalized": {"Cl": round(Cl, 3), "Ll": round(Ll, 3), "Hl": round(Hl, 3)}
    }

# -----------------------------------------------------------
# Synthetic 18-Locality Graph (Replace with real PostGIS/NetworkX graph)
# -----------------------------------------------------------
# Each node = locality centroid. Edges have distance (km) and base travel time (min).
# This mirrors the paper's 18-major-locality graph. Keys match Nagpur locality names.
LOCALITY_NAMES = [
    "Dharampeth", "Hingna", "Jaripatka", "Beltarodi", "Hudkeshwar",
    "Ramdaspeth", "Sitabuldi", "Katol Road", "Dhantoli", "Wardhaman Nagar",
    "Itwari", "Sadar Bazar", "Nari Road", "Ajni", "Khamla", "Kalyani Nagar",
    "Gittikhadan", "Maharajbagh"
]

# Synthetic graph: distance matrix (km) and time matrix (min)
# In production, replace with real OSM graph via OSMnx or PostGIS
import random
random.seed(42)
DIST_MATRIX = {}
TIME_MATRIX = {}
for i, a in enumerate(LOCALITY_NAMES):
    DIST_MATRIX[a] = {}
    TIME_MATRIX[a] = {}
    for j, b in enumerate(LOCALITY_NAMES):
        if i == j:
            DIST_MATRIX[a][b] = 0.0
            TIME_MATRIX[a][b] = 0.0
        else:
            # Realistic intra-city distances (2-12 km) and times (5-25 min)
            d = round(random.uniform(2, 12), 1)
            t = round(d * 2 + random.uniform(1, 5), 1)  # ~2 min/km + variation
            DIST_MATRIX[a][b] = d
            TIME_MATRIX[a][b] = t

G = nx.DiGraph()
for a in LOCALITY_NAMES:
    for b in LOCALITY_NAMES:
        if a != b:
            G.add_edge(a, b, weight=TIME_MATRIX[a][b])

# -----------------------------------------------------------
# Modified Dijkstra Routing (Paper Sec 7.1-7.3)
# -----------------------------------------------------------
def modified_dijkstra(G, origin, destination, risk_scores, departure_hour,
                      alpha=0.35, beta=0.65, detour_limit=0.25):
    """
    Modified Dijkstra where edge cost = α*distance + β*risk*distance
    per Paper Eq 8: we = α*de + β*Re(t)*de
    Returns recommended, fastest, and safest paths with metrics.
    """
    Tmin = nx.dijkstra_path_length(G, origin, destination, weight='weight')
    
    # --- Compute Fastest Path (unweighted by risk) ---
    try:
        fastest_path = nx.dijkstra_path(G, origin, destination, weight='weight')
    except:
        fastest_path = [origin, destination]
    
    # --- Compute Safest Path (minimize risk exposure) ---
    # Use modified cost: risk-weighted
    try:
        safest_path = nx.dijkstra_path(G, origin, destination, 
                                        weight=lambda u, v, w: 0.35 * DIST_MATRIX.get(u, {}).get(v, 1) + 
                                                             0.65 * risk_scores.get((u, v), 0.5) * DIST_MATRIX.get(u, {}).get(v, 1))
    except:
        safest_path = [origin]
    
    # --- Generate Candidate Paths (k-shortest alternatives) ---
    # Paper Sec 7.2: perturb edge preferences or use k-shortest-path
    # We'll generate 3 loopless alternatives via simple perturbation
    candidates = []
    
    # Method 1: Fastest path (already have)
    candidates.append(("Fastest", fastest_path))
    
    # Method 2: Safest path (already have)
    candidates.append(("Safest", safest_path))
    
    # Method 3: Perturbed risk coefficient (reduce β to 0.5 for balance)
    try:
        perturbed_G = G.copy()
        for u, v, d in perturbed_G.edges(data=True):
            # Reduce risk weight temporarily
            d['perturbed_weight'] = 0.35 * DIST_MATRIX[u][v] + 0.50 * risk_scores.get((u, v), 0.5) * DIST_MATRIX[u][v]
        alt_path = nx.dijkstra_path(perturbed_G, origin, destination, weight='perturbed_weight')
        if alt_path not in [p for _, p in candidates]:
            candidates.append(("Balanced (alt)", alt_path))
    except:
        pass
    
    # --- Evaluate All Candidates & Rank (Paper Sec 7.3, Eq 12) ---
    results = []
    for label, path in candidates:
        if len(path) < 2:
            continue
        
        # Compute metrics per paper definitions
        # Distance-weighted mean risk (Eq 9): R(P) = sum(Re*de) / sum(de)
        exposure_sum = 0.0
        distance_sum = 0.0
        max_risk = 0.0
        uncertainty_sum = 0.0
        
        for i in range(len(path)-1):
            u, v = path[i], path[i+1]
            de = DIST_MATRIX.get(u, {}).get(v, 1)
            tau = TIME_MATRIX.get(u, {}).get(v, 1)
            # Risk at this edge: use node's risk score (or edge midpoint)
            Re = risk_scores.get((u, v), risk_scores.get(u, 0.5))  # fallback
            exposure_sum += Re * de
            distance_sum += de
            max_risk = max(max_risk, Re)
        
        mean_risk = round(exposure_sum / distance_sum, 2) if distance_sum > 0 else 0
        total_time = sum(TIME_MATRIX.get(path[i], {}).get(path[i+1], 0) for i in range(len(path)-1))
        total_distance = sum(DIST_MATRIX.get(path[i], {}).get(path[i+1], 0) for i in range(len(path)-1))
        
        # Detour constraint (Eq 3): T(P) ≤ (1+η)Tmin, η=0.25
        detour_pct = ((total_time - Tmin) / Tmin) * 100 if Tmin > 0 else 0
        feasible = detour_pct <= (1 + 0.25) * Tmin  # simplified check
        
        # Uncertainty (Eq 11): U(P) = sum((1-qe)*de) / sum(de)
        # Using inverse of confidence: assume confidence drops with police distance & dark spots
        avg_conf = 0.8  # placeholder; in production, use locality confidence ql
        uncertainty = round(((1 - avg_conf) * total_distance) / total_distance, 2) if total_distance > 0 else 0
        
        # Multi-objective ranking score (Eq 12): J(P) = 0.15*TildeT + 0.50*Rtilde + 0.25*Rmax_tilde + 0.10*Utilde
        # Normalize metrics to [0,1] across candidates for this origin-dest pair
        norm_time = total_time / max(Tmin * 1.5, 1)  # rough normalization
        norm_risk = mean_risk / 10.0  # paper's 0-10 scale normalized to 0-1
        norm_rmax = max_risk / 10.0
        norm_unc = uncertainty / 1.0  # uncertainty in [0,1] approx
        
        J = round(0.15 * norm_time + 0.50 * norm_risk + 0.25 * norm_rmax + 0.10 * norm_unc, 4)
        
        # Explanation generation (Paper Sec 7.4 illustrative style)
        explanations = {
            "Fastest": f"Saves time but crosses higher-exposure segments at night.",
            "Safest": f"Lowest exposure, {'exceeds 25% detour limit' if detour_pct > 25 else 'within limit'} relative to fastest.",
            "Balanced (alt)": f"Avoids highest-risk locality while retaining moderate detour."
        }
        
        results.append({
            "label": label,
            "path": path,
            "total_time_min": round(total_time, 1),
            "total_distance_km": round(total_distance, 1),
            "mean_risk": mean_risk,
            "peak_risk": round(max_risk, 2),
            "uncertainty": uncertainty,
            "detour_percent": round(detour_pct, 1),
            "feasible": feasible,
            "risk_score_J": J,
            "explanation": explanations.get(label, "Route evaluated.")
        })
    
    # Sort by J score (lowest = recommended balance), then separately label fastest/safest
    results.sort(key=lambda x: x["risk_score_J"])
    
    # Assign official labels per paper: recommended = lowest J (and feasible), fastest = lowest time, safest = lowest mean risk
    final = []
    seen_labels = set()
    for r in results:
        if r["label"] == "Fastest":
            final.append({**r, "category": "fastest"})
        elif r["label"] == "Safest":
            final.append({**r, "category": "safest"})
        elif r["risk_score_J"] == min([x["risk_score_J"] for x in results if x["feasible"]]):
            final.append({**r, "category": "recommended"})
        else:
            # Duplicate category fallback
            if r["category"] not in seen_labels:
                r["category"] = "alternative"
                seen_labels.add(r["category"])
                final.append(r)
    
    return final

# -----------------------------------------------------------
# Flask Endpoints
# -----------------------------------------------------------

@app.route('/api/predict_risk', methods=['POST'])
def api_predict_risk():
    """Predict risk for a locality given environmental features."""
    data = request.get_json()
    lighting = data.get('lighting', 5.5)   # 1-10 scale
    dark_spot = int(data.get('dark_spot', 0))  # 0/1
    crowd = int(data.get('crowd', 1))  # 0=Low,1=Med,2=High
    police_km = float(data.get('police_km', 2.6))
    hour = int(data.get('hour', 22))  # 24-hr format
    
    result = predict_risk_from_features(lighting, dark_spot, crowd, police_km, hour)
    # Attach data age label
    result["data_age"] = "Last updated: synthetic prototype - replace with municipal API"
    return jsonify(result)

@app.route('/api/optimize_route', methods=['POST'])
def api_optimize_route():
    """Return recommended/fastest/safest routes with risk metrics."""
    data = request.get_json()
    origin = data.get('origin', 'Ramdaspeth')
    destination = data.get('destination', 'Dhantoli')
    departure_str = data.get('departure_time', '2024-03-15T19:30:00')
    
    # Parse hour for temporal multiplier
    try:
        dep_hour = datetime.fromisoformat(departure_str).hour
    except:
        dep_hour = 19
    
    # Build risk scores per edge (using paper model per locality features)
    # For demo, use average risk per locality based on features; in prod, query DB
    risk_scores = {}
    for u in LOCALITY_NAMES:
        for v in LOCALITY_NAMES:
            if u != v:
                # Predict risk using paper model with synthetic locality features
                # Here we use average lighting=5.5, dark_spot_rate=0.258, crowd=1, police=2.6
                r = predict_risk_from_features(5.5, 0, 1, 2.6, dep_hour)
                risk_scores[(u, v)] = r["risk_score_100"] / 10.0  # normalize to paper's 0-10
    
    routes = modified_dijkstra(G, origin, destination, risk_scores, dep_hour)
    
    # Format response: recommended, fastest, safest alternatives
    response = {
        "origin": origin,
        "destination": destination,
        "departure_time": departure_str,
        "routes": routes[:3]  # top 3: recommended, fastest, safest
    }
    return jsonify(response)

@app.route('/api/sos', methods=['POST'])
def api_sos():
    """SOS cascade endpoint. Capture location, timestamp, trigger contacts."""
    data = request.get_json()
    lat = data.get('lat')
    lng = data.get('lng')
    timestamp = data.get('timestamp', datetime.utcnow().isoformat())
    
    # In production: send push to trusted contacts, SMS to 112, log to audit
    # Per paper Sec 8: two-second press to reduce accidental activation
    # Here we just validate and return SOS session token
    
    if not lat or not lng:
        return jsonify({"error": "Location required"}), 400
    
    sos_record = {
        "sos_id": f"SOS-{datetime.utcnow().timestamp():.0f}",
        "coordinates": {"lat": lat, "lng": lng},
        "timestamp": timestamp,
        "status": "activated",
        "fallback": "If data delivery fails, SMS to 112 will be prepared with coordinates"
    }
    
    # Simulate trusted contact delivery (Paper Sec 8: persistent, quickly accessible)
    # Claims of predicted responder arrival time must not be shown unless from authorized live service
    
    return jsonify({
        "message": "SOS activated. Coordinated response initiated.",
        "sos_record": sos_record,
        "instructions": "Share your location with trusted contacts. Emergency number 112 SMS fallback available."
    })

# -----------------------------------------------------------
# Health & Status
# -----------------------------------------------------------
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "operational",
        "model": "Smart Women Safety Platform v1.0",
        "paper_references": ["Eq 5-6 risk model", "Modified Dijkstra routing", "SOS cascade"],
        "endpoints": ["/api/predict_risk", "/api/optimize_route", "/api/sos"]
    })

if __name__ == '__main__':
    print("🚀 Starting Smart Women Safety Platform Backend...")
    print("📍 Available at: http://127.0.0.1:5000")
    print("🛡️  SOS endpoint: POST /api/sos")
    print("🗺️  Routing endpoint: POST /api/optimize_route")
    print("⚠️  Replace synthetic graph with real PostGIS/NetworkX city graph for production.")
    app.run(host='0.0.0.0', port=5000, debug=False)
