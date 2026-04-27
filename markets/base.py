"""
markets/base.py — RossTrader_US

추상 Market 인터페이스.
모든 시장(한국/미국/일본 등)은 이 인터페이스를 구현해야 함.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OrderResult:
    """주문 결과."""
    success: bool
    order_no: str = ""
    ticker: str = ""
    exchange: str = ""
    direction: str = ""  # "buy" / "sell"
    qty: int = 0
    price: float = 0.0
    error_msg: str = ""
    raw_response: dict = field(default_factory=dict)


@dataclass
class PriceInfo:
    """현재가 정보."""
    ticker: str
    exchange: str
    price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    change_pct: float = 0.0
    timestamp: str = ""


@dataclass
class BalanceInfo:
    """잔고 정보."""
    total_usd: float = 0.0
    cash_usd: float = 0.0
    positions: List[dict] = field(default_factory=list)


class AbstractMarket(ABC):
    """시장 추상 인터페이스."""

    @abstractmethod
    def is_tradeable(self) -> bool:
        """현재 거래 가능 시간인지 확인."""
        ...

    @abstractmethod
    def buy(self, ticker: str, qty: int, price: float = 0.0) -> OrderResult:
        """매수 주문."""
        ...

    @abstractmethod
    def sell(self, ticker: str, qty: int, price: float = 0.0) -> OrderResult:
        """매도 주문."""
        ...

    @abstractmethod
    def get_price(self, ticker: str) -> Optional[PriceInfo]:
        """현재가 조회."""
        ...

    @abstractmethod
    def get_balance(self) -> BalanceInfo:
        """잔고 조회."""
        ...

    @abstractmethod
    def to_base_currency(self, amount: float) -> float:
        """
        시장 통화를 기준 통화(KRW)로 변환.
        - 미국: amount * USD/KRW 환율
        - 한국: amount (이미 KRW)
        """
        ...

    @abstractmethod
    def collect_news(self, tickers: List[str]) -> List[dict]:
        """뉴스 수집."""
        ...

    @abstractmethod
    def get_market_status(self) -> dict:
        """시장 상태 요약 반환."""
        ...
