"""
core/position_sizer.py — RossTrader_US

수수료 완전 반영 포지션 사이징 (v2.0).
켈리 기준 + 서킷브레이커 연동 + 신호 강도 기반 동적 사이징.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config.constants import USCommission, ExitConditions as EC
from core.factor_engine import FactorScore
from core.risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class PositionSizeResult:
    """포지션 사이징 결과."""
    shares: int
    notional_usd: float
    commission: dict
    roundtrip_cost_pct: float
    breakeven_pct: float
    stop_loss_usd: float
    target_profit_usd: float
    reward_risk_ratio: float
    viable: bool
    reject_reason: str = ""
    kelly_pct: float = 0.0
    cb_multiplier: float = 1.0


class PositionSizer:
    """
    수수료 완전 반영 포지션 사이징 (v2.0).

    설계 원칙:
    1. 손익분기점 이상의 목표가 없으면 거래 거부
    2. 계좌 리스크 2% 이내
    3. 켈리 기준 + 서킷브레이커 연동
    4. 팩터 스코어에 따라 사이즈 동적 조절
    """

    def __init__(
        self,
        account_usd: float,
        max_position_pct: float = 0.08,
        max_risk_per_trade_pct: float = 0.02,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.account_usd = account_usd
        self.max_position_pct = max_position_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.risk_manager = risk_manager

    def calculate(
        self,
        price: float,
        factor_score: FactorScore,
        stop_loss_pct: float = EC.STOP_LOSS_NORMAL,
        target_pct: float = EC.TAKE_PROFIT_2,
        win_rate: float = 0.0,
        avg_win: float = 0.0,
        avg_loss: float = 0.0,
    ) -> PositionSizeResult:
        """
        포지션 크기 계산 (켈리 기준 + 서킷브레이커 연동).

        Args:
            price: 현재가 ($)
            factor_score: 팩터 스코어 객체
            stop_loss_pct: 손절 비율 (기본 2.0%)
            target_pct: 목표 수익 비율 (기본 3.5%)
            win_rate: 과거 승률 (켈리 기준용, 0=사용 안함)
            avg_win: 평균 수익률 (켈리 기준용)
            avg_loss: 평균 손실률 (켈리 기준용)
        """
        signal = factor_score.signal_strength

        # 1. 신호 강도에 따른 기본 사이즈 비율
        size_multiplier = {
            "STRONG": 1.0,
            "NORMAL": 0.7,
            "WEAK": 0.4,
            "NONE": 0.0,
        }.get(signal, 0.0)

        if size_multiplier == 0:
            return PositionSizeResult(
                shares=0, notional_usd=0,
                commission={}, roundtrip_cost_pct=0,
                breakeven_pct=0, stop_loss_usd=0,
                target_profit_usd=0, reward_risk_ratio=0,
                viable=False, reject_reason="신호 강도 NONE",
            )

        # 2. 서킷브레이커 레벨 반영
        cb_mult = 1.0
        if self.risk_manager:
            cb_mult = self.risk_manager.get_position_size_multiplier()
            if cb_mult == 0:
                return PositionSizeResult(
                    shares=0, notional_usd=0,
                    commission={}, roundtrip_cost_pct=0,
                    breakeven_pct=0, stop_loss_usd=0,
                    target_profit_usd=0, reward_risk_ratio=0,
                    viable=False,
                    reject_reason=f"서킷브레이커 레벨: {self.risk_manager.circuit_breaker_level}",
                )

        # 3. 켈리 기준 사이징 (데이터가 있을 때만)
        kelly_pct = 0.0
        kelly_notional = 0.0
        if win_rate > 0 and avg_win > 0 and avg_loss > 0 and self.risk_manager:
            # 리스크매니저의 켈리 계산 사용
            kelly_usd = self.risk_manager.kelly_position_size(
                win_rate=win_rate,
                avg_win=avg_win,
                avg_loss=avg_loss,
                capital=self.account_usd,
            )
            kelly_pct = kelly_usd / self.account_usd if self.account_usd > 0 else 0
            kelly_notional = kelly_usd

        # 4. 최대 주문 금액 (신호 강도 + 서킷브레이커 반영)
        max_notional = self.account_usd * self.max_position_pct * size_multiplier * cb_mult

        # 5. 리스크 기반 주문 금액
        max_loss_usd = self.account_usd * self.max_risk_per_trade_pct * cb_mult
        risk_based_notional = max_loss_usd / stop_loss_pct

        # 6. 최종 노셔널 = min(켈리, 최대주문, 리스크기반)
        if kelly_notional > 0:
            notional = min(max_notional, risk_based_notional, kelly_notional)
        else:
            notional = min(max_notional, risk_based_notional)

        if notional > self.account_usd * self.max_position_pct:
            notional = self.account_usd * self.max_position_pct

        # 7. 주수 계산
        shares = int(notional / price)
        if shares < 1:
            return PositionSizeResult(
                shares=0, notional_usd=0,
                commission={}, roundtrip_cost_pct=0,
                breakeven_pct=0, stop_loss_usd=0,
                target_profit_usd=0, reward_risk_ratio=0,
                viable=False,
                reject_reason=f"주문 가능 주수 0 (금액 부족: ${notional:.0f})",
            )

        actual_notional = shares * price

        # 8. 수수료 계산
        buy_cost = USCommission.total_cost(actual_notional, shares, "buy")
        sell_cost = USCommission.total_cost(actual_notional, shares, "sell")
        roundtrip_pct = buy_cost["total_pct"] + sell_cost["total_pct"]
        breakeven_pct = roundtrip_pct * 1.0

        # 9. 실질 손익 (수수료 차감 후)
        gross_target = actual_notional * target_pct
        gross_sl = actual_notional * stop_loss_pct
        net_target = gross_target - buy_cost["total_usd"] - sell_cost["total_usd"]
        net_sl = gross_sl + buy_cost["total_usd"] + sell_cost["total_usd"]

        # 10. 손익분기점 검사
        if target_pct <= breakeven_pct * 1.5:
            return PositionSizeResult(
                shares=0, notional_usd=0,
                commission=buy_cost, roundtrip_cost_pct=roundtrip_pct,
                breakeven_pct=breakeven_pct, stop_loss_usd=0,
                target_profit_usd=0, reward_risk_ratio=0,
                viable=False,
                reject_reason=(
                    f"목표수익({target_pct*100:.1f}%) ≤ "
                    f"수수료({breakeven_pct*100:.2f}%)×1.5"
                ),
            )

        rr_ratio = round(net_target / net_sl, 2) if net_sl > 0 else 0

        logger.info(
            "[PositionSizer] %s | %d주 @ $%.2f = $%s | "
            "수수료: $%.2f (%.3f%%) | 손익분기: %.3f%% | 순손익비: %.2f | "
            "켈리: %.1f%% | 서킷브레이커: %.0f%%",
            factor_score.ticker, shares, price, f"{actual_notional:,.0f}",
            buy_cost["total_usd"] + sell_cost["total_usd"],
            roundtrip_pct * 100, breakeven_pct * 100, rr_ratio,
            kelly_pct * 100, cb_mult * 100,
        )

        return PositionSizeResult(
            shares=shares,
            notional_usd=actual_notional,
            commission=buy_cost,
            roundtrip_cost_pct=roundtrip_pct,
            breakeven_pct=breakeven_pct,
            stop_loss_usd=net_sl,
            target_profit_usd=net_target,
            reward_risk_ratio=rr_ratio,
            viable=True,
            kelly_pct=kelly_pct,
            cb_multiplier=cb_mult,
        )
