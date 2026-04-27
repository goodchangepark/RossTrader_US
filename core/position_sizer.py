"""
core/position_sizer.py — RossTrader_US

수수료 완전 반영 포지션 사이징.
켈리 기준 + 수수료 손익분기점 기반.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config.constants import USCommission, ExitConditions as EC
from core.factor_engine import FactorScore

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


class PositionSizer:
    """
    수수료 완전 반영 포지션 사이징.

    설계 원칙:
    1. 손익분기점 이상의 목표가 없으면 거래 거부
    2. 계좌 리스크 2% 이내
    3. 팩터 스코어에 따라 사이즈 동적 조절
    """

    def __init__(
        self,
        account_usd: float,
        max_position_pct: float = 0.08,
        max_risk_per_trade_pct: float = 0.02,
    ):
        self.account_usd = account_usd
        self.max_position_pct = max_position_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct

    def calculate(
        self,
        price: float,
        factor_score: FactorScore,
        stop_loss_pct: float = EC.STOP_LOSS_NORMAL,
        target_pct: float = EC.TAKE_PROFIT_2,
    ) -> PositionSizeResult:
        """
        포지션 크기 계산.

        Args:
            price: 현재가 ($)
            factor_score: 팩터 스코어 객체
            stop_loss_pct: 손절 비율 (기본 2.0%)
            target_pct: 목표 수익 비율 (기본 3.5%)
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

        # 2. 최대 주문 금액
        max_notional = self.account_usd * self.max_position_pct * size_multiplier

        # 3. 리스크 기반 주문 금액
        max_loss_usd = self.account_usd * self.max_risk_per_trade_pct
        risk_based_notional = max_loss_usd / stop_loss_pct

        notional = min(max_notional, risk_based_notional)

        # 4. 주수 계산
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

        # 5. 수수료 계산
        buy_cost  = USCommission.total_cost(actual_notional, shares, "buy")
        sell_cost = USCommission.total_cost(actual_notional, shares, "sell")
        roundtrip_pct = buy_cost["total_pct"] + sell_cost["total_pct"]
        breakeven_pct = roundtrip_pct * 1.0

        # 6. 실질 손익 (수수료 차감 후)
        gross_target = actual_notional * target_pct
        gross_sl     = actual_notional * stop_loss_pct
        net_target   = gross_target - buy_cost["total_usd"] - sell_cost["total_usd"]
        net_sl       = gross_sl + buy_cost["total_usd"] + sell_cost["total_usd"]

        # 7. 손익분기점 검사
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
            "수수료: $%.2f (%.3f%%) | 손익분기: %.3f%% | 순손익비: %.2f",
            factor_score.ticker, shares, price, f"{actual_notional:,.0f}",
            buy_cost["total_usd"] + sell_cost["total_usd"],
            roundtrip_pct * 100, breakeven_pct * 100, rr_ratio,
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
        )
