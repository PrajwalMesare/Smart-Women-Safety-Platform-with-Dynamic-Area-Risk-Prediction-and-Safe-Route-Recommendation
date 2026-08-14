"""
train_model.py — trains the RandomForest risk model once and saves it,
so app.py loads a pretrained model instead of refitting scikit-learn
on every server startup.

Run this once (after graph_builder.py):

    python train_model.py

Produces:
    data/safety_data.pkl        — synthetic training dataset (same schema as before)
    models/risk_model.joblib    — trained RandomForestRegressor
"""
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import joblib

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
SAFETY_DATA_PATH = os.path.join(DATA_DIR, "safety_data.pkl")
MODEL_PATH = os.path.join(MODELS_DIR, "risk_model.joblib")


def generate_synthetic_data(n=1446, seed=42):
    """Matches the distribution used in the original notebook / paper's data summary."""
    np.random.seed(seed)

    L = np.random.normal(5.53, 2.5, n).clip(1, 10)
    dark_spot = np.random.choice([0, 1], n, p=[0.742, 0.258])
    crowd = np.random.choice([0, 1, 2], n, p=[0.4, 0.4, 0.2])
    police_dist = np.random.uniform(0.2, 5.0, n)
    time_slot = np.random.choice([0, 1, 2, 3], n)

    Cl = 0.6 * (1 - (L - 1) / 9) + 0.4 * dark_spot + np.random.normal(0, 0.05, n)
    Cl = np.clip(Cl, 0, 1)
    Ll = (L - 1) / 9
    Hl = np.where(crowd == 0, 0, np.where(crowd == 1, 0.5, 1.0))

    multiplier = np.select(
        [time_slot == 0, time_slot == 1, time_slot == 2, time_slot == 3],
        [0.80, 1.00, 1.15, 1.25],
        default=1.0,
    )

    R_base = 10 * (0.50 * Cl + 0.30 * (1 - Ll) + 0.20 * (1 - Hl))
    R = np.minimum(10, multiplier * R_base)

    return pd.DataFrame({
        "Street_Lighting": L,
        "Known_Dark_Spot": dark_spot,
        "Crowd_Density": crowd,
        "Police_Distance_km": police_dist,
        "Time_Slot": time_slot,
        "Risk_Score": R,
        "Cl": Cl,
        "Ll": Ll,
        "Hl": Hl,
    })


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)

    df = generate_synthetic_data()
    df.to_pickle(SAFETY_DATA_PATH)
    print(f"Saved synthetic training data to {SAFETY_DATA_PATH} ({len(df)} rows).")

    X = df[["Street_Lighting", "Known_Dark_Spot", "Crowd_Density", "Police_Distance_km", "Time_Slot"]]
    y = df["Risk_Score"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestRegressor(n_estimators=300, max_depth=15, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    print(f"RandomForest performance: MAE={mae:.3f}, R2={r2:.3f}")

    importances = pd.Series(model.feature_importances_, X.columns).sort_values(ascending=False)
    print("Feature importances:")
    print(importances.to_string())

    joblib.dump(model, MODEL_PATH)
    print(f"Saved trained model to {MODEL_PATH}.")


if __name__ == "__main__":
    main()
