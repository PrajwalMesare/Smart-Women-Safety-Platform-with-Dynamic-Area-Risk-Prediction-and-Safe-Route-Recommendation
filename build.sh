#!/usr/bin/env bash
# Build script for deployment platforms (Render, Railway, etc.).
# Set this as the platform's "build command".
set -e

pip install -r requirements.txt

# Builds the routing graph. Tries the real OSM road network first; if the
# platform's network doesn't allow reaching OpenStreetMap/Overpass (or the
# request times out on a free tier), this automatically falls back to the
# sparse k-nearest-neighbor locality graph instead of failing the build.
python graph_builder.py

# Trains and saves the risk model so the server doesn't retrain on every
# cold start / restart.
python train_model.py

echo "Build complete."
