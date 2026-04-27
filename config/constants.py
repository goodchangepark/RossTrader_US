"""
config/constants.py — RossTrader_US

미국 주식 매매에 특화된 상수, 팩터 가중치, 수수료 체계.
AI 없이 순수 팩터/수급 분석 기반 매매를 위한 모든 임계값 정의.
"""

from __future__ import annotations

from datetime import date, time
from typing import Dict, List, Set


# ══════════════════════════════════════════════
# 앱 정보
# ══════════════════════════════════════════════
APP_NAME: str = "RossTrader_US"
VERSION: str = "1.0.0"
AUTHOR: str = "CHANGEDEV"


# ══════════════════════════════════════════════
# 거래소 코드
# ══════════════════════════════════════════════
EXCHANGE_CODES: Dict[str, str] = {
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
    "AMEX": "AMEX",
}

# ══════════════════════════════════════════════
# 타임존
# ══════════════════════════════════════════════
TZ_NAME_KST: str = "Asia/Seoul"
TZ_NAME_ET: str = "America/New_York"

# ══════════════════════════════════════════════
# 미국 정규장 시간 (ET)
# ══════════════════════════════════════════════
REGULAR_OPEN: time = time(9, 30)
REGULAR_CLOSE: time = time(16, 0)
PRE_OPEN: time = time(4, 0)
PRE_CLOSE: time = time(9, 30)
AFTER_OPEN: time = time(16, 0)
AFTER_CLOSE: time = time(20, 0)
ORB_START: time = time(9, 30)
ORB_END: time = time(10, 30)
FORCE_FLAT_TIME: time = time(15, 50)

# ══════════════════════════════════════════════
# 미국 휴장일 (2025~2026, ET 기준)
# ══════════════════════════════════════════════
US_HOLIDAYS_2025_2026: Set[date] = {
    date(2025, 1, 1),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 4, 18),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 12, 25),
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
}

# ══════════════════════════════════════════════
# 서킷브레이커 (S&P500 기준)
# ══════════════════════════════════════════════
CIRCUIT_BREAKER: Dict[str, float] = {
    "LEVEL_1": -7.0,
    "LEVEL_2": -13.0,
    "LEVEL_3": -20.0,
}

# ══════════════════════════════════════════════
# 수수료 체계 (2026년 기준 실제값)
# ══════════════════════════════════════════════

class USCommission:
    """
    미국 주식 실제 수수료 구조.
    KIS 해외주식 기준 + SEC/FINRA 법정 수수료.

    총 비용 = 브로커 수수료 + SEC Fee(매도만) + FINRA TAF

    사용 예:
        cost = USCommission.total_cost(10000, 10, "sell")
        print(cost["total_pct"])  # 0.0072 (0.72%)
    """

    # KIS 해외주식 수수료 (매수/매도 동일)
    KIS_RATE         = 0.0025      # 0.25% (거래대금 기준)
    KIS_MIN_USD      = 0.0         # 최소 수수료 없음

    # SEC Section 31 Fee (매도 시만 부과, FY2026 기준)
    SEC_FEE_RATE     = 0.000138    # 매도 대금의 0.0138%

    # FINRA Trading Activity Fee (TAF, 매도 시만)
    FINRA_TAF_PER_SHARE = 0.000166
    FINRA_TAF_MAX    = 8.30        # 건당 최대 $8.30

    # 환전 스프레드 (KIS 달러 환전 시, 우대 적용 가정)
    FX_SPREAD_RATE   = 0.001       # 0.1% (매수/매도 왕복 0.2%)

    @classmethod
    def total_cost(
        cls,
        notional_usd: float,
        shares: int,
        side: str,
    ) -> dict:
        """
        실제 거래 총 비용 계산.

        Args:
            notional_usd: 거래 금액 ($)
            shares:       주문 주수
            side:         "buy" or "sell"

        Returns:
            {
                "broker_fee": float,  # KIS 수수료
                "sec_fee": float,     # SEC Fee (매도만)
                "finra_taf": float,   # FINRA TAF (매도만)
                "fx_spread": float,   # 환전 비용
                "total_usd": float,   # 총 비용 (달러)
                "total_pct": float,   # 총 비용률 (%)
            }
        """
        broker_fee = notional_usd * cls.KIS_RATE

        sec_fee   = 0.0
        finra_taf = 0.0

        if side == "sell":
            sec_fee   = notional_usd * cls.SEC_FEE_RATE
            finra_taf = min(shares * cls.FINRA_TAF_PER_SHARE, cls.FINRA_TAF_MAX)

        fx_spread = notional_usd * cls.FX_SPREAD_RATE
        total_usd = broker_fee + sec_fee + finra_taf + fx_spread
        total_pct = total_usd / notional_usd if notional_usd > 0 else 0

        return {
            "broker_fee": round(broker_fee, 4),
            "sec_fee":    round(sec_fee, 6),
            "finra_taf":  round(finra_taf, 4),
            "fx_spread":  round(fx_spread, 4),
            "total_usd":  round(total_usd, 4),
            "total_pct":  round(total_pct, 6),
        }

    @classmethod
    def roundtrip_cost_pct(cls, notional_usd: float, shares: int) -> float:
        """왕복 거래 총 비용률 (손익분기점 계산용)."""
        buy  = cls.total_cost(notional_usd, shares, "buy")
        sell = cls.total_cost(notional_usd, shares, "sell")
        return buy["total_pct"] + sell["total_pct"]

    @classmethod
    def min_profit_pct(cls, notional_usd: float, shares: int) -> float:
        """손익분기점 수익률 (50% 버퍼 포함)."""
        return cls.roundtrip_cost_pct(notional_usd, shares) * 1.5


