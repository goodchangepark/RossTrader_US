"""
core/self_improvement_engine.py — RossTrader_US

자가 개선 엔진.
매일 장 마감 후 자동으로 전략 성과를 분석하고
다음 날 파라미터를 조정하는 자가 개선 루프.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from core.market_regime import MarketRegimeDetector, MarketRegime
from utils.trade_db import TradeDB

logger = logging.getLogger(__name__)


class SelfImprovementEngine:
    """
    자가 개선 엔진.

    매일 장 마감 후 자동 실행:
    1. 오늘 거래 성과 분석
    2. 수익 낮은 전략 자동 비활성화
    3. VIX 기반 다음 날 리스크 파라미터 예비 조정
    4. ML 가중치 재훈련 (7일마다)
    5. 텔레그램/로그 리포트 발송
    """

    def __init__(
        self,
        trade_db: TradeDB,
        regime_detector: MarketRegimeDetector,
        adaptive_weight_manager: Any = None,
        config_path: str = "",
    ):
        self.db = trade_db
        self.regime_detector = regime_detector
        self.weight_manager = adaptive_weight_manager
        self.config_path = Path(config_path) if config_path else None

        # 비활성화된 전략 목록
        self.disabled_strategies: List[str] = []

        # 마지막 재학습일
        self.last_retrain_date: Optional[datetime] = None

        logger.info("[SelfImprovement] 자가 개선 엔진 초기화 완료")

    def daily_post_market_review(self, vix_level: float = 15.0, sp500_change: float = 0.0):
        """
        매일 장 마감 후 자동 실행.

        Args:
            vix_level: 현재 VIX 지수
            sp500_change: S&P500 일간 변동률 (%)
        """
        logger.info("=" * 60)
        logger.info("[SelfImprovement] 📊 일일 사후 분석 시작")
        logger.info("=" * 60)

        now = datetime.now()

        # 1. 오늘 거래 성과 분석
        analytics = self.db.get_strategy_analytics()
        if analytics is not None and not analytics.empty:
            logger.info("\n=== 일일 전략 성과 ===\n%s", analytics.to_string(index=False))
        else:
            logger.info("오늘 거래 내역 없음")
            return

        # 2. 수익 낮은 전략 자동 비활성화
        self._auto_disable_strategies(analytics)

        # 3. 시장 레짐 감지 및 파라미터 조정
        regime_info = self.regime_detector.detect(sp500_change, vix_level)
        params = regime_info.trading_params()
        logger.info(
            "\n=== 시장 레짐 ===\n레짐: %s (신뢰도: %.0f%%)\n파라미터: %s",
            regime_info.regime.value, regime_info.confidence * 100, params,
        )

        # 4. ML 가중치 재훈련 (7일마다)
        if self._should_retrain(now):
            self._retrain_weights(regime_info.regime.value)

        # 5. 리포트 발송
        self._send_report(analytics, regime_info, params)

        logger.info("[SelfImprovement] ✅ 일일 사후 분석 완료")
        logger.info("=" * 60)

    def _auto_disable_strategies(self, analytics) -> None:
        """
        승률 35% 미만이고 10회 이상 거래된 전략 비활성화.
        """
        for _, row in analytics.iterrows():
            entry_reason = row.get("entry_reason", "")
            trades = int(row.get("trades", 0))
            win_rate = float(row.get("win_rate", 0))

            if entry_reason and trades >= 10 and win_rate < 35:
                if entry_reason not in self.disabled_strategies:
                    self.disabled_strategies.append(entry_reason)
                    logger.warning(
                        "[SelfImprovement] ⚠️ '%s' 전략 비활성화 (승률 %.1f%%, %d건)",
                        entry_reason, win_rate, trades,
                    )

    def _should_retrain(self, now: datetime) -> bool:
        """재학습 필요 여부 확인 (7일 경과)."""
        if self.last_retrain_date is None:
            return True
        return (now - self.last_retrain_date) > timedelta(days=7)

    def _retrain_weights(self, market_regime: str) -> None:
        """ML 팩터 가중치 재훈련."""
        if self.weight_manager is None:
            logger.info("[SelfImprovement] AdaptiveWeightManager 없음, 재학습 스킵")
            return

        try:
            # 피처 행렬 조회
            feature_df = self.db.get_feature_matrix()
            if feature_df is None or feature_df.empty or len(feature_df) < 50:
                logger.info(
                    "[SelfImprovement] 재학습 데이터 부족 (%d건 < 50건)",
                    len(feature_df) if feature_df is not None else 0,
                )
                return

            # target과 feature 분리
            targets = feature_df["target"].values
            feature_cols = [c for c in feature_df.columns if c != "target"]
            features = feature_df[feature_cols].fillna(0).values

            # 재학습
            self.weight_manager.retrain_on_trades(features, targets, market_regime)
            self.last_retrain_date = datetime.now()

            # 중요도 로깅
            importance = self.weight_manager.get_feature_importance(market_regime)
            logger.info(
                "[SelfImprovement] ✅ 팩터 중요도 (%s): %s",
                market_regime,
                {k: f"{v:.3f}" for k, v in importance.items()},
            )

        except Exception as e:
            logger.error("[SelfImprovement] 재학습 실패: %s", e)

    def _send_report(self, analytics, regime_info, params: dict) -> None:
        """일일 리포트 발송 (로그 + 설정 저장)."""
        total_trades = analytics["trades"].sum() if "trades" in analytics.columns else 0
        avg_pnl = analytics["avg_pnl_pct"].mean() if "avg_pnl_pct" in analytics.columns else 0
        strategies_active = len(analytics) if analytics is not None else 0

        report = f"""
{'='*60}
📊 RossTrader_US 일일 트레이딩 리포트
날짜: {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*60}

