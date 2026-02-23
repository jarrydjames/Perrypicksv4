"""
REPTAR Refined Halftime Prediction Model

This module provides halftime predictions using the refined temporal features
that achieve the documented 75% win accuracy.

Key differences from basic halftime model:
- Uses 139 refined temporal features (vs 12 basic)
- Uses CatBoost model (vs XGBoost)
- Looks up pre-computed rolling averages from feature store

Usage:
    from src.models.halftime_refined import RefinedHalftimeModel

    model = RefinedHalftimeModel()
    result = model.predict_from_game_id("0022500747")
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Model paths
METRICS_PATH = Path("reports/champion_runs/latest/halftime_fold_metrics.csv")
DEFAULT_DATA_PATH = Path("data/processed/halftime_with_refined_temporal.parquet")
TEAM_ID_MAP_PATH = Path("data/processed/team_tricode_to_custom_id.json")

# 80% interval z-score
Z80 = 1.2815515655446004


@dataclass
class RefinedHalftimePrediction:
    """Refined halftime prediction result with all features."""
    game_id: str

    # First half (actual)
    h1_home: int
    h1_away: int

    # Second half (predicted)
    pred_2h_total: float
    pred_2h_margin: float
    pred_2h_home: float
    pred_2h_away: float

    # Final (predicted)
    pred_final_home: float
    pred_final_away: float
    pred_final_total: float
    pred_final_margin: float

    # Intervals (80% CI)
    total_q10: float
    total_q90: float
    margin_q10: float
    margin_q90: float

    # Win probability (REPTAR)
    home_win_prob: float
    away_win_prob: float

    # Metadata
    model_name: str
    home_name: str
    away_name: str
    feature_version: str
    sigma_k_margin: float


def feature_columns(df: pd.DataFrame) -> List[str]:
    """Get feature columns from dataframe."""
    exclude = {
        'game_id', 'season_end_yy', 'game_date',
        'h1_home', 'h1_away', 'h1_total', 'h1_margin',
        'h1_events', 'h1_n_2pt', 'h1_n_3pt', 'h1_n_turnover',
        'h1_n_rebound', 'h1_n_foul', 'h1_n_timeout', 'h1_n_sub',
        'home_efg', 'away_efg', 'h2_total', 'h2_margin',
        'final_total', 'final_margin',
        'home_tri', 'away_tri', 'home_team_id', 'away_team_id'
    }

    features = [col for col in df.columns if col not in exclude]

    # Only numeric features
    numeric_features = []
    for col in features:
        if df[col].dtype in ['int64', 'float64', 'int32', 'float32']:
            numeric_features.append(col)

    return numeric_features


class RefinedHalftimeModel:
    """
    Refined halftime prediction model using temporal features and CatBoost.

    This model achieves 75% win accuracy by using:
    1. Pre-computed temporal features (rolling averages, trends, rest days)
    2. CatBoost ensemble model
    3. Proper feature lookups from historical data
    """

    def __init__(
        self,
        data_path: Path = None,
        metrics_path: Path = None,
        sigma_calib_frac: float = 0.15,
    ):
        self.data_path = data_path or DEFAULT_DATA_PATH
        self.metrics_path = metrics_path or METRICS_PATH
        self.sigma_calib_frac = sigma_calib_frac

        self._loaded = False
        self._df: Optional[pd.DataFrame] = None
        self._team_id_map: Dict[str, float] = {}
        self._model = None
        self._feature_cols: List[str] = []
        self._sigma_k_total: float = 3.0
        self._sigma_k_margin: float = 3.0

    def load(self) -> bool:
        """Load the model and feature store."""
        if self._loaded:
            return True

        # Load team ID mapping
        if TEAM_ID_MAP_PATH.exists():
            with open(TEAM_ID_MAP_PATH, 'r') as f:
                tri_to_id = json.load(f)
            self._team_id_map = {k: float(v) for k, v in tri_to_id.items()}
            logger.info(f"Loaded team ID mapping for {len(self._team_id_map)} teams")

        # Load refined temporal features
        if not self.data_path.exists():
            logger.error(f"Feature store not found at {self.data_path}")
            return False

        try:
            self._df = pd.read_parquet(self.data_path)
            self._df['game_date'] = pd.to_datetime(
                self._df['game_date'], errors='coerce', utc=True
            )
            self._feature_cols = feature_columns(self._df)
            self._loaded = True
            logger.info(f"Loaded {len(self._df)} games with {len(self._feature_cols)} features")
            return True
        except Exception as e:
            logger.error(f"Failed to load feature store: {e}")
            return False

    def _load_model_params(self) -> Tuple[Dict[str, Any], List[int]]:
        """Load production CatBoost hyperparameters from fold metrics."""
        if not self.metrics_path.exists():
            raise FileNotFoundError(f"Metrics file not found: {self.metrics_path}")

        metrics_df = pd.read_csv(self.metrics_path)
        fold_metrics = metrics_df[metrics_df["model"] == "catboost"].copy()

        # Get top 5 folds by tune_score
        fold_metrics = fold_metrics.sort_values("tune_score").head(5)

        if len(fold_metrics) == 0:
            raise ValueError("No CatBoost metrics found")

        selected_folds = [int(x) for x in fold_metrics["fold"].tolist()]

        # Parse parameters
        parsed = []
        for _, row in fold_metrics.iterrows():
            try:
                parsed.append(json.loads(row["params"]))
            except Exception:
                continue

        if not parsed:
            raise ValueError("Unable to parse CatBoost params")

        # Aggregate parameters (median for numeric, mode for categorical)
        keys = sorted({k for item in parsed for k in item.keys()})
        params = {}
        for key in keys:
            values = [item[key] for item in parsed if key in item]
            if not values:
                continue

            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                med = float(np.median(np.asarray(values, dtype=float)))
                if key in {"iterations", "depth", "random_seed"}:
                    params[key] = int(round(med))
                else:
                    params[key] = med
            else:
                # Use most frequent value
                counts = {}
                for v in values:
                    token = json.dumps(v, sort_keys=True)
                    counts[token] = counts.get(token, 0) + 1
                best_token = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                params[key] = json.loads(best_token)

        if "random_seed" not in params:
            params["random_seed"] = 42

        return params, selected_folds

    def _fit_sigma_scalers(
        self,
        X_train: np.ndarray,
        y_total_train: np.ndarray,
        y_margin_train: np.ndarray,
    ) -> Tuple[float, float]:
        """Fit sigma calibration factors on tail training split."""
        n_tr = int(len(X_train))
        n_cal = int(max(50, round(n_tr * self.sigma_calib_frac)))
        n_cal = min(n_cal, max(0, n_tr - 50))
        if n_cal <= 0:
            return 1.0, 1.0

        X_fit, X_cal = X_train[:-n_cal], X_train[-n_cal:]
        yt_fit, yt_cal = y_total_train[:-n_cal], y_total_train[-n_cal:]
        ym_fit, ym_cal = y_margin_train[:-n_cal], y_margin_train[-n_cal:]

        from src.modeling.cat_models import CatBoostTwoHeadModel

        model = CatBoostTwoHeadModel(**self._model_params)
        model.fit(X_fit, self._feature_cols, yt_fit, ym_fit)

        mu_t_cal, mu_m_cal = model.predict_heads(X_cal)

        heads = model.trained_heads()
        sig_t_raw = float(heads.total.residual_sigma)
        sig_m_raw = float(heads.margin.residual_sigma)

        q_t = float(np.quantile(np.abs(yt_cal - mu_t_cal), 0.80))
        q_m = float(np.quantile(np.abs(ym_cal - mu_m_cal), 0.80))
        k_t = q_t / max(1e-6, (Z80 * sig_t_raw))
        k_m = q_m / max(1e-6, (Z80 * sig_m_raw))
        k_t = float(max(0.5, min(3.0, k_t)))
        k_m = float(max(0.5, min(3.0, k_m)))
        return k_t, k_m

    def train_model(self, before_date: pd.Timestamp) -> bool:
        """Train the CatBoost model on historical data."""
        if not self._loaded:
            if not self.load():
                return False

        # Load model parameters
        try:
            self._model_params, selected_folds = self._load_model_params()
            logger.info(f"Loaded model params from folds: {selected_folds}")
        except Exception as e:
            logger.error(f"Failed to load model params: {e}")
            return False

        # Filter training data
        train_df = self._df[self._df['game_date'] < before_date].copy()
        logger.info(f"Training on {len(train_df)} games before {before_date}")

        # Prepare features
        X_train = train_df[self._feature_cols].values
        X_train = np.nan_to_num(X_train, nan=0.0)
        y_total_train = train_df['h2_total'].values
        y_margin_train = train_df['h2_margin'].values

        # Fit sigma scalers
        logger.info("Calibrating sigma scalers...")
        self._sigma_k_total, self._sigma_k_margin = self._fit_sigma_scalers(
            X_train, y_total_train, y_margin_train
        )
        logger.info(f"Sigma k values: total={self._sigma_k_total:.2f}, margin={self._sigma_k_margin:.2f}")

        # Train final model
        from src.modeling.cat_models import CatBoostTwoHeadModel

        self._model = CatBoostTwoHeadModel(**self._model_params)
        self._model.fit(X_train, self._feature_cols, y_total_train, y_margin_train)

        logger.info("Model trained successfully")
        return True

    def _get_team_features(
        self,
        team_id: float,
        target_dt: pd.Timestamp,
        prefix: str,
    ) -> Dict[str, float]:
        """Get team temporal features from historical data."""
        defaults = self._get_default_features(prefix)
        defaults[f"{prefix}_team_id"] = float(team_id)

        if team_id <= 0:
            return defaults

        latest_row = None
        latest_date = None

        for side in ["home", "away"]:
            id_col = f"{side}_team_id"
            subset = self._df[self._df[id_col] == team_id].copy()
            if subset.empty:
                continue

            subset = subset[subset['game_date'] < target_dt]
            if subset.empty:
                continue

            idx = subset['game_date'].idxmax()
            row = subset.loc[idx]
            row_date = row['game_date']

            if latest_date is None or row_date > latest_date:
                latest_date = row_date
                latest_row = row

        if latest_row is None:
            return defaults

        # Extract features
        features = defaults.copy()
        for col in self._df.columns:
            if col.startswith(f"{prefix}_"):
                if col in latest_row:
                    val = pd.to_numeric(latest_row[col], errors='coerce')
                    if pd.notna(val):
                        features[col] = float(val)

        return features

    def _get_default_features(self, prefix: str) -> Dict[str, float]:
        """Get default feature values."""
        return {
            f"{prefix}_pts_scored_avg_5": 54.0,
            f"{prefix}_pts_allowed_avg_5": 54.0,
            f"{prefix}_margin_avg_5": 0.0,
            f"{prefix}_current_streak": 0.0,
            f"{prefix}_days_since_last": 7.0,
            f"{prefix}_is_back_to_back": 0.0,
            f"{prefix}_efg": 0.52,
            f"{prefix}_tor": 0.12,
            f"{prefix}_tpar": 0.35,
            f"{prefix}_ftr": 0.25,
            f"{prefix}_orbp": 0.25,
            f"{prefix}_pts_scored_avg_10": 54.0,
            f"{prefix}_pts_allowed_avg_10": 54.0,
            f"{prefix}_margin_avg_10": 0.0,
            f"{prefix}_pts_scored_avg_20": 54.0,
            f"{prefix}_pts_allowed_avg_20": 54.0,
            f"{prefix}_margin_avg_20": 0.0,
            f"{prefix}_pts_scored_ewm_5": 54.0,
            f"{prefix}_pts_allowed_ewm_5": 54.0,
            f"{prefix}_margin_ewm_5": 0.0,
            f"{prefix}_wins_5": 2.5,
            f"{prefix}_wins_10": 5.0,
            f"{prefix}_wins_20": 10.0,
            f"{prefix}_is_3_in_4": 0.0,
            f"{prefix}_margin_trend_5": 0.0,
            f"{prefix}_pts_trend_5": 0.0,
            f"{prefix}_margin_std_5": 5.0,
            f"{prefix}_pts_scored_std_5": 5.0,
            f"{prefix}_games_played": 0.0,
        }

    def predict(
        self,
        h1_home: int,
        h1_away: int,
        home_team_id: float,
        away_team_id: float,
        target_dt: pd.Timestamp,
        *,
        game_id: str = "",
        home_name: str = "Home",
        away_name: str = "Away",
    ) -> Optional[RefinedHalftimePrediction]:
        """Make a halftime prediction using refined temporal features."""
        if not self._loaded:
            if not self.load():
                return None

        # Ensure model is trained
        if self._model is None:
            if not self.train_model(target_dt):
                return None

        # Get team features
        home_features = self._get_team_features(home_team_id, target_dt, "home")
        away_features = self._get_team_features(away_team_id, target_dt, "away")

        # Build feature row
        row = {
            "h1_home": h1_home,
            "h1_away": h1_away,
            "h1_total": h1_home + h1_away,
            "h1_margin": h1_home - h1_away,
        }
        row.update(home_features)
        row.update(away_features)

        # Add differential features
        for key, val in list(row.items()):
            if key.startswith("home_") and key != "home_team_id":
                away_key = key.replace("home_", "away_")
                if away_key in row:
                    diff_key = key.replace("home_", "diff_")
                    row[diff_key] = val - row[away_key]

        # Create feature vector
        X = pd.DataFrame([row])
        X = X.reindex(columns=self._feature_cols, fill_value=0.0)
        X = np.nan_to_num(X.values, nan=0.0)

        # Predict
        pred_2h_total, pred_2h_margin = self._model.predict_heads(X)
        pred_2h_total = float(pred_2h_total[0])
        pred_2h_margin = float(pred_2h_margin[0])

        # Allocate to teams
        pred_2h_home = (pred_2h_total + pred_2h_margin) / 2.0
        pred_2h_away = (pred_2h_total - pred_2h_margin) / 2.0

        # Final predictions
        pred_final_home = h1_home + pred_2h_home
        pred_final_away = h1_away + pred_2h_away
        pred_final_total = pred_final_home + pred_final_away
        pred_final_margin = pred_final_home - pred_final_away

        # Get sigma from trained model
        heads = self._model.trained_heads()
        sigma_total = heads.total.residual_sigma * self._sigma_k_total
        sigma_margin = heads.margin.residual_sigma * self._sigma_k_margin

        # 80% confidence intervals
        total_q10 = pred_final_total - Z80 * sigma_total
        total_q90 = pred_final_total + Z80 * sigma_total
        margin_q10 = pred_final_margin - Z80 * sigma_margin
        margin_q90 = pred_final_margin + Z80 * sigma_margin

        # REPTAR win probability
        h1_margin = h1_home - h1_away
        home_win_prob = 1.0 - norm.cdf(-h1_margin, loc=pred_2h_margin, scale=sigma_margin)

        return RefinedHalftimePrediction(
            game_id=game_id,
            h1_home=h1_home,
            h1_away=h1_away,
            pred_2h_total=pred_2h_total,
            pred_2h_margin=pred_2h_margin,
            pred_2h_home=pred_2h_home,
            pred_2h_away=pred_2h_away,
            pred_final_home=pred_final_home,
            pred_final_away=pred_final_away,
            pred_final_total=pred_final_total,
            pred_final_margin=pred_final_margin,
            total_q10=total_q10,
            total_q90=total_q90,
            margin_q10=margin_q10,
            margin_q90=margin_q90,
            home_win_prob=home_win_prob,
            away_win_prob=1.0 - home_win_prob,
            model_name="reptar_refined_catboost",
            home_name=home_name,
            away_name=away_name,
            feature_version="refined_temporal",
            sigma_k_margin=self._sigma_k_margin,
        )

    def predict_from_game_id(
        self,
        game_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Predict from game ID by fetching live data."""
        from src.data.game_data import (
            fetch_box,
            fetch_pbp_df,
            first_half_score,
            behavior_counts_1h,
            get_game_info,
        )

        # Extract game ID if URL provided
        gid = game_id
        if "nba.com" in game_id or len(game_id) > 12:
            from src.data.game_data import extract_game_id
            gid = extract_game_id(game_id)

        # Fetch game data
        try:
            game = fetch_box(gid)
        except Exception as e:
            logger.error(f"Failed to fetch game {gid}: {e}")
            return None

        # Get team info
        info = get_game_info(game)
        home_tri = info.get("home_tricode", "HOME")
        away_tri = info.get("away_tricode", "AWAY")

        # Get team IDs
        home_team_id = self._team_id_map.get(home_tri, 0.0)
        away_team_id = self._team_id_map.get(away_tri, 0.0)

        # Get first half scores
        h1_home, h1_away = first_half_score(game)
        if h1_home == 0 and h1_away == 0:
            logger.error(f"Could not get first half scores for {gid}")
            return None

        # Get game date
        target_dt = pd.Timestamp.now(tz='UTC')

        # Make prediction
        pred = self.predict(
            h1_home=h1_home,
            h1_away=h1_away,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            target_dt=target_dt,
            game_id=gid,
            home_name=home_tri,
            away_name=away_tri,
        )

        if pred is None:
            return None

        # Convert to dict
        return {
            "game_id": pred.game_id,
            "home_name": pred.home_name,
            "away_name": pred.away_name,
            "h1_home": pred.h1_home,
            "h1_away": pred.h1_away,
            "pred_2h_total": pred.pred_2h_total,
            "pred_2h_margin": pred.pred_2h_margin,
            "pred_2h_home": pred.pred_2h_home,
            "pred_2h_away": pred.pred_2h_away,
            "pred_final_home": pred.pred_final_home,
            "pred_final_away": pred.pred_final_away,
            "total": pred.pred_final_total,
            "margin": pred.pred_final_margin,
            "total_q10": pred.total_q10,
            "total_q90": pred.total_q90,
            "margin_q10": pred.margin_q10,
            "margin_q90": pred.margin_q90,
            "home_win_prob": pred.home_win_prob,
            "away_win_prob": pred.away_win_prob,
            "model_used": pred.model_name,
            "feature_version": pred.feature_version,
            "sigma_k_margin": pred.sigma_k_margin,
            "status": "success",
        }


# Global instance
_refined_model: Optional[RefinedHalftimeModel] = None


def get_refined_model() -> Optional[RefinedHalftimeModel]:
    """Get or create the global refined model instance."""
    global _refined_model

    if _refined_model is None:
        _refined_model = RefinedHalftimeModel()
        _refined_model.load()

    return _refined_model


__all__ = [
    'RefinedHalftimeModel',
    'RefinedHalftimePrediction',
    'get_refined_model',
    'feature_columns',
]
