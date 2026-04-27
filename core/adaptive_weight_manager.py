"""
core/adaptive_weight_manager.py — RossTrader_US

ML 기반 동적 팩터 가중치 관리.
Ridge 회귀로 과거 거래 데이터 학습 → 시장 국면별 팩터 가중치 자동 조정.

사용 예:
    wm = AdaptiveWeightManager()
    wm.retrain_on_trades(trade_db, market_regime="BULL")
    weights = wm.get_weights("BULL")
    # {'news_sentiment': 0.15, 'momentum': 0.30, ...}
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


class AdaptiveWeightManager:
    """
    ML 기반 동적 팩터 가중치 관리자.

    - Ridge 회귀로 과거 거래 데이터 학습 (과적합 방지)
    - 시장 국면(BULL/BEAR/SIDEWAYS)별 별도 모델
    - 최소 50건 이상 거래 데이터 필요
    """

    def __init__(self, model_dir: str = str(_MODEL_DIR)):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # 팩터 컬럼명 (학습 피처)
        self.feature_cols = [
            "news_sentiment_score",
            "factor_score",
            "vix_at_entry",
            "spy_trend_at_entry",
            "volume_ratio",
        ]

        # 시장 국면별 모델/스케일러/가중치
        self._models: Dict[str, Ridge] = {}
        self._scalers: Dict[str, StandardScaler] = {}
        self._weights: Dict[str, Dict[str, float]] = {}

        # 기본 가중치 (학습 데이터 부족 시 사용)
        self._default_weights = {
            "news_sentiment_score": 0.25,
            "factor_score": 0.30,
            "vix_at_entry": 0.10,
            "spy_trend_at_entry": 0.15,
            "volume_ratio": 0.20,
        }

        # 저장된 모델 로드
        self._load_models()

        logger.info("[AdaptiveWeight] 초기화 완료 | 모델 디렉토리: %s", self.model_dir)

    def _model_path(self, regime: str) -> Path:
        return self.model_dir / f"ridge_model_{regime.lower()}.pkl"

    def _scaler_path(self, regime: str) -> Path:
        return self.model_dir / f"scaler_{regime.lower()}.pkl"

    def _load_models(self):
        """저장된 모델 로드."""
        for regime in ["bull", "bear", "sideways", "high_vol", "low_vol"]:
            model_path = self._model_path(regime)
            scaler_path = self._scaler_path(regime)
            if model_path.exists():
                try:
                    with open(model_path, "rb") as f:
                        self._models[regime] = pickle.load(f)
                    with open(scaler_path, "rb") as f:
                        self._scalers[regime] = pickle.load(f)
                    logger.info("[AdaptiveWeight] %s 모델 로드 완료", regime)
                except Exception as e:
                    logger.warning("[AdaptiveWeight] %s 모델 로드 실패: %s", regime, e)

    def retrain_on_trades(
        self,
        feature_matrix: np.ndarray,
        targets: np.ndarray,
        market_regime: str,
    ) -> Dict[str, float]:
        """
        거래 데이터로 팩터 가중치 재학습.

        Args:
            feature_matrix: (n_samples, n_features) — 학습 데이터
            targets: (n_samples,) — 목표 변수 (pnl_pct)
            market_regime: 시장 국면 ('BULL' / 'BEAR' / 'SIDEWAYS')

        Returns:
            dict: 팩터별 동적 가중치
        """
        regime_key = market_regime.lower()
        n_samples = feature_matrix.shape[0]

        if n_samples < 50:
            logger.info(
                "[AdaptiveWeight] %s 데이터 부족 (%d건 < 50), 기본 가중치 사용",
                market_regime, n_samples,
            )
            self._weights[regime_key] = self._default_weights.copy()
            return self._weights[regime_key]

        try:
            # 스케일링
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(feature_matrix)

            # Ridge 회귀 학습 (L2 정규화로 과적합 방지)
            model = Ridge(alpha=1.0)
            model.fit(X_scaled, targets)

            # 모델 저장
            self._models[regime_key] = model
            self._scalers[regime_key] = scaler
            self._save_model(regime_key)

            # 회귀 계수를 소프트맥스 정규화하여 가중치로 변환
            coefs = np.maximum(model.coef_, 0)  # 음수 계수 → 0
            if coefs.sum() > 0:
                normalized = coefs / coefs.sum()
            else:
                normalized = np.ones(len(self.feature_cols)) / len(self.feature_cols)

            self._weights[regime_key] = dict(zip(self.feature_cols, normalized))

            logger.info(
                "[AdaptiveWeight] %s 재학습 완료 (%d건) | 가중치: %s",
                market_regime, n_samples,
                {k: f"{v:.3f}" for k, v in self._weights[regime_key].items()},
            )

        except Exception as e:
            logger.error("[AdaptiveWeight] %s 학습 실패: %s", market_regime, e)
            self._weights[regime_key] = self._default_weights.copy()

        return self._weights.get(regime_key, self._default_weights)

    def get_weights(self, market_regime: str) -> Dict[str, float]:
        """
        특정 시장 국면의 팩터 가중치 반환.
        학습된 모델이 없으면 기본 가중치 사용.
        """
        regime_key = market_regime.lower()
        weights = self._weights.get(regime_key)

        if weights is None:
            # 학습된 모델이 있으면 계수 기반 가중치 계산
            model = self._models.get(regime_key)
            if model is not None:
                coefs = np.maximum(model.coef_, 0)
                if coefs.sum() > 0:
                    normalized = coefs / coefs.sum()
                    weights = dict(zip(self.feature_cols, normalized))
                else:
                    weights = self._default_weights.copy()
            else:
                weights = self._default_weights.copy()

            self._weights[regime_key] = weights

        return weights

    def predict_score(
        self,
        features: Dict[str, float],
        market_regime: str,
    ) -> float:
        """
        팩터 가중치 기반 예측 점수 반환.

        Args:
            features: 팩터별 값 dict
            market_regime: 시장 국면

        Returns:
            float: 예측 점수 (-1~1 스케일, 높을수록 긍정)
        """
        weights = self.get_weights(market_regime)
        score = 0.0

        for feature, weight in weights.items():
            value = features.get(feature, 0.0)
            score += weight * value

        return score

    def _save_model(self, regime_key: str):
        """모델 저장."""
        try:
            model = self._models.get(regime_key)
            scaler = self._scalers.get(regime_key)
            if model and scaler:
                with open(self._model_path(regime_key), "wb") as f:
                    pickle.dump(model, f)
                with open(self._scaler_path(regime_key), "wb") as f:
                    pickle.dump(scaler, f)
                logger.info("[AdaptiveWeight] %s 모델 저장 완료", regime_key)
        except Exception as e:
            logger.warning("[AdaptiveWeight] %s 모델 저장 실패: %s", regime_key, e)

    def get_feature_importance(self, market_regime: str) -> Dict[str, float]:
        """팩터 중요도 반환 (가중치 내림차순)."""
        weights = self.get_weights(market_regime)
        return dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
