"""
gui/main_window_controller.py — RossTrader_US

메인 윈도우 컨트롤러.
비즈니스 로직을 View에서 분리하여 관리.
기존 RossTrader gui/main_window_controller.py 참고.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from utils.config_loader import load_config as _loader_load_config, save_config as _loader_save_config

logger = logging.getLogger(__name__)


class MainWindowController:
    """
    메인 윈도우 컨트롤러.
    - 설정 로드/저장
    - 자동매매 시작/정지 (TradingEngine)
    - 상태 조회
    """

    def __init__(self, view=None):
        self._view = view
        self._trader = None
        self._engine = None
        self._config: dict = {}
        self._wfl_applied_at: Optional[datetime] = None
        self._web_started = False

    def load_config(self, path: str = "") -> dict:
        """설정 로드."""
        try:
            cfg = _loader_load_config()
            self._config = cfg
            logger.info("[Controller] config 로드 완료")
            return cfg
        except Exception as e:
            logger.error("[Controller] config 로드 오류: %s", e)
            return {}

    def save_config(self, cfg: dict, path: str = "") -> bool:
        """설정 저장."""
        try:
            result = _loader_save_config(cfg)
            if result:
                self._config = cfg
                logger.info("[Controller] config 저장 완료")
            return result
        except Exception as e:
            logger.error("[Controller] config 저장 오류: %s", e)
            return False

    def apply_settings(self, settings: dict) -> dict:
        """설정 적용."""
        self._config.update(settings)
        return self._config

    def start_trader(self, cfg: dict, broker, news_collector) -> bool:
        """자동매매 시작."""
        if self._trader and getattr(self._trader, "_running", False):
            logger.warning("[Controller] 이미 자동매매 실행 중")
            return False
        if self._trader and self._trader.isRunning():
            logger.warning("[Controller] NewsTraderThread가 이미 실행 중")
            return False

        try:
            from utils.news_trader import NewsTraderThread
            self._trader = NewsTraderThread(
                cfg=cfg, broker=broker,
                news_collector=news_collector,
                settings=cfg.get("settings", {}),
            )
            if self._view:
                try:
                    self._trader.log_signal.connect(self._view._on_log)
                except Exception:
                    pass
                try:
                    self._trader.trade_signal.connect(self._view._on_trade_signal)
                except Exception:
                    pass
            self._trader.start()
            logger.info("[Controller] 자동매매 시작")
            return True
        except Exception as e:
            logger.error("[Controller] 자동매매 시작 오류: %s", e)
            return False

    def stop_trader(self) -> bool:
        """자동매매 중지."""
        if not self._trader:
            return False
        try:
            self._trader.stop()
            logger.info("[Controller] 자동매매 중단 요청")
            return True
        except Exception as e:
            logger.error("[Controller] 자동매매 중단 오류: %s", e)
            return False

    @property
    def is_running(self) -> bool:
        """실행 중 여부."""
        return bool(self._trader and getattr(self._trader, "_running", False))

    def apply_level_preset(self, level: int) -> dict:
        """전략 레벨 preset 적용."""
        try:
            self._config.setdefault("trade", {}).update({
                "level": level,
            })
            self._config.setdefault("settings", {})["level"] = level
            logger.info("[Controller] 레벨 %d 적용", level)
        except Exception as e:
            logger.warning("[Controller] 레벨 적용 오류: %s", e)
        return self._config

    def start_engine(self, broker=None, news_collector=None) -> bool:
        """TradingEngine 시작."""
        try:
            from core.trading_engine import TradingEngine, reset_trading_engine
            reset_trading_engine()

            def _on_log(msg):
                if self._view and hasattr(self._view, "_on_log"):
                    try:
                        self._view._on_log(msg)
                    except Exception:
                        pass

            def _on_trade(info):
                if self._view and hasattr(self._view, "_on_trade_signal"):
                    try:
                        self._view._on_trade_signal(info)
                    except Exception:
                        pass

            def _on_status(status):
                if self._view and hasattr(self._view, "_on_engine_status"):
                    try:
                        self._view._on_engine_status(status)
                    except Exception:
                        pass

            self._engine = TradingEngine(
                cfg=self._config,
                broker=broker,
                news_collector=news_collector,
                on_log=_on_log,
                on_trade=_on_trade,
                on_status=_on_status,
            )
            result = self._engine.start()
            if result:
                logger.info("[Controller] TradingEngine 시작 완료")
            return result
        except Exception as e:
            logger.error("[Controller] TradingEngine 시작 오류: %s", e)
            return False

    def stop_engine(self) -> bool:
        """TradingEngine 중단."""
        engine = getattr(self, "_engine", None)
        if engine:
            engine.stop()
            logger.info("[Controller] TradingEngine 중단")
            return True
        return False

    def poll_engine(self) -> list:
        """IPC 큐 드레인."""
        engine = getattr(self, "_engine", None)
        if engine:
            return engine.drain()
        return []

    def get_today_stats(self) -> dict:
        """오늘 통계 조회."""
        try:
            from utils.trade_db import get_trade_db
            db = get_trade_db()
            stats = db.get_today_stats()
            db.close()
            return stats
        except Exception as e:
            logger.warning("[Controller] 오늘 통계 조회 오류: %s", e)
            return {}