# ══════════════════════════════════════════════
# 팩터 가중치 (Factor Weights)
# ══════════════════════════════════════════════

class FactorWeights:
    """
    종목 스코어링에 사용하는 팩터별 가중치. 합계 = 100점.

    설계 원칙:
    - 수급(Volume/Flow): 40점 → 단기 모멘텀의 핵심
    - 가격 모멘텀:       30점 → 추세 확인
    - 뉴스 촉매:        20점 → 이벤트 드리븐
    - 기술적:          10점 → 진입 타이밍 보조
    """

    # 수급 팩터 (40점)
    RVOL_WEIGHT            = 15   # Relative Volume
    OBI_WEIGHT             = 12   # Order Book Imbalance
    DOLLAR_VOLUME_WEIGHT   = 8    # 달러 거래대금
    FLOAT_ROTATION_WEIGHT  = 5    # Float 회전율

    # 가격 모멘텀 팩터 (30점)
    INTRADAY_MOMENTUM_WEIGHT = 12  # 당일 모멘텀
    GAP_SIZE_WEIGHT          = 10  # 갭 크기
    VWAP_POSITION_WEIGHT     = 8   # VWAP 대비 위치

    # 뉴스/이벤트 팩터 (20점)
    NEWS_SENTIMENT_WEIGHT    = 10  # 뉴스 감성 점수
    EVENT_TYPE_WEIGHT        = 6   # 이벤트 유형 중요도
    NEWS_FRESHNESS_WEIGHT    = 4   # 뉴스 신선도

    # 기술적 팩터 (10점)
    RSI_WEIGHT               = 4   # RSI 과매도/과매수
    ATR_WEIGHT               = 3   # ATR 기반 변동성
    SUPPORT_WEIGHT           = 3   # 지지선 근접도


# ══════════════════════════════════════════════
# 수급 스코어 임계값
# ══════════════════════════════════════════════

class SupplyDemandThresholds:
    """수급 분석 임계값."""

    # RVOL: 현재 거래량 / 동일 시간대 20일 평균 거래량
    RVOL_WEAK      = 1.5
    RVOL_MODERATE  = 2.5
    RVOL_STRONG    = 5.0
    RVOL_EXPLOSIVE = 10.0

    # OBI (Order Book Imbalance)
    OBI_BEARISH      = 0.35
    OBI_NEUTRAL_LOW  = 0.45
    OBI_NEUTRAL_HIGH = 0.55
    OBI_BULLISH      = 0.65

    # Float Rotation
    FLOAT_LOW      = 0.05
    FLOAT_MODERATE = 0.15
    FLOAT_HIGH     = 0.30
    FLOAT_EXTREME  = 0.50


# ══════════════════════════════════════════════
# 진입 조건 (Entry Criteria)
# ══════════════════════════════════════════════

class EntryConditions:
    """매매 진입 기준값."""

    # 최소 진입 스코어 (100점 만점)
    MIN_SCORE_WEAK   = 55
    MIN_SCORE_NORMAL = 65
    MIN_SCORE_STRONG = 78

    # 갭 조건
    GAP_MIN_PCT           = 0.03
    GAP_MAX_PCT           = 0.50
    GAP_SWEET_SPOT_LOW    = 0.05
    GAP_SWEET_SPOT_HIGH   = 0.25

    # ORB 조건 (ET 9:30~10:30)
    ORB_BREAKOUT_CONFIRM = 1.005
    ORB_VOLUME_CONFIRM   = 1.5

    # 가격 조건
    MIN_PRICE_USD     = 1.0
    MAX_PRICE_USD     = 500.0
    MIN_DOLLAR_VOLUME = 500_000

    # VWAP 조건
    VWAP_MAX_DISTANCE = 0.03

    # 손익분기점 고려 최소 목표 수익
    MIN_REWARD_PCT = 0.015


# ══════════════════════════════════════════════
# 청산 조건 (Exit Criteria) — 수수료 반영
# ══════════════════════════════════════════════

