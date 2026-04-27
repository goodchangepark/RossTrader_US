"""
markets/us/us_universe.py — RossTrader_US

미국 주식 유니버스 관리.
S&P500, NASDAQ100 주요 종목 리스트 및 필터링.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# 기본 관심 종목 (확장 가능)
DEFAULT_WATCHLIST = [
    # ── Big Tech ──
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NFLX",
    # ── 반도체 ──
    "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM",
    # ── 소비재 ──
    "TSLA", "COST", "WMT", "HD", "NKE", "DIS",
    # ── 금융 ──
    "JPM", "GS", "V", "MA", "BAC", "C",
    # ── 헬스케어 ──
    "JNJ", "PFE", "UNH", "ABBV", "MRK",
    # ── 에너지 ──
    "XOM", "CVX", "COP", "SLB",
    # ── 통신 ──
    "T", "VZ", "TMUS",
    # ── ETF ──
    "SPY", "QQQ", "DIA", "IWM", "VTI", "ARKK",
]

# 섹터 분류 (일부 주요 종목)
SECTOR_MAP: Dict[str, List[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NFLX", "CRM", "ADBE", "ORCL"],
    "Semiconductor": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "ASML", "AMAT"],
    "Consumer Cyclical": ["AMZN", "TSLA", "NKE", "HD", "LOW", "SBUX", "MCD"],
    "Financial": ["JPM", "GS", "V", "MA", "BAC", "C", "WFC", "AXP"],
    "Healthcare": ["JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY", "CVS"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY"],
    "Communication": ["T", "VZ", "TMUS", "CMCSA", "CHTR"],
    "Consumer Defensive": ["COST", "WMT", "PG", "KO", "PEP", "CL"],
    "Industrial": ["CAT", "GE", "BA", "HON", "UPS", "MMM"],
}


class USUniverse:
    """
    미국 주식 유니버스.

    사용 예:
        universe = USUniverse()
        print(universe.get_watchlist())
        print(universe.get_sector("AAPL"))
        print(universe.get_stocks_by_sector("Technology"))
    """

    def __init__(self):
        self._watchlist: List[str] = DEFAULT_WATCHLIST.copy()
        self._sector_map: Dict[str, List[str]] = SECTOR_MAP
        # 종목 → 섹터 역매핑
        self._ticker_sector: Dict[str, str] = {}
        for sector, tickers in self._sector_map.items():
            for t in tickers:
                self._ticker_sector[t] = sector
        logger.info("[USUniverse] 초기화 완료 | 관심종목: %d개", len(self._watchlist))

    def get_watchlist(self) -> List[str]:
        """관심 종목 리스트 반환."""
        return self._watchlist.copy()

    def add_to_watchlist(self, ticker: str) -> bool:
        """관심 종목 추가."""
        ticker = ticker.upper().strip()
        if ticker and ticker not in self._watchlist:
            self._watchlist.append(ticker)
            logger.info("[USUniverse] 관심종목 추가: %s", ticker)
            return True
        return False

    def remove_from_watchlist(self, ticker: str) -> bool:
        """관심 종목 제거."""
        ticker = ticker.upper().strip()
        if ticker in self._watchlist:
            self._watchlist.remove(ticker)
            logger.info("[USUniverse] 관심종목 제거: %s", ticker)
            return True
        return False

    def get_sector(self, ticker: str) -> str:
        """종목의 섹터 반환."""
        return self._ticker_sector.get(ticker.upper(), "Unknown")

    def get_stocks_by_sector(self, sector: str) -> List[str]:
        """특정 섹터의 종목 리스트 반환."""
        return self._sector_map.get(sector, [])

    def get_all_sectors(self) -> List[str]:
        """전체 섹터 리스트 반환."""
        return list(self._sector_map.keys())

    def search(self, keyword: str) -> List[str]:
        """키워드로 종목 검색 (티커/종목명)."""
        keyword = keyword.upper()
        return [t for t in self._watchlist if keyword in t]

    def to_dict(self) -> dict:
        """설정 저장용 dict."""
        return {
            "watchlist": self._watchlist,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "USUniverse":
        """dict에서 복원."""
        instance = cls()
        instance._watchlist = data.get("watchlist", DEFAULT_WATCHLIST.copy())
        return instance
