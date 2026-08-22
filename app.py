# app.py - Smart Women Safety Platform Backend
#
# Changes from the original prototype:
#   - Routing graph: uses the real Nagpur road network (via OSMnx, cached in
#     data/nagpur_graph.graphml) when available; otherwise falls back to a
#     sparse k-nearest-neighbor locality graph (data/locality_graph.json,
#     built by graph_builder.py) instead of the old COMPLETE graph. A
#     complete graph meant every "shortest path" was always the single
#     direct edge, so fastest/safest/recommended routes could never
#     actually differ. Run `python graph_builder.py` before starting this
#     server.
#   - Risk: each locality now has distinct environmental features
#     (data/localities.json) instead of one hardcoded feature set being
#     applied to every edge in the city.
#   - Model: loads a pretrained model from models/risk_model.joblib
#     (built by train_model.py) instead of refitting scikit-learn on
#     every server startup.
#   - Routing: uses real k-shortest-paths (nx.shortest_simple_paths) for
#     genuinely different candidate routes, instead of a single
#     perturbed-weight hack.
#   - SOS: attempts a real Twilio SMS send if TWILIO_* env vars are
#     configured; otherwise falls back to the original "instructions"
#     style response.
#   - Error handling: replaced bare `except:` clauses with specific
#     exceptions and logging.
import json
import logging
import math
import os
import threading
import uuid
from datetime import datetime
from itertools import islice

import joblib
import networkx as nx
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("safety_platform")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
STATIC_DIR = os.path.join(BASE_DIR, "static")

LOCALITIES_PATH = os.path.join(DATA_DIR, "localities.json")
GRAPHML_PATH = os.path.join(DATA_DIR, "nagpur_graph.graphml")
FALLBACK_GRAPH_PATH = os.path.join(DATA_DIR, "locality_graph.json")
MODEL_PATH = os.path.join(MODELS_DIR, "risk_model.joblib")
REAL_CSV_PATH = os.path.join(BASE_DIR, "nagpur_women_safety_2025_RECREATED_1446.csv")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
CORS(app)

# -----------------------------------------------------------
# Load pretrained ML model (falls back to training in-process if the
# pretrained artifact is missing, so the app still runs after a fresh
# clone even if train_model.py hasn't been run yet)
# -----------------------------------------------------------
risk_rf = None
if os.path.exists(MODEL_PATH):
    try:
        risk_rf = joblib.load(MODEL_PATH)
        logger.info("Loaded pretrained risk model from %s", MODEL_PATH)
    except (OSError, EOFError, ValueError) as e:
        logger.warning("Failed to load pretrained model (%s): %s. Will train in-process.", type(e).__name__, e)

if risk_rf is None:
    try:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split

        safety_data_path = os.path.join(DATA_DIR, "safety_data.pkl")
        if os.path.exists(safety_data_path):
            df = pd.read_pickle(safety_data_path)
            X = df[["Street_Lighting", "Known_Dark_Spot", "Crowd_Density", "Police_Distance_km", "Time_Slot"]]
            y = df["Risk_Score"]
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            risk_rf = RandomForestRegressor(n_estimators=100, random_state=42)
            risk_rf.fit(X_train, y_train)
            logger.warning("No pretrained model found at %s; trained a fallback model in-process. "
                            "Run `python train_model.py` to avoid this on every restart.", MODEL_PATH)
        else:
            logger.warning("No pretrained model and no safety_data.pkl found. "
                            "Run `python train_model.py` first. Falling back to the transparent paper model only.")
    except ImportError:
        logger.warning("scikit-learn not available; falling back to the transparent paper model only.")

# -----------------------------------------------------------
# Paper's Transparent Composite Risk Model (Eq 5 & 6)
# -----------------------------------------------------------
def compute_base_risk(Cl, Ll, Hl):
    return 10 * (0.50 * Cl + 0.30 * (1 - Ll) + 0.20 * (1 - Hl))


def compute_temporal_risk(R_base, hour):
    if 6 <= hour < 12:
        m = 0.80
    elif 12 <= hour < 18:
        m = 1.00
    elif 18 <= hour < 21:
        m = 1.15
    else:
        m = 1.25
    return min(10, m * R_base)


