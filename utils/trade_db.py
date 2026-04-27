"""
utils/trade_db.py — RossTrader_US

거래 내역 DB (간단 JSON 파일 기반).
기존 RossTrader utils/trade_db.py 호환 인터페이스.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 프로젝트 루트
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "trade_history.json"


def get_trade_db(path: str = "") -> "TradeDB":
    """TradeDB 싱글톤 인스턴스 반환."""
    return TradeDB(path or str(_DEFAULT_DB_PATH))


class TradeDB:
    """
    거래 내역 DB (JSON 파일).
    - get_today_stats(): 오늘 통계 반환
    - get_history(): 전체 거래 내역 반환
    - add_trade(): 거래 추가
    - close(): 파일 저장
    """

    def __init__(self, path: str):
        self._path = path
        self._trades: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        """JSON 파일에서 거래 내역 로드."""
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get("trades", [])
        except Exception as e:
            logger.warning(f"[TradeDB] 로드 실패: {e}")
            return []

    def _save(self):
        """거래 내역을 JSON 파일에 저장."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"trades": self._trades}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[TradeDB] 저장 실패: {e}")

    def add_trade(self, trade: Dict[str, Any]):
        """거래 추가."""
        if "timestamp" not in trade:
            trade["timestamp"] = datetime.now().isoformat()
        self._trades.append(trade)
        self._save()

    def get_today_stats(self) -> Dict[str, Any]:
        """오늘 거래 통계 반환."""
        today = date.today().isoformat()
        today_trades = [
            t for t in self._trades
            if t.get("timestamp", "").startswith(today)
        ]

        if not today_trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "net_pnl_pct": 0.0,
            }

        wins = sum(1 for t in today_trades if t.get("net_pnl", 0) > 0)
        losses = sum(1 for t in today_trades if t.get("net_pnl", 0) <= 0)
        total_pnl = sum(t.get("net_pnl", 0) for t in today_trades)

        return {
            "total_trades": len(today_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(today_trades) * 100) if today_trades else 0.0,
            "net_pnl": total_pnl,
        }

    def get_history(
        self,
        limit: int = 100,
        ticker: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """거래 내역 반환."""
        result = self._trades
        if ticker:
            result = [t for t in result if t.get("ticker") == ticker.upper()]
        return sorted(result, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]

    def close(self):
        """DB 저장 및 종료."""
        self._save()
        logger.info(f"[TradeDB] 저장 완료: {len(self._trades)}건")
