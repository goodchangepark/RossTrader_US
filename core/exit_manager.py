"""
core/exit_manager.py — RossTrader_US

수수료 완전 반영 청산 관리자.
모든 수익/손실 판단은 수수료 차감 후 실질 기준으로 계산.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from config.constants import USCommission, ExitConditions as EC
from markets.us.us_session import us_session

logger = logging.getLogger(__name__)


class ExitReason(Enum):
    """청산 사유."""
    STOP_LOSS     = "stop_loss"
    TAKE_PROFIT_1 = "take_profit_1"
    TAKE_PROFIT_2 = "take_profit_2"
    TAKE_PROFIT_3 = "take_profit_3"
    TRAILING_STOP = "trailing_stop"
    TIME_STOP     = "time_stop"
    VWAP_FAIL     = "vwap_fail"
    FORCE_FLAT    = "force_flat"
    KILL_SWITCH   = "kill_switch"
    BREAKEVEN_HIT = "breakeven_hit"
    MANUAL        = "manual"


@dataclass
class Position:
    """보유 포지션."""
    ticker: str
    shares: int
    entry_price: float
    entry_time: datetime
    entry_commission_usd: float = 0.0
    stop_loss_price: float = 0.0
    initial_stop_price: float = 0.0
    trail_price: float = 0.0
    highest_price: float = 0.0
    partial_exit_1_done: bool = False
    partial_exit_2_done: bool = False
    remaining_shares: int = 0
    vwap_below_bars: int = 0
    breakeven_moved: bool = False

    def __post_init__(self):
        if self.remaining_shares == 0:
            self.remaining_shares = self.shares
        if self.highest_price == 0:
            self.highest_price = self.entry_price

    @property
    def notional_usd(self) -> float:
        return self.entry_price * self.shares

    def pnl_gross_pct(self, current_price: float) -> float:
        """총 수익률 (수수료 미차감)."""
        return (current_price - self.entry_price) / self.entry_price

    def pnl_net_pct(self, current_price: float, shares_to_sell: Optional[int] = None) -> float:
        """순 수익률 (수수료 차감 후)."""
        n = shares_to_sell or self.remaining_shares
        exit_notional = current_price * n
        exit_cost = USCommission.total_cost(exit_notional, n, "sell")

        gross_pnl = (current_price - self.entry_price) * n
        net_pnl   = gross_pnl - exit_cost["total_usd"] - self.entry_commission_usd
        notional  = self.entry_price * n
        return net_pnl / notional if notional > 0 else 0

    def hold_minutes(self) -> int:
        """보유 시간 (분)."""
        if not self.entry_time.tzinfo:
            return int((datetime.now() - self.entry_time).total_seconds() / 60)
        return int((datetime.now(self.entry_time.tzinfo) - self.entry_time).total_seconds() / 60)


@dataclass
class ExitSignal:
    """청산 신호."""
    should_exit: bool = False
    reason: Optional[ExitReason] = None
    shares_to_exit: int = 0
    is_partial: bool = False
    expected_net_pnl_pct: float = 0.0
    current_price: float = 0.0
    message: str = ""


class ExitManager:
    """
    수수료 완전 반영 청산 관리자.
    모든 청산 판단은 실질 수익 기준으로 수행.
    """

    def check_exit(
        self,
        position: Position,
        current_price: float,
        current_vwap: float,
        is_vwap_bar_below: bool = False,
    ) -> ExitSignal:
        """
        청산 조건 순서대로 점검.
        순서: 킬스위치 > 강제청산 > 손절 > VWAP실패 > 시간손절
              > 트레일링 > 부분익절 > 손익분기이동
        """
        sig = ExitSignal(current_price=current_price)

        # 최고가 갱신
        if current_price > position.highest_price:
            position.highest_price = current_price

        # VWAP 이탈 카운터
        if is_vwap_bar_below:
            position.vwap_below_bars += 1
        else:
            position.vwap_below_bars = 0

        gross_ret = position.pnl_gross_pct(current_price)
        net_ret   = position.pnl_net_pct(current_price)

        # ① 강제 청산 (장 마감 10분 전)
        if us_session.should_force_flat():
            return _make_signal(ExitReason.FORCE_FLAT, position.remaining_shares,
                                net_ret, f"장 마감 강제청산 | 순손익: {net_ret*100:.2f}%")

        # ② 시간 손절
        hold_min = position.hold_minutes()
        if hold_min >= EC.MAX_HOLD_MINUTES:
            return _make_signal(ExitReason.TIME_STOP, position.remaining_shares,
                                net_ret, f"시간손절 {hold_min}분 | 순손익: {net_ret*100:.2f}%")

        # ③ 손절
        if current_price <= position.stop_loss_price:
            return _make_signal(ExitReason.STOP_LOSS, position.remaining_shares,
                                net_ret,
                                f"손절 | 현재가 ${current_price:.2f} ≤ 손절가 ${position.stop_loss_price:.2f} | "
                                f"순손실: {net_ret*100:.2f}%")

        # ④ VWAP 연속 이탈
        if position.vwap_below_bars >= EC.VWAP_FAIL_BARS:
            return _make_signal(ExitReason.VWAP_FAIL, position.remaining_shares,
                                net_ret, f"VWAP 연속 {position.vwap_below_bars}바 이탈")

        # ⑤ 트레일링 스탑
        if gross_ret > 0:
            trail_signal = self._check_trailing(position, current_price)
            if trail_signal.should_exit:
                trail_signal.expected_net_pnl_pct = net_ret
                return trail_signal

        # ⑥ 부분 익절 1차
        if not position.partial_exit_1_done and gross_ret >= EC.TAKE_PROFIT_1:
            partial_shares = int(position.remaining_shares * EC.PARTIAL_EXIT_1_PCT)
            if partial_shares > 0:
                sig.should_exit    = True
                sig.reason         = ExitReason.TAKE_PROFIT_1
                sig.shares_to_exit = partial_shares
                sig.is_partial     = True
                sig.expected_net_pnl_pct = position.pnl_net_pct(current_price, partial_shares)
                sig.message = (
                    f"1차 부분익절 {EC.PARTIAL_EXIT_1_PCT*100:.0f}% ({partial_shares}주) | "
                    f"총수익: {gross_ret*100:.2f}% | 순수익: {sig.expected_net_pnl_pct*100:.2f}%"
                )
                position.partial_exit_1_done = True
                position.remaining_shares -= partial_shares
                position.stop_loss_price = position.entry_price
                position.breakeven_moved = True
                return sig

        # ⑦ 부분 익절 2차
        if (position.partial_exit_1_done
                and not position.partial_exit_2_done
                and gross_ret >= EC.TAKE_PROFIT_2):
            # 남은 주식의 30% (원본의 30%)
            pct_left = EC.PARTIAL_EXIT_2_PCT / (1 - EC.PARTIAL_EXIT_1_PCT)
            partial_shares = int(position.remaining_shares * pct_left)
            if partial_shares > 0:
                _sig = _make_signal(ExitReason.TAKE_PROFIT_2, partial_shares,
                                    position.pnl_net_pct(current_price, partial_shares),
                                    f"2차 부분익절 ({partial_shares}주)")
                _sig.is_partial = True
                position.partial_exit_2_done = True
                position.remaining_shares -= partial_shares
                return _sig

        # ⑧ 3차 목표 (잔량 전량)
        if position.partial_exit_2_done and gross_ret >= EC.TAKE_PROFIT_3:
            return _make_signal(ExitReason.TAKE_PROFIT_3, position.remaining_shares,
                                net_ret, f"3차 목표 달성 | 순수익: {net_ret*100:.2f}%")

        # ⑨ 손익분기점 이동 후 진입가 아래
        if position.breakeven_moved and current_price <= position.entry_price:
            return _make_signal(ExitReason.BREAKEVEN_HIT, position.remaining_shares,
                                net_ret, "손익분기 손절 (진입가 터치)")

        return sig

    def _check_trailing(self, position: Position, current_price: float) -> ExitSignal:
        """가속형 트레일링 스탑."""
        gross_ret = position.pnl_gross_pct(current_price)
        highest   = position.highest_price

        if gross_ret >= 0.05:
            trail_gap = EC.TRAILING_TIGHTEN_2
        elif gross_ret >= 0.03:
            trail_gap = EC.TRAILING_TIGHTEN_1
        else:
            trail_gap = EC.TRAILING_INITIAL

        new_trail = highest * (1 - trail_gap)
        if new_trail > position.trail_price:
            position.trail_price = new_trail

        sig = ExitSignal()
        if current_price <= position.trail_price and position.trail_price > 0:
            sig.should_exit    = True
            sig.reason         = ExitReason.TRAILING_STOP
            sig.shares_to_exit = position.remaining_shares
            sig.message = (
                f"트레일링 스탑 | 현재 ${current_price:.2f} ≤ "
                f"트레일 ${position.trail_price:.2f} (간격 {trail_gap*100:.1f}%)"
            )
        return sig


def _make_signal(reason: ExitReason, shares: int, net_pnl: float, msg: str) -> ExitSignal:
    """청산 신호 생성 헬퍼."""
    return ExitSignal(
        should_exit=True,
        reason=reason,
        shares_to_exit=shares,
        expected_net_pnl_pct=net_pnl,
        message=msg,
    )