def predict_risk_from_features(lighting, dark_spot, crowd, police_km, hour):
    """Predict risk score [0-100 scaled] and band using the paper's transparent model.

    Note: per the paper (Eq 5), the base risk formula intentionally uses only
    crime proxy / lighting / crowd — police_km is NOT part of the base risk
    score. It IS used below to derive the confidence/evidence-coverage label
    (closer police presence is treated as a proxy for better incident-data
    coverage in that area), so the parameter is no longer silently ignored
    as it was in the original prototype.
    """
    Ll = (lighting - 1) / 9 if 1 <= lighting <= 10 else 0.5
    Hl = {0: 0, 1: 0.5, 2: 1}.get(crowd, 0.5)
    Cl = np.clip(0.6 * (1 - Ll) + 0.4 * dark_spot, 0, 1)

    R_base = compute_base_risk(Cl, Ll, Hl)
    R = compute_temporal_risk(R_base, hour)
    risk_100 = R * 10

    if risk_100 < 30:
        band = "Green (Lower estimated exposure)"
    elif risk_100 < 60:
        band = "Yellow (Moderate estimated exposure)"
    else:
        band = "Red (Higher estimated exposure)"

    # Evidence coverage proxy: closer police presence -> assumed better data coverage.
    ql = min(1.0, max(0.0, 1 - (police_km / 6.0)))
    if ql >= 0.8:
        conf = "High evidence coverage"
    elif ql >= 0.5:
        conf = "Moderate evidence coverage"
    else:
        conf = "Sparse evidence coverage"

    crime_contrib = 0.50 * Cl * 10
    lighting_contrib = 0.30 * (1 - Ll) * 10
    crowd_contrib = 0.20 * (1 - Hl) * 10

    return {
        "risk_score_100": round(risk_100, 2),
        "risk_band": band,
        "confidence": conf,
        "confidence_score": round(ql, 3),
        "data_freshness": "Snapshot version v1.0 - verify with municipal updates",
        "factor_contributions": {
            "crime_proxy": round(crime_contrib, 2),
            "lighting": round(lighting_contrib, 2),
            "crowd_activity": round(crowd_contrib, 2),
        },
        "normalized": {"Cl": round(Cl, 3), "Ll": round(Ll, 3), "Hl": round(Hl, 3)},
    }


# -----------------------------------------------------------
# Locality data (distinct per-locality features, replacing the old
# single hardcoded feature set applied to every edge in the city)
# -----------------------------------------------------------
with open(LOCALITIES_PATH, "r", encoding="utf-8") as f:
    _localities_raw = json.load(f)["localities"]

LOCALITIES = {loc["name"]: loc for loc in _localities_raw}
LOCALITY_NAMES = list(LOCALITIES.keys())


def locality_risk(name, hour):
    loc = LOCALITIES.get(name)
    if loc is None:
        # Unknown locality: fall back to a citywide-average profile rather than crashing.
        return predict_risk_from_features(5.5, 0, 1, 2.6, hour)
    return predict_risk_from_features(loc["lighting"], loc["dark_spot"], loc["crowd"], loc["police_km"], hour)


# -----------------------------------------------------------
# Routing graph: real road network if cached, else sparse k-NN fallback,
# else the legacy complete graph (last resort, kept for backward
# compatibility if neither data file is present).
# -----------------------------------------------------------
GRAPH_MODE = None
G = nx.DiGraph()
DIST_MATRIX = {}
TIME_MATRIX = {}
NODE_TO_LOCALITY = {}  # maps a raw graph node id -> nearest locality name (used for risk lookup)
NODE_COORDS = {}  # maps a raw graph node id -> (lat, lon); only populated in real_road_network mode


def _load_real_road_graph():
    import osmnx as ox

    graph = ox.load_graphml(GRAPHML_PATH)
    # OSMnx graphs are MultiDiGraph with 'length' (meters) and travel time attrs.
    # Convert to a plain DiGraph keyed by osmid with distance_km / time_min weights.
    simple = nx.DiGraph()
    for u, v, data in graph.edges(data=True):
        dist_km = data.get("length", 100) / 1000.0
        speed_kph = data.get("speed_kph", 25)  # urban default
        time_min = (dist_km / max(speed_kph, 5)) * 60
        if simple.has_edge(u, v):
            if simple[u][v]["weight"] <= time_min:
                continue
        simple.add_edge(u, v, weight=time_min, distance_km=dist_km, time_min=time_min)

    # Map each locality centroid to its nearest OSM node, and record every
    # node's real coordinates so routes can be drawn following actual
    # streets instead of straight lines between area centroids.
    node_points = {n: (d["y"], d["x"]) for n, d in graph.nodes(data=True)}
    NODE_COORDS.update(node_points)
    for name, loc in LOCALITIES.items():
        nearest = ox.distance.nearest_nodes(graph, loc["lon"], loc["lat"])
        NODE_TO_LOCALITY[nearest] = name

    # Fill NODE_TO_LOCALITY for every node via nearest-centroid assignment so
    # every edge can be attributed a risk value.
    loc_items = list(LOCALITIES.items())
    for n, (lat, lon) in node_points.items():
        if n in NODE_TO_LOCALITY:
            continue
        best_name, best_d = None, float("inf")
        for name, loc in loc_items:
            d = (lat - loc["lat"]) ** 2 + (lon - loc["lon"]) ** 2
            if d < best_d:
                best_d, best_name = d, name
        NODE_TO_LOCALITY[n] = best_name

    return simple, node_points


