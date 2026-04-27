"""
utils/trade_db.py — RossTrader_US

SQLite 기반 거래 내역 DB (v2.0).
TradeRecord dataclass로 진입/청산 사유, VIX, SPY 추세, 거래량 비율 등
메타데이터를 함께 저장하여 전략 분석 및 ML 피드백 가능.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "trades.db"


@dataclass
class TradeRecord:
    """상용 수준 거래 기록 — 분석/ML 피드백용 메타데이터 포함."""
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    side: str                     # 'long' / 'short'
    pnl: float
    pnl_pct: float
    entry_reason: str             # 'ORB' / 'GAP' / 'NEWS' / 'FACTOR' / 'MOMENTUM'
    exit_reason: str              # 'TRAILING_STOP' / 'TAKE_PROFIT' / 'STOP_LOSS' / 'TIME_STOP'
    news_sentiment_score: float = 0.0
    factor_score: float = 0.0
    vix_at_entry: float = 15.0
    spy_trend_at_entry: float = 0.0   # SPY 5일 기울기 (%)
    volume_ratio: float = 1.0         # 거래량 / 20일 평균
    market_regime: str = "UNKNOWN"    # 'BULL' / 'BEAR' / 'SIDEWAYS'
    commission_usd: float = 0.0
    hold_minutes: int = 0


def get_trade_db(path: str = "") -> "TradeDB":
    """TradeDB 싱글톤 인스턴스 반환."""
    return TradeDB(path or str(_DEFAULT_DB_PATH))


class TradeDB:
    """
    SQLite 기반 거래 내역 DB.
    기존 JSON 호환 인터페이스 유지 + SQLite 분석 기능 추가.
    스레드 안전 (threading.Lock).
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info("[TradeDB] SQLite DB 초기화 완료: %s", path)

    def _create_tables(self):
        """테이블 생성 (최초 1회)."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT NOT NULL,
                    entry_time      TEXT NOT NULL,
                    exit_time       TEXT NOT NULL,
                    entry_price     REAL NOT NULL,
                    exit_price      REAL NOT NULL,
                    quantity        INTEGER NOT NULL,
                    side            TEXT NOT NULL DEFAULT 'long',
                    pnl             REAL NOT NULL DEFAULT 0,
                    pnl_pct         REAL NOT NULL DEFAULT 0,
                    entry_reason    TEXT DEFAULT '',
                    exit_reason     TEXT DEFAULT '',
                    news_sentiment_score REAL DEFAULT 0,
                    factor_score    REAL DEFAULT 0,
                    vix_at_entry    REAL DEFAULT 15,
                    spy_trend_at_entry  REAL DEFAULT 0,
                    volume_ratio    REAL DEFAULT 1,
                    market_regime   TEXT DEFAULT 'UNKNOWN',
                    commission_usd  REAL DEFAULT 0,
                    hold_minutes    INTEGER DEFAULT 0,
                    created_at      TEXT DEFAULT (datetime('now'))
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol
                ON trades(symbol)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_entry_reason
                ON trades(entry_reason)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_market_regime
                ON trades(market_regime)
            """)
            self._conn.commit()

    # ── 쓰기 ─────────────────────────────────────────

    def add_trade(self, trade: Dict[str, Any]):
        """거래 기록 추가 (dict 호환)."""
        record = TradeRecord(
            symbol=trade.get("symbol", trade.get("ticker", "")),
            entry_time=trade.get("entry_time", datetime.now()),
            exit_time=trade.get("exit_time", datetime.now()),
            entry_price=float(trade.get("entry_price", 0)),
            exit_price=float(trade.get("exit_price", 0)),
            quantity=int(trade.get("quantity", trade.get("qty", 0))),
            side=trade.get("side", "long"),
            pnl=float(trade.get("pnl", trade.get("net_pnl", 0))),
            pnl_pct=float(trade.get("pnl_pct", trade.get("net_pnl_pct", 0))),
            entry_reason=trade.get("entry_reason", ""),
            exit_reason=trade.get("exit_reason", ""),
            news_sentiment_score=float(trade.get("news_sentiment_score", 0)),
            factor_score=float(trade.get("factor_score", 0)),
            vix_at_entry=float(trade.get("vix_at_entry", 15)),
            spy_trend_at_entry=float(trade.get("spy_trend_at_entry", 0)),
            volume_ratio=float(trade.get("volume_ratio", 1)),
            market_regime=trade.get("market_regime", "UNKNOWN"),
            commission_usd=float(trade.get("commission_usd", 0)),
            hold_minutes=int(trade.get("hold_minutes", 0)),
        )
        self._insert_record(record)

    def add_trade_record(self, record: TradeRecord) -> int:
        """TradeRecord 직접 추가 (권장)."""
        return self._insert_record(record)

    def _insert_record(self, record: TradeRecord) -> int:
        """내부 INSERT."""
        with self._lock:
            cursor = self._conn.execute("""
                INSERT INTO trades (
                    symbol, entry_time, exit_time,
                    entry_price, exit_price, quantity, side,
                    pnl, pnl_pct,
                    entry_reason, exit_reason,
                    news_sentiment_score, factor_score,
                    vix_at_entry, spy_trend_at_entry,
                    volume_ratio, market_regime,
                    commission_usd, hold_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.symbol,
                record.entry_time.isoformat() if isinstance(record.entry_time, datetime) else record.entry_time,
                record.exit_time.isoformat() if isinstance(record.exit_time, datetime) else record.exit_time,
                record.entry_price, record.exit_price, record.quantity,
                record.side, record.pnl, record.pnl_pct,
                record.entry_reason, record.exit_reason,
                record.news_sentiment_score, record.factor_score,
                record.vix_at_entry, record.spy_trend_at_entry,
                record.volume_ratio, record.market_regime,
                record.commission_usd, record.hold_minutes,
            ))
            self._conn.commit()
            return cursor.lastrowid

    # ── 읽기 ─────────────────────────────────────────

    def get_today_stats(self) -> Dict[str, Any]:
        """오늘 거래 통계 반환 (기존 JSON 호환)."""
        today = date.today().isoformat()
        with self._lock:
            row = self._conn.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(pnl), 0) as net_pnl,
                    COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
                    COALESCE(SUM(commission_usd), 0) as total_commission
                FROM trades
                WHERE entry_time >= ? AND entry_time < ?
            """, (today, date.today().isoformat()))

            r = row.fetchone()
            total = r["total_trades"] if r else 0
            wins = r["wins"] if r else 0
            net_pnl = r["net_pnl"] if r else 0.0

            return {
                "total_trades": total,
                "wins": wins,
                "losses": total - wins,
                "win_rate": (wins / total * 100) if total > 0 else 0.0,
                "net_pnl": net_pnl,
                "total_commission": r["total_commission"] if r else 0.0,
            }

    def get_history(
        self,
        limit: int = 100,
        ticker: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """거래 내역 반환 (기존 JSON 호환)."""
        with self._lock:
            if ticker:
                rows = self._conn.execute("""
                    SELECT * FROM trades
                    WHERE symbol = ?
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (ticker.upper(), limit))
            else:
                rows = self._conn.execute("""
                    SELECT * FROM trades
                    ORDER BY entry_time DESC
                    LIMIT ?
                """, (limit,))

            return [dict(r) for r in rows.fetchall()]

    # ── 분석 쿼리 (신규) ─────────────────────────────

    def get_strategy_analytics(self) -> pd.DataFrame:
        """전략별 성과 분석 — 어떤 진입 이유가 실제로 돈을 버는지 확인."""
        with self._lock:
            query = """
                SELECT
                    entry_reason,
                    market_regime,
                    COUNT(*) as trades,
                    ROUND(AVG(pnl_pct), 4) as avg_pnl_pct,
                    ROUND(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as win_rate,
                    ROUND(AVG(vix_at_entry), 1) as avg_vix,
                    ROUND(AVG(volume_ratio), 2) as avg_vol_ratio,
                    ROUND(AVG(factor_score), 1) as avg_factor_score,
                    ROUND(SUM(pnl), 2) as total_pnl
                FROM trades
                GROUP BY entry_reason, market_regime
                ORDER BY avg_pnl_pct DESC
            """
            return pd.read_sql_query(query, self._conn)

    def get_recent_trades_df(self, days: int = 30) -> pd.DataFrame:
        """최근 N일간 거래 데이터프레임 (ML 학습용)."""
        with self._lock:
            query = f"""
                SELECT * FROM trades
                WHERE entry_time >= datetime('now', '-{days} days')
                ORDER BY entry_time DESC
            """
            return pd.read_sql_query(query, self._conn)

    def get_trades_by_regime(self, regime: str) -> pd.DataFrame:
        """특정 시장 국면의 거래 데이터 (ML 학습용)."""
        with self._lock:
            query = """
                SELECT * FROM trades
                WHERE market_regime = ?
                ORDER BY entry_time DESC
            """
            return pd.read_sql_query(query, self._conn, params=(regime,))

    def get_feature_matrix(self) -> pd.DataFrame:
        """ML 학습용 피처 행렬 반환."""
        with self._lock:
            query = """
                SELECT
                    pnl_pct as target,
                    news_sentiment_score,
                    factor_score,
                    vix_at_entry,
                    spy_trend_at_entry,
                    volume_ratio,
                    CASE market_regime
                        WHEN 'BULL' THEN 1
                        WHEN 'SIDEWAYS' THEN 0
                        WHEN 'BEAR' THEN -1
                        ELSE 0
                    END as regime_num,
                    hold_minutes
                FROM trades
                WHERE pnl_pct != 0
            """
            return pd.read_sql_query(query, self._conn)

    # ── 유틸리티 ─────────────────────────────────────

    def get_total_trades(self) -> int:
        """전체 거래 건수."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()
            return row["cnt"] if row else 0

    def close(self):
        """DB 연결 종료."""
        try:
            self._conn.close()
            logger.info("[TradeDB] DB 연결 종료")
        except Exception as e:
            logger.warning("[TradeDB] 종료 오류: %s", e)
