"""
core/entry_engine.py — RossTrader_US

진입 엔진.
팩터 스코어 연동 + ORB/Gap/모멘텀 전략 상태머신.
미국 시장 ET 9:30 기준 ORB 적용, 팩터 임계값에 따라 진입 판단.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from config.constants import EntryConditions as EC, ExitConditions as XC
from core.factor_engine import FactorEngine, FactorScore, MarketData, NewsData
from markets.us.us_session import us_session

logger = logging.getLogger(__name__)


class EntryStrategy(Enum):
    """진입 전략."""
    ORB = "orb"
    GAP = "gap"
    MOMENTUM = "momentum"
    NEWS = "news"
    FACTOR = "factor"


@dataclass
class EntrySignal:
    """진입 시그널."""
    ticker: str
    strategy: EntryStrategy
    direction: str          # "long" / "short"
    entry_price: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    factor_score: Optional[FactorScore] = None


class EntryEngine:
    """
    진입 엔진.
    ORB/Gap/모멘텀 전략 + 팩터 스코어 기반 진입.
    """

    def __init__(self):
        self.active_signals: List[EntrySignal] = []
        self.factor_engine = FactorEngine()
        logger.info("[EntryEngine] 초기화 완료 (팩터 연동)")

    def evaluate(
        self,
        ticker: str,
        market_data: MarketData,
        news_data: Optional[NewsData] = None,
    ) -> Optional[EntrySignal]:
        """
        통합 진입 평가.
        팩터 스코어를 먼저 계산하고, 조건 충족 시 진입 신호 생성.

        Args:
            ticker: 종목 코드
            market_data: 실시간 시장 데이터
            news_data: 뉴스 데이터 (선택)

        Returns:
            EntrySignal or None
        """
        if news_data is None:
            news_data = NewsData()

        # 1. 팩터 스코어 계산 (40+30+20+10 = 100점)
        fs = self.factor_engine.score(market_data, news_data)

        if fs.disqualified:
            logger.debug("[EntryEngine] %s 자격 탈락: %s", ticker, fs.disqualify_reason)
            return None

        # 2. 최소 진입 스코어 체크
        if fs.total_score < EC.MIN_SCORE_WEAK:
            logger.debug("[EntryEngine] %s 스코어 부족: %.1f < %d",
                          ticker, fs.total_score, EC.MIN_SCORE_WEAK)
            return None

        # 3. 전략별 세부 체크
        gap_pct = fs.gap_pct
        vwap_dist = fs.vwap_distance_pct
        is_orb = us_session.is_orb_period()

        strategy = EntryStrategy.FACTOR
        direction = "long"

        # ORB 기간이면 ORB 전략 우선
        if is_orb:
            orb_signal = self._check_orb_internal(ticker, market_data, fs)
            if orb_signal:
                orb_signal.factor_score = fs
                self.add_signal(orb_signal)
                return orb_signal

        # 갭이 충분히 크면 갭 전략
        if EC.GAP_SWEET_SPOT_LOW <= gap_pct <= EC.GAP_SWEET_SPOT_HIGH:
            strategy = EntryStrategy.GAP
            stop_loss = market_data.price * (1 - XC.STOP_LOSS_NORMAL)
            take_profit = market_data.price * (1 + XC.TAKE_PROFIT_2)
        else:
            # 일반 모멘텀
            strategy = EntryStrategy.MOMENTUM
            stop_loss = market_data.price * (1 - XC.STOP_LOSS_TIGHT)
            take_profit = market_data.price * (1 + XC.TAKE_PROFIT_1)

        # 4. 최소 VWAP 조건 (VWAP 위에 있어야 매수)
        if vwap_dist < -EC.VWAP_MAX_DISTANCE:
            logger.debug("[EntryEngine] %s VWAP 조건 미달: %.2f%%", ticker, vwap_dist * 100)
            return None

        entry_signal = EntrySignal(
            ticker=ticker,
            strategy=strategy,
            direction="long",
            entry_price=market_data.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=min(1.0, fs.total_score / 100.0),
            reason=(
                f"팩터스코어 {fs.total_score:.1f}/{fs.signal_strength}"
                f" | 갭 {gap_pct*100:.2f}% | RVOL {fs.rvol:.1f}x"
            ),
            factor_score=fs,
        )

        self.add_signal(entry_signal)
        return entry_signal

    def _check_orb_internal(
        self,
        ticker: str,
        md: MarketData,
        fs: FactorScore,
    ) -> Optional[EntrySignal]:
        """ORB 전략 내부 체크 (팩터 스코어 연동)."""
        if not us_session.is_orb_period():
            return None

        minutes_since = us_session.minutes_since_open()
        if minutes_since < 0 or minutes_since > 60:
            return None

        # ORB는 이미 MarketData에 포함된 첫 30분 고가/저가 기준
        # 단순화: 현재가가 당일 고가 근처이면 상향돌파로 간주
        orb_range = md.high - md.low
        if orb_range <= 0:
            return None

        # 현재가가 당일 고가의 99.5% 이상이면 상향돌파
        if md.price >= md.high * EC.ORB_BREAKOUT_CONFIRM:
            confidence = min(1.0, fs.total_score / 100.0)
            return EntrySignal(
                ticker=ticker,
                strategy=EntryStrategy.ORB,
                direction="long",
                entry_price=md.price,
                stop_loss=md.low,
                take_profit=md.price + orb_range * 1.5,
                confidence=confidence,
                reason=(
                    f"ORB 상향돌파 | 고가 ${md.high:.2f} → 현재 ${md.price:.2f}"
                    f" | 스코어 {fs.total_score:.1f}"
                ),
            )

        return None

    def check_orb(self, ticker: str, current_price: float,
                  open_price: float, high_30m: float, low_30m: float) -> Optional[EntrySignal]:
        """ORB 체크 (레거시 호환)."""
        if not us_session.is_orb_period():
            return None
        minutes_since = us_session.minutes_since_open()
        if minutes_since < 0 or minutes_since > 60:
            return None

        orb_high, orb_low = high_30m, low_30m
        orb_range = orb_high - orb_low
        if orb_range <= 0:
            return None

        if current_price > orb_high:
            return EntrySignal(
                ticker=ticker,
                strategy=EntryStrategy.ORB,
                direction="long",
                entry_price=current_price,
                stop_loss=orb_low,
                take_profit=current_price + orb_range * 1.5,
                confidence=0.7,
                reason=f"ORB 상향돌파 (고가:{orb_high:.2f} → 현재:{current_price:.2f})",
            )
        elif current_price < orb_low:
            return EntrySignal(
                ticker=ticker,
                strategy=EntryStrategy.ORB,
                direction="short",
                entry_price=current_price,
                stop_loss=orb_high,
                take_profit=current_price - orb_range * 1.5,
                confidence=0.7,
                reason=f"ORB 하향돌파 (저가:{orb_low:.2f} → 현재:{current_price:.2f})",
            )
        return None

    def check_gap(self, ticker: str, current_price: float,
                  prev_close: float) -> Optional[EntrySignal]:
        """갭 전략 체크 (레거시 호환)."""
        if prev_close <= 0:
            return None
        gap_pct = ((current_price - prev_close) / prev_close) * 100.0
        if gap_pct > 1.0:
            return EntrySignal(
                ticker=ticker, strategy=EntryStrategy.GAP,
                direction="long", entry_price=current_price,
                stop_loss=current_price * 0.98,
                take_profit=current_price * 1.03,
                confidence=0.5, reason=f"갭 상승 ({gap_pct:.2f}%)",
            )
        elif gap_pct < -1.0:
            return EntrySignal(
                ticker=ticker, strategy=EntryStrategy.GAP,
                direction="short", entry_price=current_price,
                stop_loss=current_price * 1.02,
                take_profit=current_price * 0.97,
                confidence=0.5, reason=f"갭 하락 ({gap_pct:.2f}%)",
            )
        return None

    def add_signal(self, signal: EntrySignal) -> None:
        """진입 시그널 추가."""
        self.active_signals.append(signal)
        logger.info(
            "[EntryEngine] 시그널 추가 | %s %s %s @ $%.2f (conf=%.2f, score=%.1f)",
            signal.ticker, signal.strategy.value, signal.direction,
            signal.entry_price, signal.confidence,
            signal.factor_score.total_score if signal.factor_score else 0,
        )

    def clear_signals(self) -> None:
        """시그널 초기화."""
        self.active_signals.clear()
