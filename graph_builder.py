"""
graph_builder.py — builds the routing graph used by app.py.

Two modes, tried in order:

1. REAL ROAD NETWORK (preferred): uses OSMnx to download the actual
   Nagpur drivable street network from OpenStreetMap and caches it to
   data/nagpur_graph.graphml. This requires outbound internet access to
   the OSM/Overpass API, which is NOT available in some sandboxed/CI
   environments. On a normal laptop with internet access this works
   out of the box — just run:

       python graph_builder.py

   The first run downloads and caches the graph; later runs (and app.py
   itself) reuse the cached .graphml file, so this network call only
   happens once.

2. SPARSE LOCALITY FALLBACK: if OSMnx/Overpass isn't reachable, we
   build a k-nearest-neighbor graph over the 18 locality centroids in
   data/localities.json instead. This is still a big improvement over
   the old app.py, which connected every locality directly to every
   other locality (a complete graph). A complete graph means the
   "shortest path" between any two points is ALWAYS the direct edge,
   so fastest/safest/recommended routes could never actually differ.
   The k-NN fallback forces routes through intermediate localities,
   so risk-weighted and time-weighted paths can genuinely diverge.

Run this script once before starting app.py:

    python graph_builder.py
"""
import json
import math
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOCALITIES_PATH = os.path.join(DATA_DIR, "localities.json")
GRAPHML_PATH = os.path.join(DATA_DIR, "nagpur_graph.graphml")
FALLBACK_GRAPH_PATH = os.path.join(DATA_DIR, "locality_graph.json")

NAGPUR_PLACE_NAME = "Nagpur, Maharashtra, India"
K_NEAREST = 4  # each locality connects to its 4 nearest neighbors in fallback mode


def _load_localities():
    with open(LOCALITIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["localities"]


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_real_road_graph():
    """Attempt to fetch and cache the real Nagpur drivable street network via OSMnx."""
    import osmnx as ox

    print(f"Downloading real road network for '{NAGPUR_PLACE_NAME}' via OSMnx...")
    G = ox.graph_from_place(NAGPUR_PLACE_NAME, network_type="drive")
    os.makedirs(DATA_DIR, exist_ok=True)
    ox.save_graphml(G, GRAPHML_PATH)
    print(f"Saved real road network to {GRAPHML_PATH} ({len(G.nodes)} nodes, {len(G.edges)} edges).")
    return GRAPHML_PATH


def build_fallback_locality_graph():
    """Build a sparse k-nearest-neighbor graph over the 18 locality centroids."""
    localities = _load_localities()
    names = [loc["name"] for loc in localities]
    coords = {loc["name"]: (loc["lat"], loc["lon"]) for loc in localities}

    edges = []
    edge_keys = set()
    for a in localities:
        dists = []
        for b in localities:
            if a["name"] == b["name"]:
                continue
            d = _haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            dists.append((d, b["name"]))
        dists.sort(key=lambda x: x[0])
        for d, neighbor_name in dists[:K_NEAREST]:
            # Road distance is longer than straight-line distance; approximate with a
            # circuity factor typical of urban street grids (~1.3x).
            road_km = round(d * 1.3, 2)
            # ~2.2 min/km average urban driving speed + small fixed overhead (turns, signals)
            time_min = round(road_km * 2.2 + 1.0, 1)
            # Add both directions. A pure one-way k-NN graph can strand a node that
            # nobody else happens to pick as one of *their* nearest neighbors (e.g. an
            # outlying locality) — making it reachable but never reachable-FROM,
            # which breaks routing in either direction. Real streets are traversable
            # both ways, so this also better matches reality than a one-way graph.
            for u, v in [(a["name"], neighbor_name), (neighbor_name, a["name"])]:
                key = (u, v)
                if key not in edge_keys:
                    edge_keys.add(key)
                    edges.append({"from": u, "to": v, "distance_km": road_km, "time_min": time_min})

    graph_data = {
        "_comment": "Sparse k-nearest-neighbor fallback graph (used when OSMnx/Overpass is unreachable). "
                    "Unlike a complete graph, routes must pass through intermediate localities, so "
                    "fastest/safest/recommended paths can genuinely differ.",
        "k_nearest": K_NEAREST,
        "nodes": names,
        "coords": coords,
        "edges": edges,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FALLBACK_GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
    print(f"Saved fallback k-NN locality graph to {FALLBACK_GRAPH_PATH} "
          f"({len(names)} nodes, {len(edges)} directed edges, k={K_NEAREST}).")
    return FALLBACK_GRAPH_PATH


def main():
    try:
        build_real_road_graph()
    except Exception as e:
        print(f"Could not fetch real OSM road network ({type(e).__name__}: {e}).")
        print("Falling back to sparse k-nearest-neighbor locality graph.")
        build_fallback_locality_graph()


if __name__ == "__main__":
    main()