def _load_fallback_locality_graph():
    with open(FALLBACK_GRAPH_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    simple = nx.DiGraph()
    dist_m, time_m = {}, {}
    for name in data["nodes"]:
        dist_m[name] = {}
        time_m[name] = {}
    for e in data["edges"]:
        u, v = e["from"], e["to"]
        simple.add_edge(u, v, weight=e["time_min"], distance_km=e["distance_km"], time_min=e["time_min"])
        dist_m[u][v] = e["distance_km"]
        time_m[u][v] = e["time_min"]
        NODE_TO_LOCALITY[u] = u
        NODE_TO_LOCALITY[v] = v
    return simple, dist_m, time_m


def _load_legacy_complete_graph():
    """Last-resort fallback: kept only for backward compatibility if neither
    graph_builder.py output is present. Prints a loud warning because this
    reproduces the original prototype's main limitation (every locality
    directly connects to every other, so routes can't diverge)."""
    logger.warning(
        "No routing graph found (data/nagpur_graph.graphml or data/locality_graph.json). "
        "Run `python graph_builder.py` first. Falling back to a legacy COMPLETE graph, "
        "which means fastest/safest routes will always be identical direct paths."
    )
    import random
    random.seed(42)
    simple = nx.DiGraph()
    dist_m, time_m = {}, {}
    for a in LOCALITY_NAMES:
        dist_m[a], time_m[a] = {}, {}
        for b in LOCALITY_NAMES:
            if a == b:
                continue
            d = round(random.uniform(2, 12), 1)
            t = round(d * 2 + random.uniform(1, 5), 1)
            dist_m[a][b] = d
            time_m[a][b] = t
            simple.add_edge(a, b, weight=t, distance_km=d, time_min=t)
            NODE_TO_LOCALITY[a] = a
            NODE_TO_LOCALITY[b] = b
    return simple, dist_m, time_m


if os.path.exists(GRAPHML_PATH):
    try:
        G, _node_points = _load_real_road_graph()
        GRAPH_MODE = "real_road_network"
        logger.info("Loaded real Nagpur road network from %s (%d nodes, %d edges).",
                    GRAPHML_PATH, G.number_of_nodes(), G.number_of_edges())
    except (ImportError, OSError, ValueError) as e:
        logger.warning("Failed to load real road network (%s: %s). Trying fallback graph.", type(e).__name__, e)
        G = nx.DiGraph()

if GRAPH_MODE is None and os.path.exists(FALLBACK_GRAPH_PATH):
    G, DIST_MATRIX, TIME_MATRIX = _load_fallback_locality_graph()
    GRAPH_MODE = "sparse_locality_knn"
    logger.info("Loaded sparse k-NN locality graph from %s (%d nodes, %d edges).",
                FALLBACK_GRAPH_PATH, G.number_of_nodes(), G.number_of_edges())

if GRAPH_MODE is None:
    G, DIST_MATRIX, TIME_MATRIX = _load_legacy_complete_graph()
    GRAPH_MODE = "legacy_complete_graph"


def _resolve_node(locality_name):
    """Map a locality name to a routable graph node id (identity for locality-keyed
    graphs; nearest OSM node id for the real road network)."""
    if GRAPH_MODE == "real_road_network":
        for node, name in NODE_TO_LOCALITY.items():
            if name == locality_name:
                return node
        raise KeyError(f"No graph node found near locality '{locality_name}'")
    return locality_name


def _blended_risk_at(lat, lon, dep_hour, risk_cache, top_n=5):
    """Inverse-distance-weighted risk at an exact point, blending the
    nearest few localities instead of hard-assigning to a single nearest
    one. Without this, every point within a locality's whole nearest-
    neighbor region shares one identical risk value, so a route has no
    local incentive to curve away from a risky centroid - it only changes
    once it crosses into a different locality's region, and runs straight
    through the middle of whichever region it's currently in otherwise."""
    dists = []
    for name, loc in LOCALITIES.items():
        d = _haversine_km(lat, lon, loc["lat"], loc["lon"])
        dists.append((d, name))
    dists.sort(key=lambda x: x[0])
    nearest = dists[:top_n]

    total_weight = 0.0
    weighted_sum = 0.0
    for d, name in nearest:
        if name not in risk_cache:
            risk_cache[name] = locality_risk(name, dep_hour)["risk_score_100"] / 10.0
        w = 1.0 / (d ** 2 + 0.05)  # small epsilon avoids divide-by-zero at d=0
        weighted_sum += w * risk_cache[name]
        total_weight += w
    return weighted_sum / total_weight if total_weight > 0 else 5.0


def _edge_risk(u, v, dep_hour, risk_cache):
    """Risk for a single graph edge. In real_road_network mode, uses a
    smooth distance-weighted blend at the edge's exact midpoint (see
    _blended_risk_at) so routes can genuinely curve away from a risky
    centroid. In sparse/legacy modes, nodes ARE the named localities
    directly, so no sub-locality geography exists to blend - uses each
    endpoint's own risk instead."""
    if GRAPH_MODE == "real_road_network" and u in NODE_COORDS and v in NODE_COORDS:
        edge_key = ("edge", u, v)
        if edge_key not in risk_cache:
            lat_u, lon_u = NODE_COORDS[u]
            lat_v, lon_v = NODE_COORDS[v]
            mid_lat, mid_lon = (lat_u + lat_v) / 2, (lon_u + lon_v) / 2
            risk_cache[edge_key] = _blended_risk_at(mid_lat, mid_lon, dep_hour, risk_cache)
        return risk_cache[edge_key]

    loc_u = NODE_TO_LOCALITY.get(u, u if u in LOCALITIES else None)
    loc_v = NODE_TO_LOCALITY.get(v, v if v in LOCALITIES else None)
    names = [n for n in (loc_u, loc_v) if n]
    if not names:
        return 5.0  # neutral default if we truly can't attribute a locality
    vals = []
    for n in names:
        if n not in risk_cache:
            risk_cache[n] = locality_risk(n, dep_hour)["risk_score_100"] / 10.0
        vals.append(risk_cache[n])
    return sum(vals) / len(vals)


# -----------------------------------------------------------
# Routing: real k-shortest-paths (Yen's algorithm via networkx) instead
# of a single perturbed-weight hack, so candidate routes are genuinely
# distinct rather than usually collapsing to the same path.
# -----------------------------------------------------------
def compute_routes(origin, destination, dep_hour, alpha=0.25, beta=0.75, k=5):
    o_node = _resolve_node(origin)
    d_node = _resolve_node(destination)

    if o_node not in G or d_node not in G:
        raise ValueError(f"Unknown locality: '{origin}' or '{destination}'")

    risk_cache = {}

    def risk_weight(u, v, data):
        de = data.get("distance_km", 1)
        re = _edge_risk(u, v, dep_hour, risk_cache)
        return alpha * de + beta * re * de

    try:
        Tmin = nx.dijkstra_path_length(G, o_node, d_node, weight="time_min")
    except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
        raise ValueError(f"No route exists between '{origin}' and '{destination}': {e}")

    candidate_paths = []
    seen = set()

    # Up to k fastest paths (time-weighted)
    try:
        gen = nx.shortest_simple_paths(G, o_node, d_node, weight="time_min")
        for path in islice(gen, k):
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                candidate_paths.append(("time", path))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass

    # Up to k safest paths (risk-weighted)
    try:
        gen = nx.shortest_simple_paths(G, o_node, d_node, weight=risk_weight)
        for path in islice(gen, k):
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                candidate_paths.append(("risk", path))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass

    if not candidate_paths:
        raise ValueError(f"No route could be computed between '{origin}' and '{destination}'.")

    results = []
    for source, path in candidate_paths:
        if len(path) < 2:
            continue
        exposure_sum = distance_sum = max_risk = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            edge = G[u][v]
            de = edge.get("distance_km", 1)
            re = _edge_risk(u, v, dep_hour, risk_cache)
            exposure_sum += re * de
            distance_sum += de
            max_risk = max(max_risk, re)

        mean_risk = round(exposure_sum / distance_sum, 2) if distance_sum > 0 else 0
        total_time = sum(G[path[i]][path[i + 1]].get("time_min", 0) for i in range(len(path) - 1))
        total_distance = sum(G[path[i]][path[i + 1]].get("distance_km", 0) for i in range(len(path) - 1))

        detour_pct = ((total_time - Tmin) / Tmin) * 100 if Tmin > 0 else 0
        feasible = detour_pct <= 25.0

        avg_conf = np.mean([risk_cache.get(NODE_TO_LOCALITY.get(n, n), 0.8) for n in path]) if path else 0.8
        uncertainty = round(max(0.0, 1 - min(avg_conf, 1.0)), 2)

        norm_time = total_time / max(Tmin * 1.5, 1)
        norm_risk = mean_risk / 10.0
        norm_rmax = max_risk / 10.0
        norm_unc = uncertainty

        J = round(0.15 * norm_time + 0.50 * norm_risk + 0.25 * norm_rmax + 0.10 * norm_unc, 4)

        readable_path = [NODE_TO_LOCALITY.get(n, str(n)) for n in path] if GRAPH_MODE == "real_road_network" else path

        if GRAPH_MODE == "real_road_network":
            # Real street-by-street geometry (every OSM node the route passes
            # through), not just the named-area waypoints — this is what lets
            # the map draw the route actually following streets instead of
            # straight lines between area centroids.
            path_coords = [[NODE_COORDS[n][0], NODE_COORDS[n][1]] for n in path if n in NODE_COORDS]
        else:
            # No real street geometry available in this mode; use each
            # area's centroid coordinates instead.
            path_coords = [[LOCALITIES[n]["lat"], LOCALITIES[n]["lon"]] for n in path if n in LOCALITIES]

        results.append({
            "source": source,
            "path": readable_path,
            "path_coords": path_coords,
            "total_time_min": round(total_time, 1),
            "total_distance_km": round(total_distance, 1),
            "mean_risk": mean_risk,
            "peak_risk": round(max_risk, 2),
            "uncertainty": uncertainty,
            "detour_percent": round(detour_pct, 1),
            "feasible": feasible,
            "risk_score_J": J,
        })

    if not results:
        raise ValueError("No feasible routes found.")

    fastest = min(results, key=lambda r: r["total_time_min"])
    safest = min(results, key=lambda r: r["mean_risk"])
    feasible_results = [r for r in results if r["feasible"]] or results
    recommended = min(feasible_results, key=lambda r: r["risk_score_J"])

    final = []
    shown_paths = []  # list of (category_label, path_tuple) already added

    def add(route, category, explanation):
        path_key = tuple(route["path"])
        duplicate_of = next((label for label, p in shown_paths if p == path_key), None)
        if duplicate_of:
            explanation = (
                f"Same route as '{duplicate_of}' — no meaningfully different, "
                f"lower-exposure alternative was found among the candidate paths searched."
            )
        shown_paths.append((category, path_key))
        final.append({**route, "category": category, "explanation": explanation,
                       "duplicate_of": duplicate_of})

    add(recommended, "recommended",
        "Best balance of time and safety exposure, computed across multiple real candidate routes.")
    add(fastest, "fastest", "Minimizes travel time; may cross higher-exposure segments at night.")
    add(safest, "safest",
        f"Lowest mean exposure; {'exceeds' if safest['detour_percent'] > 25 else 'within'} the 25% detour limit vs. fastest.")

    return final


# -----------------------------------------------------------
# SOS: attempts a real Twilio SMS if configured via environment
# variables; otherwise falls back to the original acknowledgment-only
# behavior. Twilio credentials are never hardcoded.
#
# Nearest police station: identified by real jurisdiction name from the
# dataset (each area's Police_Station value matches its own Area name 1:1
# in the real CSV), found via nearest-centroid lookup against the
# person's GPS coordinates. We deliberately do NOT show a direct-dial
# number for that specific station: the dataset doesn't include verified
# phone numbers, and a wrong number in a real emergency is worse than no
# number. Calling always uses India's official, verified emergency lines
# (100 / 112 / 1091) instead.
# -----------------------------------------------------------
NATIONAL_EMERGENCY_NUMBERS = {
    "police": "100",
    "unified_emergency": "112",
    "women_helpline": "1091",
    "ambulance": "108",
}

# Verified from the official government listing at nagpur.gov.in/police/
# ("Nagpur City Police, Behind Collector Office, West High Court Road,
# Civil Lines, Phone: 0712 256 0601"). Used as a fallback for areas that
# don't have their own specific verified station number, so there's still
# a real, correct local(ish) number to try before the national lines.
NAGPUR_POLICE_HQ_PHONE = "0712-2560601"

# Some station names in the contacts CSV don't exactly match the dataset's
# area names (e.g. "Rana Pratap Nagar" vs area "Pratap Nagar"). Mapped by
# hand since there are only a handful of mismatches.
STATION_NAME_ALIASES = {
    "Nandavan": "Nandanvan",
    "Pachpaoli": "Panchpaoli",
    "Rana Pratap Nagar": "Pratap Nagar",
    "Lakadapul": "Lakadganj",
    "Juni Kamptee": "Kamptee",
}


def _load_police_contacts():
    """Map area name -> a verified real phone number, from the uploaded
    contacts CSV. Entries whose Contact Number is literally 'Available'
    (a placeholder, not a real verified number) are excluded on purpose -
    showing an unverified/fake number in a safety feature is worse than
    showing none."""
    path = os.path.join(DATA_DIR, "nagpur_police_contacts.csv")
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
    except Exception as e:
        logger.warning("Could not read police contacts CSV: %s", e)
        return {}

    stations = df[df["Type"] == "Police Station"].copy()
    stations = stations[stations["Contact Number"].astype(str).str.contains(r"\d{4,}")]

    mapping = {}
    for _, row in stations.iterrows():
        raw_name = str(row["Police Station/Contact"]).replace("Police Station", "").strip()
        canonical = STATION_NAME_ALIASES.get(raw_name, raw_name)
        if canonical not in LOCALITIES:
            continue
        if canonical not in mapping:  # keep first (primary) number if an area has duplicates
            mapping[canonical] = str(row["Contact Number"]).strip()
    return mapping


POLICE_CONTACTS = _load_police_contacts()
logger.info("Loaded %d verified police station contact numbers.", len(POLICE_CONTACTS))


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _nearest_police_jurisdiction(lat, lng):
    """Real jurisdiction name (= area name) nearest the given coordinates,
    using actual area centroids from the dataset."""
    if not LOCALITIES:
        return None, None
    best_name, best_dist = None, float("inf")
    for name, loc in LOCALITIES.items():
        d = _haversine_km(lat, lng, loc["lat"], loc["lon"])
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, round(best_dist, 2)


def _send_sos_sms(lat, lng, timestamp, station_name, station_phone, message_note,
                   to_number_override=None, contact_name=None, tracking_url=None):
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    to_number = to_number_override or os.environ.get("EMERGENCY_CONTACT_NUMBER")

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.info("Twilio not configured or no contact number available (set TWILIO_ACCOUNT_SID, "
                     "TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER env vars, and either EMERGENCY_CONTACT_NUMBER "
                     "or a per-request contact_phone, to enable real SMS). "
                     "Falling back to acknowledgment-only SOS response.")
        return {"sent": False, "reason": "twilio_not_configured"}

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        station_line = f"{station_name} Police Station: {station_phone}." if station_phone else \
            f"Nearest jurisdiction: {station_name or 'unknown'} (no verified direct line - call 100)."
        greeting = f"Hi {contact_name}, this is an automatic safety alert. " if contact_name else ""
        tracking_line = f" Live location: {tracking_url}." if tracking_url else ""
        body = (
            f"{greeting}SOS ALERT at {timestamp}. {message_note} "
            f"Location: https://maps.google.com/?q={lat},{lng}.{tracking_line} "
            f"{station_line} "
            f"If unreachable, call 100 (Police) or 112 (Emergency)."
        )
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        logger.info("Sent SOS SMS via Twilio, sid=%s", message.sid)
        return {"sent": True, "sid": message.sid}
    except ImportError:
        logger.warning("twilio package not installed; falling back to acknowledgment-only SOS response.")
        return {"sent": False, "reason": "twilio_package_missing"}
    except Exception as e:
        # Twilio's SDK can raise several exception types (auth, network, rest errors);
        # catching broadly here is intentional so a misconfigured/unreachable SMS
        # provider never breaks the emergency acknowledgment path itself.
        logger.error("Twilio SMS send failed (%s): %s", type(e).__name__, e)
        return {"sent": False, "reason": f"twilio_error: {e}"}


def _start_tracking_link(lat, lng, origin_label="SOS", destination_label="", path_coords=None, duration_min=360):
    """Creates a trip-like entry purely so an SOS alert can include a live
    tracking link, reusing the same in-memory trip store and /track page.
    Long default duration (6h) since SOS doesn't have a natural 'expected
    arrival' - the auto-alert-on-timeout behavior still applies as a
    harmless bonus if it's never explicitly ended."""
    trip_id = uuid.uuid4().hex
    share_id = uuid.uuid4().hex[:10]
    now = datetime.utcnow()
    trip = {
        "trip_id": trip_id,
        "share_id": share_id,
        "origin": origin_label,
        "destination": destination_label,
        "path_coords": path_coords or [],
        "created_at": now.isoformat(),
        "deadline_ts": now.timestamp() + duration_min * 60,
        "duration_min": duration_min,
        "last_location": {"lat": lat, "lng": lng, "updated_at": now.isoformat()},
        "status": "active",
        "sms": None,
    }
    with TRIPS_LOCK:
        ACTIVE_TRIPS[trip_id] = trip
    return trip_id, share_id


# -----------------------------------------------------------
# Trip check-in: start a timer before a trip; if the person doesn't check
# in as arrived before the deadline, an alert automatically fires using
# the same SOS SMS pipeline (last known location + nearest jurisdiction).
# Also generates a shareable read-only link a trusted contact can open to
# watch the trip's live location without needing the app themselves.
#
# Storage is a simple in-memory dict, not a database - fine for a single-
# process demo (the Procfile already runs gunicorn with --workers 1 for
# this reason), but trips are lost on server restart and this would need
# a real datastore (Redis, a DB) to survive restarts or scale to multiple
# worker processes.
# -----------------------------------------------------------
ACTIVE_TRIPS = {}
TRIP_TIMERS = {}
TRIPS_LOCK = threading.Lock()
MAX_TRIP_DURATION_MIN = 6 * 60  # 6 hours, sanity cap


def _trip_timeout_handler(trip_id):
    """Fires automatically when a trip's check-in deadline passes without
    the person confirming they arrived safely."""
    with TRIPS_LOCK:
        trip = ACTIVE_TRIPS.get(trip_id)
        if not trip or trip["status"] != "active":
            return
        trip["status"] = "auto_alerted"
        trip["alerted_at"] = datetime.utcnow().isoformat()
        lat = trip["last_location"]["lat"]
        lng = trip["last_location"]["lng"]
        origin = trip["origin"]
        destination = trip["destination"]
        contact_phone = trip.get("contact_phone")
        contact_name = trip.get("contact_name")
        share_id = trip["share_id"]
        base_url = trip.get("base_url")

    station_name, station_km = _nearest_police_jurisdiction(lat, lng)
    station_phone = POLICE_CONTACTS.get(station_name)
    phone_to_use = station_phone or NAGPUR_POLICE_HQ_PHONE
    message_note = (
        f"Check-in overdue for a trip from {origin} to {destination} - "
        f"expected arrival time passed without confirmation."
    )
    tracking_url = f"{base_url}/track/{share_id}" if base_url else None
    sms_result = _send_sos_sms(lat, lng, datetime.utcnow().isoformat(), station_name, phone_to_use, message_note,
                                to_number_override=contact_phone, contact_name=contact_name, tracking_url=tracking_url)

    with TRIPS_LOCK:
        trip["sms"] = sms_result
        trip["nearest_police_jurisdiction"] = {
            "area_name": station_name, "approx_distance_km": station_km, "phone": phone_to_use,
        }
    logger.warning("Trip %s timed out without check-in (%s -> %s); auto-alert sent.", trip_id, origin, destination)


@app.route("/api/trip/start", methods=["POST"])
def api_trip_start():
    data = request.get_json(silent=True) or {}
    origin = str(data.get("origin", ""))[:100]
    destination = str(data.get("destination", ""))[:100]
    path_coords = data.get("path_coords", [])
    contact_name = data.get("contact_name")
    contact_phone = data.get("contact_phone")
    base_url = request.host_url.rstrip("/")

    try:
        duration_min = float(data.get("duration_min"))
        if not (0 < duration_min <= MAX_TRIP_DURATION_MIN):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": f"duration_min must be a positive number of minutes, up to {MAX_TRIP_DURATION_MIN}."}), 400

    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "Valid lat/lng are required to start a trip."}), 400

    trip_id = uuid.uuid4().hex
    share_id = uuid.uuid4().hex[:10]
    now = datetime.utcnow()
    deadline_ts = now.timestamp() + duration_min * 60

    trip = {
        "trip_id": trip_id,
        "share_id": share_id,
        "origin": origin,
        "destination": destination,
        "path_coords": path_coords if isinstance(path_coords, list) else [],
        "created_at": now.isoformat(),
        "deadline_ts": deadline_ts,
        "duration_min": duration_min,
        "last_location": {"lat": lat, "lng": lng, "updated_at": now.isoformat()},
        "status": "active",
        "sms": None,
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "base_url": base_url,
    }

    with TRIPS_LOCK:
        ACTIVE_TRIPS[trip_id] = trip
        timer = threading.Timer(duration_min * 60, _trip_timeout_handler, args=[trip_id])
        timer.daemon = True
        timer.start()
        TRIP_TIMERS[trip_id] = timer

    logger.info("Trip started: %s (%s -> %s, %.1f min)", trip_id, origin, destination, duration_min)
    return jsonify({
        "trip_id": trip_id,
        "share_id": share_id,
        "share_path": f"/track/{share_id}",
        "deadline_ts": deadline_ts,
    })


