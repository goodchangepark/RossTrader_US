"""
core/execution_engine.py — RossTrader_US

체결 엔진 (TWAP 분할 체결).
기존 RossTrader execution_engine.py 로직 참고.
"""

from __future__ import annotations

import logging
import time as time_mod
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from markets.base import OrderResult

logger = logging.getLogger(__name__)


@dataclass
class ExecutionOrder:
    """체결 대상 주문."""
    ticker: str
    direction: str          # "buy" / "sell"
    total_qty: int
    total_value: float
    slice_qty: int = 0      # 분할 수량
    slices: int = 1         # 분할 횟수
    interval_sec: float = 60.0  # 분할 간격 (초)
    executed_qty: int = 0
    remaining_qty: int = 0
    is_completed: bool = False


class ExecutionEngine:
    """
    체결 엔진.
    TWAP 분할 체결로 시장 충격 최소화.
    """

    def __init__(self, order_func: Optional[Callable] = None):
        """
        Args:
            order_func: 실제 주문 함수 (signature: func(ticker, qty, price) -> OrderResult)
        """
        self.order_func = order_func
        self.active_orders: List[ExecutionOrder] = []
        logger.info("[ExecutionEngine] 초기화 완료")

    def create_twap_order(
        self,
        ticker: str,
        direction: str,
        total_qty: int,
        total_value: float,
        slices: int = 3,
        duration_minutes: int = 5,
    ) -> ExecutionOrder:
        """
        TWAP 주문 생성.
        total_qty를 slices로 분할하여 duration_minutes 동안 체결.
        """
        slice_qty = max(1, total_qty // slices)
        interval_sec = (duration_minutes * 60.0) / slices

        order = ExecutionOrder(
            ticker=ticker,
            direction=direction,
            total_qty=total_qty,
            total_value=total_value,
            slice_qty=slice_qty,
            slices=slices,
            interval_sec=interval_sec,
            remaining_qty=total_qty,
        )
        self.active_orders.append(order)
        logger.info("[ExecutionEngine] TWAP 주문 생성 | %s %s %d주 | %d회 분할 | %d분",
                     ticker, direction, total_qty, slices, duration_minutes)
        return order

    def execute_twap(self, order: ExecutionOrder, price: float) -> List[OrderResult]:
        """TWAP 실행."""
        results = []
        while order.remaining_qty > 0:
            qty = min(order.slice_qty, order.remaining_qty)

            if self.order_func:
                result = self.order_func(order.ticker, qty, price)
                results.append(result)

                if result.success:
                    order.executed_qty += qty
                    order.remaining_qty -= qty
                    logger.info("[ExecutionEngine] TWAP 체결 | %s %d주 @ $%.2f",
                                 order.ticker, qty, price)

            if order.remaining_qty > 0:
                time_mod.sleep(order.interval_sec)

        order.is_completed = True
        return results

    def cancel_all(self) -> None:
        """미체결 주문 취소."""
        self.active_orders.clear()
        logger.info("[ExecutionEngine] 모든 주문 취소")
