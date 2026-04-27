"""
core/signal_pipeline.py — RossTrader_US

시그널 파이프라인 (6단계 + 팩터 스코어링 연동).
: 팩터 엔진 → 포지션 사이저 → 리스크 체크 통합 파이프라인.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config.constants import EntryConditions as EC
from core.factor_engine import FactorEngine, FactorScore, MarketData, NewsData
from core.position_sizer import PositionSizer, PositionSizeResult

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    """시그널 방향."""
    NONE = "none"
    LONG = "long"
    SHORT = "short"
    EXIT = "exit"


@dataclass
class Signal:
    """트레이딩 시그널."""
    ticker: str
    direction: SignalDirection
    confidence: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    factor_score: Optional[FactorScore] = None
    size_result: Optional[PositionSizeResult] = None


class PipelineStage(Enum):
    """파이프라인 단계."""
    COLLECT = "collect"
    SCORE = "score"
    FILTER = "filter"
    RANK = "rank"
    VALIDATE = "validate"
    SIZE = "size"             # 포지션 사이징 단계 (신규)
    VETO = "veto"


SignalProcessor = Callable[[List[Signal]], List[Signal]]


class SignalPipeline:
    """
    7단계 시그널 파이프라인 (팩터 + 사이징 연동).

    단계:
    1. COLLECT: 여러 전략에서 시그널 수집
    2. SCORE: 팩터 스코어 계산 (FactorEngine 연동)
    3. FILTER: 저품질 시그널 제거
    4. RANK: 순위화
    5. VALIDATE: 가격/볼륨 검증
    6. SIZE: 포지션 사이징 (PositionSizer 연동)
    7. VETO: 부정 이벤트 차단
    """

    def __init__(self):
        self.stages: Dict[PipelineStage, SignalProcessor] = {}
        self.factor_engine = FactorEngine()
        self.position_sizer: Optional[PositionSizer] = None
        logger.info("[SignalPipeline] 초기화 완료 (팩터 + 사이징 연동)")

    def register_stage(self, stage: PipelineStage, processor: SignalProcessor) -> None:
        """특정 단계에 프로세서 등록."""
        self.stages[stage] = processor
        logger.info("[SignalPipeline] Stage 등록: %s", stage.value)

    def set_position_sizer(self, sizer: PositionSizer) -> None:
        """포지션 사이저 설정."""
        self.position_sizer = sizer
        logger.info("[SignalPipeline] PositionSizer 연결 완료")

    def process(self, signals: List[Signal]) -> List[Signal]:
        """파이프라인 실행."""
        current = signals[:]

        for stage in PipelineStage:
            if stage in self.stages:
                try:
                    current = self.stages[stage](current)
                    logger.debug("[SignalPipeline] Stage %s 완료 | 시그널: %d개",
                                 stage.value, len(current))
                except Exception as e:
                    logger.error("[SignalPipeline] Stage %s 실패: %s", stage.value, e)
                    return []

        return current

    def evaluate_with_factors(
        self,
        ticker: str,
        market_data: MarketData,
        news_data: Optional[NewsData] = None,
    ) -> Signal:
        """
        팩터 스코어링으로 단일 종목 평가.

        Returns:
            Signal with factor_score, size_result 포함
        """
        if news_data is None:
            news_data = NewsData()

        # FactorEngine으로 스코어 계산
        fs = self.factor_engine.score(market_data, news_data)

        sig = Signal(
            ticker=ticker,
            direction=SignalDirection.LONG if not fs.disqualified else SignalDirection.NONE,
            confidence=fs.total_score / 100.0 if not fs.disqualified else 0.0,
            entry_price=market_data.price,
            factor_score=fs,
            reason=(
                f"팩터스코어 {fs.total_score:.1f}/{fs.signal_strength}"
                + (f" | 탈락: {fs.disqualify_reason}" if fs.disqualified else "")
            ),
        )

        # 포지션 사이징 (viable일 때만)
        if not fs.disqualified and self.position_sizer and fs.total_score >= EC.MIN_SCORE_WEAK:
            result = self.position_sizer.calculate(
                price=market_data.price,
                factor_score=fs,
            )
            sig.size_result = result
            if result.viable:
                sig.stop_loss = market_data.price * (1 - result.roundtrip_cost_pct * 2)
                sig.take_profit = market_data.price * (1 + result.breakeven_pct * 2)
                sig.reason += f" | {result.shares}주 ${result.notional_usd:.0f} (RR={result.reward_risk_ratio})"

        return sig

    def execute(self, signals: List[Signal]) -> List[Signal]:
        """파이프라인 실행 (process alias)."""
        return self.process(signals)


# ── 기본 필터 함수 ──────────────────────────

def default_score_filter(signals: List[Signal], min_confidence: float = 0.3) -> List[Signal]:
    """기본 신뢰도 필터."""
    return [s for s in signals if s.confidence >= min_confidence]


def default_veto_filter(signals: List[Signal]) -> List[Signal]:
    """기본 Veto 필터."""
    return signals


def default_rank_filter(signals: List[Signal], max_signals: int = 5) -> List[Signal]:
    """상위 N개 시그널만 유지."""
    sorted_sigs = sorted(signals, key=lambda s: s.confidence, reverse=True)
    return sorted_sigs[:max_signals]