@app.route("/api/trip/<trip_id>/checkin", methods=["POST"])
def api_trip_checkin(trip_id):
    with TRIPS_LOCK:
        trip = ACTIVE_TRIPS.get(trip_id)
        if not trip:
            return jsonify({"error": "Trip not found."}), 404
        if trip["status"] == "active":
            trip["status"] = "arrived_safe"
            trip["resolved_at"] = datetime.utcnow().isoformat()
        status = trip["status"]
        timer = TRIP_TIMERS.pop(trip_id, None)

    if timer:
        timer.cancel()

    return jsonify({"message": "Checked in - glad you made it safely!", "status": status})


@app.route("/api/trip/<trip_id>/location", methods=["POST"])
def api_trip_location(trip_id):
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "Valid lat/lng are required."}), 400

    with TRIPS_LOCK:
        trip = ACTIVE_TRIPS.get(trip_id)
        if not trip:
            return jsonify({"error": "Trip not found."}), 404
        trip["last_location"] = {"lat": lat, "lng": lng, "updated_at": datetime.utcnow().isoformat()}

    return jsonify({"ok": True})


@app.route("/api/trip/share/<share_id>", methods=["GET"])
def api_trip_share(share_id):
    """Public, read-only lookup for the trip-tracking page. The share_id
    is an unguessable random token (not a login), which is a reasonable
    tradeoff for a lightweight demo feature - anyone who has the exact
    link can view the trip's live location, same tradeoff most consumer
    trip-sharing features make."""
    with TRIPS_LOCK:
        trip = next((t for t in ACTIVE_TRIPS.values() if t["share_id"] == share_id), None)
        if not trip:
            return jsonify({"error": "This tracking link wasn't found - the trip may have ended or the server restarted."}), 404
        payload = {
            "origin": trip["origin"],
            "destination": trip["destination"],
            "path_coords": trip["path_coords"],
            "last_location": trip["last_location"],
            "status": trip["status"],
            "deadline_ts": trip["deadline_ts"],
            "created_at": trip["created_at"],
            "nearest_police_jurisdiction": trip.get("nearest_police_jurisdiction"),
        }
    return jsonify(payload)