📈 시장 현황
  - 레짐: {regime_info.regime.value}
  - VIX: {regime_info.vix_level:.1f}
  - SPY 변동률: {regime_info.sp500_change:+.2f}%

📊 거래 성과
  - 총 거래: {total_trades}
  - 활성 전략: {strategies_active}
  - 평균 수익률: {avg_pnl*100:+.2f}%
  - 비활성화 전략: {', '.join(self.disabled_strategies) if self.disabled_strategies else '없음'}

⚙️ 다음 날 파라미터
  - 최대 포지션: {params.get('max_positions', '?')}
  - 포지션 사이즈: {params.get('position_size_mult', '?')*100:.0f}%
  - 손절 배수: {params.get('stop_loss_mult', '?')}x
  - 최대 일일 거래: {params.get('max_daily_trades', '?')}
{'='*60}
"""
        logger.info(report)

        # 설정 저장 (선택적)
        if self.config_path:
            self._save_next_day_params(params)

    def _save_next_day_params(self, params: dict) -> None:
        """다음 날 파라미터를 설정 파일에 저장."""
        try:
            import json

            if self.config_path.exists():
                with open(self.config_path, "r") as f:
                    config = json.load(f)
            else:
                config = {}

            # 트레이딩 파라미터 업데이트
            trade_config = config.get("trade", {})
            trade_config.update({
                "max_positions": params.get("max_positions", 3),
                "position_size_mult": params.get("position_size_mult", 0.7),
                "stop_loss_mult": params.get("stop_loss_mult", 1.0),
                "max_daily_trades": params.get("max_daily_trades", 10),
                "last_updated": datetime.now().isoformat(),
            })
            config["trade"] = trade_config
            config["market_regime"] = {
                "vix_params": {
                    "low_vix": params.get("position_size_mult", 0.7) >= 0.8,
                }
            }

            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)

            logger.info("[SelfImprovement] 다음 날 파라미터 저장 완료")

        except Exception as e:
            logger.warning("[SelfImprovement] 파라미터 저장 실패: %s", e)

    def is_strategy_disabled(self, strategy_name: str) -> bool:
        """전략이 비활성화되었는지 확인."""
        return strategy_name in self.disabled_strategies

    def get_disabled_strategies(self) -> List[str]:
        """비활성화된 전략 목록 반환."""
        return self.disabled_strategies.copy()

    def reset(self) -> None:
        """비활성화 전략 초기화."""
        self.disabled_strategies.clear()
        self.last_retrain_date = None
        logger.info("[SelfImprovement] 자가 개선 엔진 리셋 완료")
