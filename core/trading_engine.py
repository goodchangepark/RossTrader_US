"""
core/trading_engine.py — RossTrader_US

트레이딩 엔진.
메인 루프에서 시장 상태 체크 → 신호 생성 → 매매 실행.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from config.constants import APP_NAME

logger = logging.getLogger(__name__)

# 전역 엔진 인스턴스 (IPC 큐 공유용)
_engine_instance: Optional["TradingEngine"] = None


def reset_trading_engine():
    """전역 엔진 초기화."""
    global _engine_instance
    _engine_instance = None


class TradingEngine:
    """
    트레이딩 엔진.
    - 메인 루프 실행
    - 시장 상태 체크
    - 신호 생성 → 매매 실행
    - IPC 큐를 통한 GUI 통신
    """

    def __init__(
        self,
        cfg: dict,
        broker: Any,
        news_collector: Any,
        on_log: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
    ):
        self._cfg = cfg
        self._broker = broker
        self._news_collector = news_collector
        self._on_log = on_log
        self._on_trade = on_trade
        self._on_status = on_status
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()

        global _engine_instance
        _engine_instance = self

    def start(self) -> bool:
        """엔진 시작."""
        if self._running:
            return False

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        if self._on_log:
            self._on_log(f"[TradingEngine] {APP_NAME} 엔진 시작")

        logger.info("[TradingEngine] 엔진 시작")
        return True

    def stop(self):
        """엔진 중지."""
        self._running = False
        if self._on_log:
            self._on_log("[TradingEngine] 엔진 중지 요청")
        logger.info("[TradingEngine] 엔진 중지 요청")

    def drain(self) -> List[dict]:
        """IPC 큐 드레인."""
        items = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def _run_loop(self):
        """메인 루프."""
        interval = max(self._cfg.get("trade", {}).get("scan_interval_sec", 60), 10)

        while self._running:
            try:
                self._cycle()
            except Exception as e:
                logger.error(f"[TradingEngine] 사이클 오류: {e}")

            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("[TradingEngine] 엔진 종료")

    def _cycle(self):
        """매 사이클 실행."""
        # 시장 상태 체크
        if self._broker:
            try:
                if hasattr(self._broker, 'get_market_status'):
                    status = self._broker.get_market_status()
                    if status:
                        self._queue.put({
                            "type": "market_status",
                            "data": status,
                        })
            except Exception as e:
                logger.warning(f"[TradingEngine] 시장 상태 체크 실패: {e}")

        # 잔고 조회
        if self._broker:
            try:
                bal = self._broker.get_balance()
                self._queue.put({
                    "type": "balance",
                    "total_usd": bal.total_usd if hasattr(bal, 'total_usd') else 0,
                    "cash_usd": bal.cash_usd if hasattr(bal, 'cash_usd') else 0,
                })
            except Exception as e:
                logger.warning(f"[TradingEngine] 잔고 조회 실패: {e}")
