"""
core/portfolio_manager.py — RossTrader_US

포트폴리오 관리자.
섹터/팩터 익스포저 관리, 포트폴리오 비중 제어.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PositionInfo:
    """포지션 정보."""
    ticker: str
    name: str = ""
    qty: int = 0
    avg_price: float = 0.0
    current_price: float = 0.0
    total_value: float = 0.0
    profit_pct: float = 0.0
    sector: str = "Unknown"
    weight: float = 0.0


class PortfolioManager:
    """
    포트폴리오 관리자.
    섹터/팩터 익스포저 관리, 포지션 비중 제어.
    """

    def __init__(self, initial_capital_usd: float = 1000.0):
        self.initial_capital = initial_capital_usd
        self.max_portfolio_pct = settings.us.max_portfolio_pct
        self.positions: Dict[str, PositionInfo] = {}
        self.cash_usd: float = initial_capital_usd
        logger.info("[PortfolioManager] 초기화 완료 | 초기자본: $%.2f", initial_capital_usd)

    @property
    def total_value(self) -> float:
        """총 포트폴리오 가치 ($)."""
        pos_value = sum(p.total_value for p in self.positions.values())
        return self.cash_usd + pos_value

    @property
    def position_count(self) -> int:
        """보유 포지션 수."""
        return len(self.positions)

    def add_position(self, position: PositionInfo) -> bool:
        """포지션 추가."""
        if position.ticker in self.positions:
            logger.warning("[Portfolio] 이미 보유 중: %s", position.ticker)
            return False

        # 최대 포트폴리오 비중 체크
        new_value = position.total_value
        if new_value / self.total_value > self.max_portfolio_pct:
            logger.warning("[Portfolio] 비중 초과: %s (%.1f%%)",
                           position.ticker, new_value / self.total_value * 100)
            return False

        self.positions[position.ticker] = position
        self.cash_usd -= new_value
        self._update_weights()
        logger.info("[Portfolio] 포지션 추가 | %s %d주 @ $%.2f | 잔고: $%.2f",
                     position.ticker, position.qty, position.avg_price, self.cash_usd)
        return True

    def remove_position(self, ticker: str) -> Optional[PositionInfo]:
        """포지션 제거."""
        pos = self.positions.pop(ticker, None)
        if pos:
            self.cash_usd += pos.total_value
            self._update_weights()
            logger.info("[Portfolio] 포지션 제거 | %s | 회수: $%.2f | 잔고: $%.2f",
                         ticker, pos.total_value, self.cash_usd)
        return pos

    def update_price(self, ticker: str, current_price: float) -> None:
        """포지션 현재가 업데이트."""
        if ticker in self.positions:
            pos = self.positions[ticker]
            pos.current_price = current_price
            pos.total_value = pos.qty * current_price
            pos.profit_pct = ((current_price - pos.avg_price) / pos.avg_price) * 100.0
            self._update_weights()

    def _update_weights(self) -> None:
        """각 포지션 비중 재계산."""
        total = self.total_value
        if total > 0:
            for pos in self.positions.values():
                pos.weight = (pos.total_value / total) * 100.0

    def get_sector_exposure(self) -> Dict[str, float]:
        """섹터별 익스포저 ($)."""
        exposure: Dict[str, float] = {}
        for pos in self.positions.values():
            sector = pos.sector
            exposure[sector] = exposure.get(sector, 0.0) + pos.total_value
        return exposure

    def get_summary(self) -> dict:
        """포트폴리오 요약."""
        return {
            "total_value": self.total_value,
            "cash": self.cash_usd,
            "position_count": self.position_count,
            "positions": [
                {
                    "ticker": p.ticker,
                    "qty": p.qty,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "total_value": p.total_value,
                    "profit_pct": p.profit_pct,
                    "sector": p.sector,
                    "weight": p.weight,
                }
                for p in self.positions.values()
            ],
            "sector_exposure": self.get_sector_exposure(),
        }

    def reset(self) -> None:
        """포트폴리오 리셋."""
        self.positions.clear()
        self.cash_usd = self.initial_capital
        logger.info("[Portfolio] 리셋 완료")
