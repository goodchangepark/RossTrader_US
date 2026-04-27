"""
utils/performance_tracker.py — RossTrader_US

일일 거래 성과 추적 (수수료 완전 반영).
매 거래 후 자동 업데이트.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

from config.constants import USCommission

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """개별 거래 기록."""
    ticker: str
    shares: int
    entry_price: float
    exit_price: float
    entry_commission: dict
    exit_commission: dict
    exit_reason: str
    hold_minutes: int
    timestamp: str = ""

    @property
    def gross_pnl_usd(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def total_commission_usd(self) -> float:
        return (
            self.entry_commission.get("total_usd", 0)
            + self.exit_commission.get("total_usd", 0)
        )

    @property
    def net_pnl_usd(self) -> float:
        return self.gross_pnl_usd - self.total_commission_usd

    @property
    def net_pnl_pct(self) -> float:
        notional = self.entry_price * self.shares
        return self.net_pnl_usd / notional if notional > 0 else 0.0

    def summary(self) -> dict:
        return {
            "ticker": self.ticker,
            "shares": self.shares,
            "entry": f"${self.entry_price:.2f}",
            "exit": f"${self.exit_price:.2f}",
            "gross_pnl": f"${self.gross_pnl_usd:+.2f}",
            "commission": f"${self.total_commission_usd:.2f}",
            "net_pnl": f"${self.net_pnl_usd:+.2f}",
            "net_pnl_pct": f"{self.net_pnl_pct*100:+.2f}%",
            "exit_reason": self.exit_reason,
            "hold_minutes": self.hold_minutes,
        }


@dataclass
class DailyPerformance:
    """일일 거래 성과."""
    date_str: str
    trades: List[TradeRecord] = field(default_factory=list)

    @property
    def total_gross_pnl(self) -> float:
        return sum(t.gross_pnl_usd for t in self.trades)

    @property
    def total_commission(self) -> float:
        return sum(t.total_commission_usd for t in self.trades)

    @property
    def total_net_pnl(self) -> float:
        return sum(t.net_pnl_usd for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.net_pnl_usd > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_wins  = sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd > 0)
        gross_loses = abs(sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd < 0))
        return gross_wins / gross_loses if gross_loses > 0 else float("inf")

    def add_trade(self, trade: TradeRecord) -> None:
        """거래 추가."""
        self.trades.append(trade)
        logger.info(
            "[Performance] 거래 추가 | %s %d주 | 순손익: $%.2f (%.2f%%)",
            trade.ticker, trade.shares, trade.net_pnl_usd, trade.net_pnl_pct * 100,
        )

    def summary(self) -> dict:
        """일일 성과 요약."""
        return {
            "날짜": self.date_str,
            "거래횟수": len(self.trades),
            "총수익(수수료전)": f"${self.total_gross_pnl:+.2f}",
            "총수수료": f"${self.total_commission:.2f}",
            "순수익": f"${self.total_net_pnl:+.2f}",
            "승률": f"{self.win_rate*100:.1f}%",
            "수익팩터": f"{self.profit_factor:.2f}",
            "수수료비중": (
                f"{self.total_commission / abs(self.total_gross_pnl) * 100:.1f}%"
                if self.total_gross_pnl != 0 else "N/A"
            ),
        }


class PerformanceTracker:
    """
    거래 성과 추적기.
    일별/전체 성과를 수수료 완전 반영하여 계산.
    """

    def __init__(self):
        self.daily: Dict[str, DailyPerformance] = {}

    def record_trade(
        self,
        ticker: str,
        shares: int,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
        hold_minutes: int,
        trade_date: str | None = None,
    ) -> TradeRecord:
        """
        거래 기록 저장 (수수료 자동 계산).

        Args:
            ticker: 종목 코드
            shares: 주문 주수
            entry_price: 진입 가격
            exit_price: 청산 가격
            exit_reason: 청산 사유
            hold_minutes: 보유 시간 (분)
            trade_date: 거래일 (기본: 오늘)
        """
        if trade_date is None:
            trade_date = date.today().isoformat()

        # 수수료 계산
        notional_buy  = entry_price * shares
        notional_sell = exit_price * shares
        entry_comm = USCommission.total_cost(notional_buy, shares, "buy")
        exit_comm  = USCommission.total_cost(notional_sell, shares, "sell")

        trade = TradeRecord(
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_commission=entry_comm,
            exit_commission=exit_comm,
            exit_reason=exit_reason,
            hold_minutes=hold_minutes,
        )

        # 일일 성과에 추가
        if trade_date not in self.daily:
            self.daily[trade_date] = DailyPerformance(date_str=trade_date)
        self.daily[trade_date].add_trade(trade)

        return trade

    def get_daily_summary(self, date_str: str) -> dict | None:
        """특정 일자의 성과 요약."""
        perf = self.daily.get(date_str)
        if perf:
            return perf.summary()
        return None

    def get_overall_summary(self) -> dict:
        """전체 기간 성과 요약."""
        all_trades = []
        total_days = len(self.daily)

        for day in self.daily.values():
            all_trades.extend(day.trades)

        if not all_trades:
            return {"거래없음": "기록된 거래가 없습니다."}

        total_gross  = sum(t.gross_pnl_usd for t in all_trades)
        total_comm   = sum(t.total_commission_usd for t in all_trades)
        total_net    = sum(t.net_pnl_usd for t in all_trades)
        wins         = sum(1 for t in all_trades if t.net_pnl_usd > 0)

        return {
            "전체거래일": total_days,
            "전체거래횟수": len(all_trades),
            "총수익(수수료전)": f"${total_gross:+.2f}",
            "총수수료": f"${total_comm:.2f}",
            "순수익": f"${total_net:+.2f}",
            "승률": f"{wins/len(all_trades)*100:.1f}%",
            "평균수수료율": (
                f"{total_comm / abs(total_gross) * 100:.1f}%"
                if total_gross != 0 else "N/A"
            ),
        }

    def reset(self) -> None:
        """모든 데이터 초기화."""
        self.daily.clear()
        logger.info("[PerformanceTracker] 데이터 초기화 완료")
