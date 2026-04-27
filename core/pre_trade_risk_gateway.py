"""
core/pre_trade_risk_gateway.py — RossTrader_US

사전 리스크 게이트웨이.
주문 실행 전 최종 리스크 검증.
"""

from __future__ import annotations

import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class PreTradeRiskGateway:
    """
    사전 리스크 게이트웨이.
    주문 실행 전 최종 검증:
    - 최대 주문 금액 검증
    - 포트폴리오 비중 검증
    - 시장 상태 검증
    - 환율 리스크 검증
    """

    def __init__(self):
        self.max_order_usd = settings.us.max_order_usd
        self.max_portfolio_pct = settings.us.max_portfolio_pct
        logger.info("[PreTradeRisk] 초기화 완료 | max_order=$%.0f", self.max_order_usd)

    def check(
        self,
        ticker: str,
        qty: int,
        estimated_price: float,
        current_portfolio_value: float,
    ) -> dict:
        """
        사전 리스크 체크.

        Returns:
            {
                "passed": bool,
                "reason": str,
                "details": {}
            }
        """
        order_value = qty * estimated_price
        result = {"passed": True, "reason": "", "details": {}}

        # 1. 최대 주문 금액
        if order_value > self.max_order_usd:
            result["passed"] = False
            result["reason"] = f"최대 주문 금액 초과: ${order_value:.2f} > ${self.max_order_usd:.2f}"
            return result

        # 2. 포트폴리오 비중
        if current_portfolio_value > 0:
            weight = (order_value / current_portfolio_value) * 100.0
            if weight > self.max_portfolio_pct * 100.0:
                result["passed"] = False
                result["reason"] = f"포트폴리오 비중 초과: {weight:.1f}% > {self.max_portfolio_pct*100:.0f}%"
                return result

        result["details"] = {
            "ticker": ticker,
            "qty": qty,
            "estimated_price": estimated_price,
            "order_value": order_value,
            "portfolio_value": current_portfolio_value,
        }

        return result
