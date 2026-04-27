"""
core/risk_manager.py — RossTrader_US

리스크 관리자.
VaR/킬스위치/사전 리스크 체크 (미국 시장 파라미터 적용).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


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
    리스크 관리자.
    VaR/킬스위치/주문 한도/일일 손실한도 관리.
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

        logger.info("[RiskManager] 초기화 완료 | max_order=$%.0f | max_pos=%d",
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

        # 2. 일일 거래 횟수
        if self.daily_trade_count >= self.max_daily_trades:
            return RiskCheckResult(False, f"일일 거래 횟수 초과 ({self.daily_trade_count}/{self.max_daily_trades})")

        # 3. 일일 손실 한도
        if abs(self.daily_pnl) >= self.daily_loss_limit_usd:
            return RiskCheckResult(False, f"일일 손실 한도 도달 (${self.daily_pnl:.2f})")

        # 4. 주문 금액 한도
        order_value = qty * estimated_price
        if order_value > self.max_order_usd:
            return RiskCheckResult(
                False,
                f"주문 금액 초과: ${order_value:.2f} > ${self.max_order_usd:.2f}",
            )

        # 5. 최대 포지션 수
        if current_positions >= self.max_positions:
            return RiskCheckResult(
                False,
                f"최대 포지션 수 초과 ({current_positions}/{self.max_positions})",
            )

        return RiskCheckResult(True, "리스크 체크 통과")

    def update_daily_pnl(self, pnl_change: float) -> None:
        """일일 PnL 업데이트."""
        self.daily_pnl += pnl_change
        self.daily_trade_count += 1
        logger.info("[RiskManager] 일일 PnL: $%.2f | 거래횟수: %d",
                     self.daily_pnl, self.daily_trade_count)

        # 일일 손실 한도 체크
        if abs(self.daily_pnl) >= self.daily_loss_limit_usd:
            logger.warning("[RiskManager] 일일 손실 한도 도달! 킬스위치 작동!")
            self.engage_kill_switch("일일 손실 한도 초과")

    def engage_kill_switch(self, reason: str) -> None:
        """킬스위치 작동."""
        self.kill_switch_engaged = True
        logger.critical("[RiskManager] 🛑 킬스위치 작동! 사유: %s", reason)

    def release_kill_switch(self) -> None:
        """킬스위치 해제."""
        self.kill_switch_engaged = False
        logger.info("[RiskManager] 킬스위치 해제")

    def reset_daily(self) -> None:
        """일일 카운터 리셋."""
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        logger.info("[RiskManager] 일일 카운터 리셋")

    def get_status(self) -> dict:
        """리스크 상태 요약."""
        return {
            "kill_switch": self.kill_switch_engaged,
            "daily_pnl": self.daily_pnl,
            "daily_trade_count": self.daily_trade_count,
            "max_daily_trades": self.max_daily_trades,
            "max_order_usd": self.max_order_usd,
            "max_positions": self.max_positions,
        }