# -----------------------------------------------------------
# Flask Endpoints
# -----------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/track/<share_id>")
def track_page(share_id):
    return send_from_directory(STATIC_DIR, "track.html")


@app.route("/api/localities", methods=["GET"])
def api_localities():
    """List localities with coordinates and current risk, for populating the
    map/dropdowns and color-coding areas by risk level."""
    hour = request.args.get("hour", type=int)
    if hour is None:
        hour = datetime.utcnow().hour

    localities = []
    for name, loc in LOCALITIES.items():
        risk = locality_risk(name, hour)
        localities.append({
            "name": name,
            "lat": loc["lat"],
            "lon": loc["lon"],
            "risk_score_100": risk["risk_score_100"],
            "risk_band": risk["risk_band"],
            "confidence": risk["confidence"],
        })

    return jsonify({
        "graph_mode": GRAPH_MODE,
        "hour": hour,
        "localities": localities,
    })


@app.route("/api/predict_risk", methods=["POST"])
def api_predict_risk():
    data = request.get_json(silent=True) or {}
    try:
        lighting = float(data.get("lighting", 5.5))
        dark_spot = int(data.get("dark_spot", 0))
        crowd = int(data.get("crowd", 1))
        police_km = float(data.get("police_km", 2.6))
        hour = int(data.get("hour", 22))
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400

    result = predict_risk_from_features(lighting, dark_spot, crowd, police_km, hour)
    result["data_age"] = "Last updated: synthetic prototype - replace with municipal API"
    return jsonify(result)


