"""
core/factor_engine.py — RossTrader_US

멀티팩터 스코어링 엔진 (AI 없음).
수급(40) + 모멘텀(30) + 뉴스(20) + 기술적(10) = 100점

이 파일이 RossTrader_US의 핵심 알파 생성기.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.constants import (
    FactorWeights as FW,
    SupplyDemandThresholds as SDT,
    EntryConditions as EC,
    USEventWeights,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 팩터 입력 데이터
# ══════════════════════════════════════════════

@dataclass
class MarketData:
    """실시간 시장 데이터 스냅샷."""
    ticker: str
    price: float              # 현재가 ($)
    prev_close: float         # 전일 종가
    open_price: float         # 당일 시가
    vwap: float               # VWAP
    high: float               # 당일 고가
    low: float                # 당일 저가
    volume: int               # 당일 누적 거래량
    avg_volume_20d: int       # 20일 평균 거래량 (동일 시간대)
    shares_float: int         # 유통주식수 (Float)
    bid: float = 0.0          # 매수 1호가
    ask: float = 0.0          # 매도 1호가
    bid_size: int = 0         # 매수 호가 잔량
    ask_size: int = 0         # 매도 호가 잔량
    atr_14: float = 0.0       # ATR(14)
    rsi_14: float = 50.0      # RSI(14)
    short_interest_pct: float = 0.0
    market_cap_usd: float = 0.0
    minutes_since_open: int = 0


@dataclass
class NewsData:
    """뉴스/이벤트 데이터."""
    has_news: bool = False
    sentiment_score: float = 50.0    # 0~100
    event_type: str = "general"
    freshness_seconds: float = 999.0
    headline: str = ""
    is_edgar: bool = False


@dataclass
class FactorScore:
    """팩터별 세부 점수 및 최종 합계."""
    ticker: str

    # 수급 팩터 (40점)
    rvol_score: float = 0.0
    obi_score: float = 0.0
    dollar_volume_score: float = 0.0
    float_rotation_score: float = 0.0
    supply_demand_total: float = 0.0

    # 모멘텀 팩터 (30점)
    intraday_momentum_score: float = 0.0
    gap_score: float = 0.0
    vwap_position_score: float = 0.0
    momentum_total: float = 0.0

    # 뉴스 팩터 (20점)
    news_sentiment_score: float = 0.0
    event_type_score: float = 0.0
    freshness_score: float = 0.0
    news_total: float = 0.0

    # 기술적 팩터 (10점)
    rsi_score: float = 0.0
    atr_score: float = 0.0
    support_score: float = 0.0
    technical_total: float = 0.0

    # 최종
    total_score: float = 0.0
    signal_strength: str = "NONE"   # NONE/WEAK/NORMAL/STRONG

    # 메타
    gap_pct: float = 0.0
    rvol: float = 0.0
    obi: float = 0.0
    float_rotation: float = 0.0
    vwap_distance_pct: float = 0.0
    spread_pct: float = 0.0

    # 패스/실패 사유
    disqualified: bool = False
    disqualify_reason: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ══════════════════════════════════════════════
# 팩터 엔진
# ══════════════════════════════════════════════

class FactorEngine:
    """
    멀티팩터 스코어링 엔진.

    사용 예:
        engine = FactorEngine()
        score  = engine.score(market_data, news_data)
        if score.total_score >= 65 and not score.disqualified:
            # 진입 신호
    """

    def score(self, md: MarketData, nd: NewsData | None = None) -> FactorScore:
        """전체 팩터 스코어 계산."""
        if nd is None:
            nd = NewsData()

        fs = FactorScore(ticker=md.ticker)

        # 0. 사전 자격 검사
        if not self._prequalify(md, fs):
            return fs

        # 핵심 지표 계산
        fs.gap_pct         = self._gap_pct(md)
        fs.rvol            = self._rvol(md)
        fs.obi             = self._obi(md)
        fs.float_rotation  = self._float_rotation(md)
        fs.spread_pct      = self._spread_pct(md)
        fs.vwap_distance_pct = self._vwap_distance_pct(md)

        # 팩터별 점수
        self._score_supply_demand(md, fs)
        self._score_momentum(md, fs)
        self._score_news(nd, fs)
        self._score_technical(md, fs)

        # 합산
        fs.total_score = (
            fs.supply_demand_total
            + fs.momentum_total
            + fs.news_total
            + fs.technical_total
        )
        fs.total_score = round(min(100.0, max(0.0, fs.total_score)), 2)

        # 신호 강도 분류
        fs.signal_strength = self._classify_signal(fs.total_score)

        return fs

    # ── 사전 자격 검사 ────────────────────────

    def _prequalify(self, md: MarketData, fs: FactorScore) -> bool:
        """기본 자격 미달 시 즉시 탈락."""

        if md.price < EC.MIN_PRICE_USD:
            _reject(fs, f"가격 미달 ${md.price:.2f} < ${EC.MIN_PRICE_USD}")
            return False

        if md.price > EC.MAX_PRICE_USD:
            _reject(fs, f"가격 초과 ${md.price:.2f} > ${EC.MAX_PRICE_USD}")
            return False

        dollar_vol = md.price * md.volume
        if dollar_vol < EC.MIN_DOLLAR_VOLUME:
            _reject(fs, f"거래대금 부족 ${dollar_vol:,.0f} < ${EC.MIN_DOLLAR_VOLUME:,.0f}")
            return False

        spread = self._spread_pct(md)
        if spread > 0.02:
            _reject(fs, f"스프레드 과다 {spread*100:.2f}%")
            return False

        return True

    # ── 수급 팩터 (40점) ──────────────────────

    def _score_supply_demand(self, md: MarketData, fs: FactorScore) -> None:
        rvol = fs.rvol

        # ① RVOL (15점)
        if rvol >= SDT.RVOL_EXPLOSIVE:
            rvol_s = 15.0
        elif rvol >= SDT.RVOL_STRONG:
            rvol_s = 12.0
        elif rvol >= SDT.RVOL_MODERATE:
            rvol_s = 8.0
        elif rvol >= SDT.RVOL_WEAK:
            rvol_s = 4.0
        else:
            rvol_s = 0.0

        # ② OBI (12점)
        obi = fs.obi
        if obi >= SDT.OBI_BULLISH:
            obi_s = 12.0
        elif obi >= SDT.OBI_NEUTRAL_HIGH:
            obi_s = 7.0
        elif obi >= SDT.OBI_NEUTRAL_LOW:
            obi_s = 4.0
        elif obi >= SDT.OBI_BEARISH:
            obi_s = 1.0
        else:
            obi_s = 0.0

        # ③ 달러 거래대금 (8점)
        dollar_vol = md.price * md.volume
        if dollar_vol >= 50_000_000:
            dvol_s = 8.0
        elif dollar_vol >= 10_000_000:
            dvol_s = 6.0
        elif dollar_vol >= 2_000_000:
            dvol_s = 4.0
        elif dollar_vol >= 500_000:
            dvol_s = 2.0
        else:
            dvol_s = 0.0

        # ④ Float 회전율 (5점)
        fr = fs.float_rotation
        if fr >= SDT.FLOAT_EXTREME:
            float_s = 2.0     # 과다 → 반전 위험
        elif fr >= SDT.FLOAT_HIGH:
            float_s = 5.0
        elif fr >= SDT.FLOAT_MODERATE:
            float_s = 3.0
        elif fr >= SDT.FLOAT_LOW:
            float_s = 1.0
        else:
            float_s = 0.0

        fs.rvol_score            = rvol_s
        fs.obi_score             = obi_s
        fs.dollar_volume_score   = dvol_s
        fs.float_rotation_score  = float_s
        fs.supply_demand_total   = rvol_s + obi_s + dvol_s + float_s

    # ── 모멘텀 팩터 (30점) ───────────────────

    def _score_momentum(self, md: MarketData, fs: FactorScore) -> None:
        # ① 당일 모멘텀 (12점)
        intraday_ret = (md.price - md.open_price) / md.open_price if md.open_price > 0 else 0
        if intraday_ret >= 0.08:
            intrad_s = 12.0
        elif intraday_ret >= 0.05:
            intrad_s = 9.0
        elif intraday_ret >= 0.03:
            intrad_s = 6.0
        elif intraday_ret >= 0.01:
            intrad_s = 3.0
        elif intraday_ret >= 0:
            intrad_s = 1.0
        else:
            intrad_s = 0.0

        # ② 갭 점수 (10점)
        gap = fs.gap_pct
        if EC.GAP_SWEET_SPOT_LOW <= gap <= EC.GAP_SWEET_SPOT_HIGH:
            gap_s = 10.0
        elif gap >= EC.GAP_MIN_PCT:
            gap_s = 5.0
        elif gap <= -0.03:
            gap_s = 0.0
        else:
            gap_s = 2.0

        # ③ VWAP 위치 (8점)
        vwap_dist = fs.vwap_distance_pct
        if 0 <= vwap_dist <= 0.01:
            vwap_s = 8.0
        elif 0.01 < vwap_dist <= 0.02:
            vwap_s = 6.0
        elif 0.02 < vwap_dist <= 0.03:
            vwap_s = 4.0
        elif vwap_dist > 0.03:
            vwap_s = 1.0
        else:
            vwap_s = 0.0

        fs.intraday_momentum_score = intrad_s
        fs.gap_score               = gap_s
        fs.vwap_position_score     = vwap_s
        fs.momentum_total          = intrad_s + gap_s + vwap_s

    # ── 뉴스 팩터 (20점) ──────────────────────

    def _score_news(self, nd: NewsData, fs: FactorScore) -> None:
        if not nd.has_news:
            fs.news_total = 0.0
            return

        # ① 감성 점수 (10점)
        sent = nd.sentiment_score
        if sent >= 75:
            sent_s = 10.0
        elif sent >= 60:
            sent_s = 7.0
        elif sent >= 50:
            sent_s = 4.0
        elif sent >= 40:
            sent_s = 1.0
        else:
            sent_s = 0.0

        # ② 이벤트 유형 점수 (6점)
        event_weight = USEventWeights.get_weight(nd.event_type)
        event_s = 6.0 * max(0.0, event_weight)
        if nd.is_edgar:
            event_s = min(6.0, event_s * 1.2)

        # ③ 신선도 점수 (4점)
        freshness = nd.freshness_seconds
        if freshness <= 60:
            fresh_s = 4.0
        elif freshness <= 300:
            fresh_s = 3.0
        elif freshness <= 900:
            fresh_s = 2.0
        elif freshness <= 1800:
            fresh_s = 1.0
        else:
            fresh_s = 0.0

        fs.news_sentiment_score = sent_s
        fs.event_type_score     = event_s
        fs.freshness_score      = fresh_s
        fs.news_total           = sent_s + event_s + fresh_s

    # ── 기술적 팩터 (10점) ───────────────────

    def _score_technical(self, md: MarketData, fs: FactorScore) -> None:
        # ① RSI 점수 (4점)
        rsi = md.rsi_14
        if 45 <= rsi <= 65:
            rsi_s = 4.0
        elif 35 <= rsi < 45:
            rsi_s = 2.0
        elif 65 < rsi <= 75:
            rsi_s = 2.0
        elif rsi > 75:
            rsi_s = 0.0
        else:
            rsi_s = 1.0

        # ② ATR 점수 (3점)
        if md.atr_14 > 0 and md.price > 0:
            atr_pct = md.atr_14 / md.price
            if 0.02 <= atr_pct <= 0.06:
                atr_s = 3.0
            elif 0.01 <= atr_pct < 0.02:
                atr_s = 1.5
            elif 0.06 < atr_pct <= 0.10:
                atr_s = 1.5
            else:
                atr_s = 0.0
        else:
            atr_s = 1.5

        # ③ 지지선 근접도 (3점)
        support = md.low if md.low > 0 else md.vwap * 0.98
        distance_to_support = (md.price - support) / md.price if md.price > 0 else 0
        if 0.005 <= distance_to_support <= 0.02:
            supp_s = 3.0
        elif distance_to_support <= 0.005:
            supp_s = 1.0
        else:
            supp_s = 1.5

        fs.rsi_score      = rsi_s
        fs.atr_score      = atr_s
        fs.support_score  = supp_s
        fs.technical_total = rsi_s + atr_s + supp_s

    # ── 보조 계산 함수 ─────────────────────────

    @staticmethod
    def _gap_pct(md: MarketData) -> float:
        if md.prev_close <= 0:
            return 0.0
        return (md.open_price - md.prev_close) / md.prev_close

    @staticmethod
    def _rvol(md: MarketData) -> float:
        if md.avg_volume_20d <= 0:
            return 1.0
        return md.volume / md.avg_volume_20d

    @staticmethod
    def _obi(md: MarketData) -> float:
        total = md.bid_size + md.ask_size
        if total <= 0:
            return 0.5
        return md.bid_size / total

    @staticmethod
    def _float_rotation(md: MarketData) -> float:
        if md.shares_float <= 0:
            return 0.0
        return md.volume / md.shares_float

    @staticmethod
    def _spread_pct(md: MarketData) -> float:
        if md.ask <= 0 or md.bid <= 0:
            return 0.0
        mid = (md.bid + md.ask) / 2
        return (md.ask - md.bid) / mid if mid > 0 else 0

    @staticmethod
    def _vwap_distance_pct(md: MarketData) -> float:
        if md.vwap <= 0:
            return 0.0
        return (md.price - md.vwap) / md.vwap

    @staticmethod
    def _classify_signal(score: float) -> str:
        if score >= EC.MIN_SCORE_STRONG:
            return "STRONG"
        elif score >= EC.MIN_SCORE_NORMAL:
            return "NORMAL"
        elif score >= EC.MIN_SCORE_WEAK:
            return "WEAK"
        else:
            return "NONE"


def _reject(fs: FactorScore, reason: str) -> None:
    """팩터 스코어 탈락 처리."""
    fs.disqualified = True
    fs.disqualify_reason = reason