class ExitConditions:
    """
    청산 조건. 모든 수익/손실 기준은 수수료 반영 후 실질 기준.
    KIS 수수료 0.25% 왕복 + SEC/FINRA 합산 약 0.72% 고려.
    """

    # Stop Loss
    STOP_LOSS_TIGHT  = 0.015
    STOP_LOSS_NORMAL = 0.020
    STOP_LOSS_WIDE   = 0.030

    # Take Profit (단계별)
    TAKE_PROFIT_1    = 0.020   # 1차 목표: 2.0% (실질 1.28%)
    TAKE_PROFIT_2    = 0.035   # 2차 목표: 3.5%
    TAKE_PROFIT_3    = 0.060   # 3차 목표: 6.0%

    # 부분 청산 비율
    PARTIAL_EXIT_1_PCT = 0.50  # 1차: 50% 청산
    PARTIAL_EXIT_2_PCT = 0.30  # 2차: 추가 30% 청산
    RUNNER_PCT         = 0.20  # 마지막 20% Runner 유지

    # 가속형 Trailing Stop
    TRAILING_INITIAL   = 0.015  # 초기 트레일 1.5%
    TRAILING_TIGHTEN_1 = 0.010  # 수익 3% 초과 시 1.0%
    TRAILING_TIGHTEN_2 = 0.007  # 수익 5% 초과 시 0.7%

    # Time Stop (ET 기준)
    MAX_HOLD_MINUTES   = 45
    FORCE_FLAT_MINUTES_BEFORE_CLOSE = 10

    # VWAP 이탈 청산
    VWAP_FAIL_BARS     = 3

    # Break-Even 이동
    BREAKEVEN_TRIGGER  = 0.010  # 수익 1% 도달 시 손절선을 진입가로 이동


# ══════════════════════════════════════════════
# 뉴스 이벤트 유형별 가중치
# ══════════════════════════════════════════════

class USEventWeights:
    """미국 주식 이벤트 유형별 중요도 (-1.0~1.0)."""

    EVENT_WEIGHTS: Dict[str, float] = {
        # 최고 등급 (0.9~1.0)
        "earnings_beat":         1.0,
        "fda_approval":          1.0,
        "major_contract":        0.95,
        "buyout_offer":          0.95,
        "short_squeeze":         0.90,

        # 높은 등급 (0.7~0.89)
        "earnings_guidance_up":  0.85,
        "clinical_success":      0.85,
        "analyst_upgrade":       0.75,
        "strategic_partnership": 0.75,
        "stock_buyback":         0.70,

        # 중간 등급 (0.5~0.69)
        "earnings_miss":        -0.80,
        "analyst_downgrade":    -0.70,
        "guidance_cut":         -0.75,
        "dilution":             -0.80,
        "sec_investigation":    -0.90,
        "ceo_resign":           -0.65,

        # 낮은 등급 (0.3~0.49)
        "general_news":          0.40,
        "product_launch":        0.55,
        "partnership":           0.50,
    }

    @classmethod
    def get_weight(cls, event_type: str) -> float:
        return cls.EVENT_WEIGHTS.get(event_type, 0.40)


# ══════════════════════════════════════════════
# 미국 주식 부정/긍정 이벤트 키워드
# ══════════════════════════════════════════════

US_VETO_KEYWORDS: List[str] = [
    "sec investigation", "sec charges", "fraud", "accounting irregularities",
    "restatement", "class action", "delisting", "bankruptcy", "chapter 11",
    "going concern", "material weakness",
    "dilutive offering", "at-the-market offering", "reverse stock split",
    "debt restructuring", "default",
    "clinical trial failure", "fda rejection", "complete response letter",
    "trial discontinued",
]

US_POSITIVE_KEYWORDS: List[str] = [
    "beats estimates", "earnings beat", "revenue beat", "raised guidance",
    "fda approved", "fda clearance", "contract awarded", "acquisition",
    "buyout", "merger", "partnership agreement", "licensing deal",
    "share repurchase", "dividend increase", "analyst upgrade",
    "price target raised", "clinical success", "positive data",
]

# ══════════════════════════════════════════════
# 레거시 호환 (기존 코드에서 사용)
# ══════════════════════════════════════════════
EXIT_REASONS: Dict[str, str] = {
    "STOP_LOSS": "stop_loss",
    "TAKE_PROFIT": "take_profit",
    "TRAILING": "trailing_stop",
    "PARTIAL_TP": "partial_tp",
    "BREAK_EVEN": "break_even",
    "TIME_STOP": "time_stop",
    "FORCE_FLAT": "force_flat",
    "REGIME": "regime_exit",
    "VETO": "veto_exit",
    "EOD": "eod_force",
}

STRONG_EVENT_TYPES: set = {"contract", "earnings", "approval", "buyback"}

EVENT_TYPE_PATTERNS: Dict[str, List[str]] = {
    "contract":  ["contract", "agreement", "partnership", "collaboration"],
    "earnings":  ["earnings", "revenue", "profit", "quarterly", "EPS"],
    "approval":  ["approval", "authorization", "clearance", "FDA"],
    "buyback":   ["buyback", "repurchase", "share buyback"],
}

US_COMMISSION_RATE: float = 0.002
SEC_FEE_RATE: float = 0.000008
FINRA_FEE_RATE: float = 0.000145

NEWS_SOURCES: Dict[str, str] = {
    "finnhub": "Finnhub API",
    "edgar": "SEC EDGAR",
    "yahoo": "Yahoo Finance RSS",
}