@app.route("/api/optimize_route", methods=["POST"])
def api_optimize_route():
    data = request.get_json(silent=True) or {}
    origin = data.get("origin", "Ramdaspeth")
    destination = data.get("destination", "Dhantoli")
    departure_str = data.get("departure_time", datetime.utcnow().isoformat())

    try:
        dep_hour = datetime.fromisoformat(departure_str).hour
    except ValueError:
        logger.warning("Could not parse departure_time '%s'; defaulting to hour=19.", departure_str)
        dep_hour = 19

    try:
        routes = compute_routes(origin, destination, dep_hour)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "origin": origin,
        "destination": destination,
        "departure_time": departure_str,
        "graph_mode": GRAPH_MODE,
        "routes": routes,
    })


@app.route("/api/sos", methods=["POST"])
def api_sos():
    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lng = data.get("lng")
    timestamp = data.get("timestamp", datetime.utcnow().isoformat())
    message_note = data.get("message", "I need help.")
    contact_name = data.get("contact_name")
    contact_phone = data.get("contact_phone")

    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Coordinates out of range")
    except (TypeError, ValueError):
        return jsonify({"error": "Valid 'lat' and 'lng' are required"}), 400

    station_name, station_km = _nearest_police_jurisdiction(lat, lng)
    station_phone = POLICE_CONTACTS.get(station_name)
    is_hq_fallback = station_phone is None
    phone_to_use = station_phone or NAGPUR_POLICE_HQ_PHONE

    # SOS doesn't have a natural route to attach to, but still generates a
    # live-tracking link (reusing the trip infrastructure) so the SMS and
    # response can include somewhere the contact can watch location update
    # in real time, not just a one-time static map pin.
    _, share_id = _start_tracking_link(lat, lng, origin_label="SOS", destination_label="")
    tracking_url = f"{request.host_url.rstrip('/')}/track/{share_id}"

    sms_result = _send_sos_sms(lat, lng, timestamp, station_name, phone_to_use, message_note,
                                to_number_override=contact_phone, contact_name=contact_name, tracking_url=tracking_url)

    sos_record = {
        "sos_id": f"SOS-{datetime.utcnow().timestamp():.0f}",
        "coordinates": {"lat": lat, "lng": lng},
        "timestamp": timestamp,
        "status": "activated",
        "sms": sms_result,
        "tracking_url": tracking_url,
        "nearest_police_jurisdiction": {
            "area_name": station_name,
            "approx_distance_km": station_km,
            "phone": phone_to_use,
            "is_hq_fallback": is_hq_fallback,
            "note": (
                f"Verified contact number for {station_name} Police Station."
                if station_phone else
                f"No verified direct number for {station_name} Police Station specifically - "
                f"using the verified Nagpur City Police HQ number instead."
            ),
        },
        "emergency_numbers": NATIONAL_EMERGENCY_NUMBERS,
    }
    logger.info("SOS activated: %s (nearest jurisdiction: %s)", sos_record["sos_id"], station_name)

    return jsonify({
        "message": "SOS activated. Coordinated response initiated.",
        "sos_record": sos_record,
        "instructions": "Tap Call Police (100) or Emergency (112) below for immediate help. "
                         "Your location has been shared with your emergency contact if configured.",
    })


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    """Aggregate stats from the real crime dataset, for the Analytics dashboard."""
    if not os.path.exists(REAL_CSV_PATH):
        return jsonify({"error": "Real dataset not found on server."}), 404

    df = pd.read_csv(REAL_CSV_PATH)
    total = len(df)
    night_pct = round((df["Time_Slot"] == "Night").mean() * 100, 1)

    area_group = df.groupby("Area").agg(
        total=("Crime_ID", "count"),
        avg_risk=("Risk_Score", "mean"),
        avg_lighting=("Street_Lighting_Score", "mean"),
        avg_police_km=("Nearby_Police_km", "mean"),
    ).round(2)
    # Most common Risk_Level per area (mode)
    area_group["risk_level"] = df.groupby("Area")["Risk_Level"].agg(lambda s: s.mode().iloc[0])
    area_group["safety_score"] = (100 - area_group["avg_risk"]).round(1)
    area_group = area_group.sort_values("avg_risk", ascending=False)

    high_risk_areas = int((area_group["risk_level"] == "High").sum())
    safest_area = area_group["safety_score"].idxmax()

    area_summary = [
        {
            "area": area,
            "total": int(row["total"]),
            "avg_risk": round(row["avg_risk"], 1),
            "safety_score": row["safety_score"],
            "avg_lighting": row["avg_lighting"],
            "avg_police_km": row["avg_police_km"],
            "risk_level": row["risk_level"],
        }
        for area, row in area_group.iterrows()
    ]

    crime_type_dist = df["Crime_Type"].value_counts().to_dict()
    time_slot_dist = df["Time_Slot"].value_counts().reindex(
        ["Morning", "Afternoon", "Evening", "Night"]).fillna(0).astype(int).to_dict()
    crime_by_area = df["Area"].value_counts().head(15).to_dict()
    safety_by_area = area_group["safety_score"].sort_values(ascending=False).head(15).to_dict()

    return jsonify({
        "total_records": total,
        "high_risk_areas": high_risk_areas,
        "night_crime_pct": night_pct,
        "safest_area": safest_area,
        "num_areas": int(df["Area"].nunique()),
        "area_summary": area_summary,
        "crime_type_distribution": crime_type_dist,
        "time_slot_distribution": time_slot_dist,
        "crime_count_by_area": crime_by_area,
        "safety_score_by_area": safety_by_area,
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "operational",
        "model": "Smart Women Safety Platform v1.0",
        "graph_mode": GRAPH_MODE,
        "ml_model_loaded": risk_rf is not None,
        "paper_references": ["Eq 5-6 risk model", "k-shortest-paths routing", "SOS cascade"],
        "endpoints": ["/api/predict_risk", "/api/optimize_route", "/api/sos", "/api/localities"],
    })


if __name__ == "__main__":
    print("Starting Smart Women Safety Platform Backend...")
    print(f"Routing graph mode: {GRAPH_MODE}")
    print("Available at: http://127.0.0.1:5000")
    if GRAPH_MODE != "real_road_network":
        print("Tip: run `python graph_builder.py` with internet access to fetch the real road network.")
    app.run(host="0.0.0.0", port=5000, debug=False)
