"""
core/market_regime.py — RossTrader_US

시장 레짐 감지.
S&P500/VIX 기반 상승/하락/변동성 국면 감지.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """시장 레짐."""
    BULL = "bull"               # 상승장
    BEAR = "bear"              # 하락장
    HIGH_VOLATILITY = "high_vol"  # 고변동성
    LOW_VOLATILITY = "low_vol"   # 저변동성
    RANGE = "range"            # 횡보장
    UNKNOWN = "unknown"        # 알 수 없음


@dataclass
class RegimeInfo:
    """레짐 정보."""
    regime: MarketRegime
    sp500_change: float = 0.0
    vix_level: float = 0.0
    confidence: float = 0.0


class MarketRegimeDetector:
    """
    시장 레짐 감지기.
    S&P500 일간 변동률 + VIX 지수 기준.
    """

    def __init__(self):
        # VIX 기준: 20 이하 = 낮음, 20~30 = 중간, 30 이상 = 높음
        self.vix_low_threshold = 20.0
        self.vix_high_threshold = 30.0

        # S&P500 일간 변동률 기준
        self.bull_threshold = 0.5    # 0.5% 이상 상승
        self.bear_threshold = -0.5   # -0.5% 이상 하락

    def detect(self, sp500_change_pct: float = 0.0, vix_level: float = 15.0) -> RegimeInfo:
        """
        현재 시장 레짐 감지.

        Args:
            sp500_change_pct: S&P500 일간 변동률 (%)
            vix_level: 현재 VIX 지수

        Returns:
            RegimeInfo
        """
        regime = MarketRegime.UNKNOWN
        confidence = 0.5

        # VIX 기준
        if vix_level >= self.vix_high_threshold:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = min(0.9, 0.5 + (vix_level - self.vix_high_threshold) / 50.0)
        elif vix_level <= self.vix_low_threshold:
            regime = MarketRegime.LOW_VOLATILITY
            confidence = 0.7
        else:
            regime = MarketRegime.RANGE
            confidence = 0.5

        # S&P500 변동률 기준 (VIX보다 우선)
        if sp500_change_pct >= self.bull_threshold:
            if vix_level < self.vix_high_threshold:
                regime = MarketRegime.BULL
                confidence = min(0.9, 0.5 + abs(sp500_change_pct) / 2.0)
        elif sp500_change_pct <= self.bear_threshold:
            if vix_level > self.vix_low_threshold:
                regime = MarketRegime.BEAR
                confidence = min(0.9, 0.5 + abs(sp500_change_pct) / 2.0)

        return RegimeInfo(
            regime=regime,
            sp500_change=sp500_change_pct,
            vix_level=vix_level,
            confidence=confidence,
        )

    def is_tradeable(self, regime: MarketRegime) -> bool:
        """트레이딩 가능 레짐인지 확인."""
        return regime not in (MarketRegime.HIGH_VOLATILITY, MarketRegime.BEAR)
