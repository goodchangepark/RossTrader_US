"""
utils/news_trader.py — RossTrader_US

뉴스 기반 자동매매 스레드.
기존 RossTrader utils/news_trader.py 호환 인터페이스.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class NewsTraderThread(QThread):
    """뉴스 기반 자동매매 스레드 (PyQt5 QThread)."""

    log_signal = pyqtSignal(str)
    trade_signal = pyqtSignal(dict)

    def __init__(
        self,
        cfg: dict,
        broker: Any,
        news_collector: Any,
        settings: Optional[dict] = None,
    ):
        super().__init__()
        self._cfg = cfg
        self._broker = broker
        self._news_collector = news_collector
        self._settings = settings or {}
        self._running = False
        self._positions: Dict[str, dict] = {}
        self._cycle_count = 0

    def run(self):
        """메인 루프 실행."""
        self._running = True
        self.log_signal.emit("[NewsTrader] 자동매매 스레드 시작")

        interval = max(self._settings.get("scan_interval_sec", 60), 10)

        while self._running:
            try:
                self._cycle()
                self._cycle_count += 1
            except Exception as e:
                self.log_signal.emit(f"[NewsTrader] 사이클 오류: {e}")

            # 1초 단위로 _running 체크하며 대기
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

        self.log_signal.emit("[NewsTrader] 자동매매 스레드 종료")

    def _cycle(self):
        """매 사이클 실행: 뉴스 수집 → 분석 → 매매."""
        tickers = self._get_watchlist()
        if not tickers:
            return

        # 뉴스 수집
        news_items = []
        try:
            if self._news_collector:
                news_items = self._news_collector.collect(tickers)
        except Exception as e:
            logger.warning(f"[NewsTrader] 뉴스 수집 실패: {e}")

        if not news_items:
            return

        # 뉴스 분석 및 매매 (간략화)
        for item in news_items[:10]:
            ticker = item.ticker if hasattr(item, 'ticker') else ''
            if not ticker or ticker not in tickers:
                continue

            self.trade_signal.emit({
                "time": datetime.now().strftime("%H:%M:%S"),
                "ticker": ticker,
                "side": "WATCH",
                "qty": 0,
                "price": 0.0,
                "profit": 0.0,
                "profit_pct": 0.0,
                "reason": f"뉴스 감지: {item.title[:50] if hasattr(item, 'title') else ''}",
            })

    def _get_watchlist(self) -> List[str]:
        """관심종목 리스트 반환."""
        try:
            trade_cfg = self._cfg.get("trade", {})
            watchlist = trade_cfg.get("watchlist", [])
            if not watchlist:
                # 기본 관심종목
                watchlist = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
                             "NVDA", "META", "JPM", "V", "JNJ"]
            return watchlist
        except Exception:
            return ["AAPL", "MSFT", "GOOGL"]

    def stop(self):
        """스레드 중지."""
        self._running = False
        self.log_signal.emit("[NewsTrader] 중지 요청")
