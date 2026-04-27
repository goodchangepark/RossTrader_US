"""
core/risk_manager.py — RossTrader_US

리스크 관리자 (v2.0).
3단계 서킷브레이커 + 상관관계 리스크 + 켈리 포지션 사이징 연동.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)


class CircuitBreakerLevel:
    """서킷브레이커 레벨."""
    NORMAL = "NORMAL"
    HALF_SIZE = "HALF_SIZE"        # Level 1: 포지션 50% 감소
    NO_NEW_ENTRY = "NO_NEW_ENTRY"  # Level 2: 신규 진입 중단
    KILL_SWITCH = "KILL_SWITCH"    # Level 3: 전량 청산


@dataclass
class RiskCheckResult:
    """리스크 체크 결과."""
    passed: bool
    reason: str = ""
    details: dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class RiskManager:
    """
    리스크 관리자 (v2.0).
    3단계 서킷브레이커 + 상관관계 체크 + 일일 리스크 관리.
    """

    def __init__(self):
        self.max_order_usd = settings.us.max_order_usd
        self.max_positions = settings.max_positions
        self.daily_loss_limit_pct = 5.0      # 일일 최대 손실 5%
        self.daily_loss_limit_usd = 50.0     # 일일 최대 손실 금액 ($)
        self.kill_switch_engaged = False
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.max_daily_trades = 20
        self.peak_portfolio_value: float = 0.0
        self.current_portfolio_value: float = 0.0
        self.circuit_breaker_level: str = CircuitBreakerLevel.NORMAL

        # 포지션별 수익률 기록 (상관관계 분석용)
        self._position_returns: Dict[str, List[float]] = {}

        logger.info("[RiskManager] v2.0 초기화 완료 | max_order=$%.0f | max_pos=%d",
                     self.max_order_usd, self.max_positions)

    def pre_trade_check(
        self,
        ticker: str,
        qty: int,
        estimated_price: float,
        current_positions: int,
    ) -> RiskCheckResult:
        """사전 거래 리스크 체크."""
        # 1. 킬스위치
        if self.kill_switch_engaged:
            return RiskCheckResult(False, "킬스위치 활성화됨")

        # 2. 서킷브레이커 레벨 체크
        if self.circuit_breaker_level == CircuitBreakerLevel.NO_NEW_ENTRY:
            return RiskCheckResult(False, "서킷브레이커 Level 2: 신규 진입 중단")
        if self.circuit_breaker_level == CircuitBreakerLevel.KILL_SWITCH:
            return RiskCheckResult(False, "서킷브레이커 Level 3: Kill Switch 활성화")

        # 3. 일일 거래 횟수
        if self.daily_trade_count >= self.max_daily_trades:
            return RiskCheckResult(False, f"일일 거래 횟수 초과 ({self.daily_trade_count}/{self.max_daily_trades})")

        # 4. 일일 손실 한도
        if abs(self.daily_pnl) >= self.daily_loss_limit_usd:
            return RiskCheckResult(False, f"일일 손실 한도 도달 (${self.daily_pnl:.2f})")

        # 5. 주문 금액 한도
        order_value = qty * estimated_price
        if order_value > self.max_order_usd:
            return RiskCheckResult(
                False,
                f"주문 금액 초과: ${order_value:.2f} > ${self.max_order_usd:.2f}",
            )

        # 6. 최대 포지션 수
        if current_positions >= self.max_positions:
            return RiskCheckResult(
                False,
                f"최대 포지션 수 초과 ({current_positions}/{self.max_positions})",
            )

        return RiskCheckResult(True, "리스크 체크 통과")

    def update_daily_pnl(self, pnl_change: float) -> None:
        """일일 PnL 업데이트 + 서킷브레이커 체크."""
        self.daily_pnl += pnl_change
        self.daily_trade_count += 1
        logger.info("[RiskManager] 일일 PnL: $%.2f | 거래횟수: %d",
                     self.daily_pnl, self.daily_trade_count)

        # 3단계 서킷브레이커
        self._check_circuit_breaker(pnl_change)

    def update_portfolio_value(self, current_value: float):
        """포트폴리오 가치 업데이트 (서킷브레이커용)."""
        self.current_portfolio_value = current_value
        if current_value > self.peak_portfolio_value:
            self.peak_portfolio_value = current_value

    def _check_circuit_breaker(self, pnl_change: float):
        """
        3단계 서킷브레이커 체크.
        Level 1: 일일 -1.5% → 포지션 사이즈 50% 감소
        Level 2: 일일 -2.5% → 신규 진입 중단
        Level 3: 일일 -4.0% → 전량 청산 + Kill Switch
        """
        peak = self.peak_portfolio_value or 1000.0
        daily_loss_pct = self.daily_pnl / peak
        drawdown_pct = ((self.current_portfolio_value - peak) / peak) if peak > 0 else 0

        # Level 3: 일일 -4.0% 또는 최대손실 -8.0%
        if daily_loss_pct < -0.04 or drawdown_pct < -0.08:
            self.circuit_breaker_level = CircuitBreakerLevel.KILL_SWITCH
            self.engage_kill_switch(
                f"서킷브레이커 Level 3 | 일일 {daily_loss_pct*100:.1f}% | "
                f"DD {drawdown_pct*100:.1f}%"
            )
            return

        # Level 2: 일일 -2.5%
        if daily_loss_pct < -0.025:
            self.circuit_breaker_level = CircuitBreakerLevel.NO_NEW_ENTRY
            logger.warning(
                "[RiskManager] ⚠️ 서킷브레이커 Level 2: 신규 진입 중단 (일일 %.1f%%)",
                daily_loss_pct * 100,
            )
            return

        # Level 1: 일일 -1.5%
        if daily_loss_pct < -0.015:
            self.circuit_breaker_level = CircuitBreakerLevel.HALF_SIZE
            logger.warning(
                "[RiskManager] ⚠️ 서킷브레이커 Level 1: 포지션 사이즈 50%% 감소 (일일 %.1f%%)",
                daily_loss_pct * 100,
            )
            return

        # 정상
        self.circuit_breaker_level = CircuitBreakerLevel.NORMAL

    def get_position_size_multiplier(self) -> float:
        """서킷브레이커 레벨에 따른 포지션 사이즈 배수 반환."""
        multipliers = {
            CircuitBreakerLevel.NORMAL: 1.0,
            CircuitBreakerLevel.HALF_SIZE: 0.5,
            CircuitBreakerLevel.NO_NEW_ENTRY: 0.0,
            CircuitBreakerLevel.KILL_SWITCH: 0.0,
        }
        return multipliers.get(self.circuit_breaker_level, 1.0)

    def kelly_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        capital: float,
    ) -> float:
        """
        켈리 기준 포지션 사이징.
        Half Kelly 사용 (실전 표준, Full Kelly는 너무 공격적).

        공식: f* = (bp - q) / b
        b = avg_win/avg_loss, p = win_rate, q = 1-p
        """
        if avg_loss == 0 or win_rate == 0 or win_rate == 1:
            return 0.0

        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p
        full_kelly = (b * p - q) / b

        if full_kelly <= 0:
            return 0.0  # 기대값 음수 → 진입 불가

        half_kelly = full_kelly * 0.5  # Half Kelly (안전)
        max_pct = 0.05  # 단일 종목 최대 5%

        # 서킷브레이커 레벨 반영
        cb_mult = self.get_position_size_multiplier()
        kelly_pct = max(0, min(half_kelly * cb_mult, max_pct))
        return capital * kelly_pct

    # ══════════════════════════════════════════════
    # 상관관계 리스크 (Correlation Risk)
    # ══════════════════════════════════════════════

    def record_position_return(self, symbol: str, return_pct: float):
        """포지션 일일 수익률 기록 (상관관계 분석용)."""
        if symbol not in self._position_returns:
            self._position_returns[symbol] = []
        self._position_returns[symbol].append(return_pct)
        # 최근 20개만 유지
        if len(self._position_returns[symbol]) > 20:
            self._position_returns[symbol] = self._position_returns[symbol][-20:]

    def portfolio_correlation_check(
        self,
        new_symbol: str,
        current_positions: List[Dict[str, Any]],
    ) -> bool:
        """
        신규 진입 종목이 기존 포지션과 상관관계 > 0.7이면 진입 거부.
        같은 섹터에 과집중 방지.
        """
        if not current_positions:
            return True  # 포지션 없으면 허용

        new_returns = self._position_returns.get(new_symbol, [])
        if len(new_returns) < 5:
            return True  # 데이터 부족 → 허용

        for pos in current_positions:
            existing_returns = self._position_returns.get(pos["symbol"], [])
            if len(existing_returns) < 5:
                continue

            # 상관관계 계산
            min_len = min(len(new_returns), len(existing_returns))
            corr = np.corrcoef(new_returns[-min_len:], existing_returns[-min_len:])[0, 1]

            if corr > 0.70:
                logger.warning(
                    "[RiskManager] 상관관계 초과 거부: %s vs %s (r=%.2f)",
                    new_symbol, pos["symbol"], corr,
                )
                return False  # 상관관계 높음 → 진입 거부

        return True

    # ══════════════════════════════════════════════

    def engage_kill_switch(self, reason: str) -> None:
        """킬스위치 작동."""
        self.kill_switch_engaged = True
        logger.critical("[RiskManager] 🛑 킬스위치 작동! 사유: %s", reason)

    def release_kill_switch(self) -> None:
        """킬스위치 해제."""
        self.kill_switch_engaged = False
        self.circuit_breaker_level = CircuitBreakerLevel.NORMAL
        logger.info("[RiskManager] 킬스위치 해제")

    def reset_daily(self) -> None:
        """일일 카운터 리셋."""
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.circuit_breaker_level = CircuitBreakerLevel.NORMAL
        logger.info("[RiskManager] 일일 카운터 리셋")

    def get_status(self) -> dict:
        """리스크 상태 요약."""
        return {
            "kill_switch": self.kill_switch_engaged,
            "circuit_breaker": self.circuit_breaker_level,
            "daily_pnl": self.daily_pnl,
            "daily_trade_count": self.daily_trade_count,
            "max_daily_trades": self.max_daily_trades,
            "max_order_usd": self.max_order_usd,
            "max_positions": self.max_positions,
            "size_multiplier": self.get_position_size_multiplier(),
        }
