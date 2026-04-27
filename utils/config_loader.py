"""
utils/config_loader.py — RossTrader_US

설정 로더.
Pydantic settings 객체를 dict 형태로도 사용할 수 있게 래핑.
기존 RossTrader utils/config_loader.py 참고.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from config.settings import settings as _pydantic_settings

logger = logging.getLogger(__name__)

# ── config.json 경로 (GUI 설정 저장용) ─────────────────
_CONFIG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_JSON_PATH = os.path.join(_CONFIG_DIR, "config.json")


def get_pydantic_settings() -> Any:
    """Pydantic AppSettings 객체 반환."""
    return _pydantic_settings


def to_dict() -> Dict[str, Any]:
    """설정을 dict로 변환."""
    s = _pydantic_settings
    return {
        "kis": {
            "app_key": s.kis.app_key,
            "app_secret": "***MASKED***",
            "account_no": s.kis.account_no,
            "base_url": s.kis.base_url,
            "is_real": s.kis.is_real,
        },
        "us": {
            "default_exchange": s.us.default_exchange,
            "usd_krw_fallback": s.us.usd_krw_fallback,
            "max_order_usd": s.us.max_order_usd,
            "max_portfolio_pct": s.us.max_portfolio_pct,
            "stop_loss_pct": s.us.stop_loss_pct,
            "take_profit_pct": s.us.take_profit_pct,
            "trailing_stop_pct": s.us.trailing_stop_pct,
        },
        "finnhub": {
            "api_key": "***MASKED***" if s.finnhub.api_key else "",
        },
        "telegram": {
            "token": "***MASKED***" if s.telegram.token else "",
            "chat_id": s.telegram.chat_id,
        },
        "web_monitor": {
            "port": s.web_monitor.port,
        },
        "budget_usd": s.budget_usd,
        "max_positions": s.max_positions,
        "is_real": s.is_real_trading,
        "mode": s.mode_str,
    }


# ═══════════════════════════════════════════════════════════
# config.json 로드/저장 (GUI 설정과 동기화)
# ═══════════════════════════════════════════════════════════

def load_config(path: str = "") -> Dict[str, Any]:
    """
    config.json 파일 로드.
    파일이 없으면 Pydantic 설정 기반 기본값 반환.
    """
    target = path or CONFIG_JSON_PATH
    if not os.path.exists(target):
        logger.info("[ConfigLoader] config.json 없음 — 기본 설정 사용: %s", target)
        return _default_config()

    try:
        with open(target, "r", encoding="utf-8") as f:
            cfg: Dict[str, Any] = json.load(f)
        logger.info("[ConfigLoader] config.json 로드 완료: %s", target)
        return cfg
    except Exception as e:
        logger.warning("[ConfigLoader] config.json 로드 실패: %s — 기본 설정 사용", e)
        return _default_config()


def save_config(cfg: Dict[str, Any], path: str = "") -> bool:
    """config.json 파일 저장."""
    target = path or CONFIG_JSON_PATH
    try:
        with open(target, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        logger.info("[ConfigLoader] config.json 저장 완료: %s", target)
        return True
    except Exception as e:
        logger.error("[ConfigLoader] config.json 저장 실패: %s", e)
        return False


def _default_config() -> Dict[str, Any]:
    """Pydantic 설정 기반 기본 config.json 내용."""
    s = _pydantic_settings
    return {
        "kis": {
            "app_key": s.kis.app_key,
            "app_secret": s.kis.app_secret,
            "account_no": s.kis.account_no,
            "base_url": s.kis.base_url,
            "is_real": s.kis.is_real,
        },
        "us": {
            "default_exchange": s.us.default_exchange,
            "usd_krw_fallback": s.us.usd_krw_fallback,
            "max_order_usd": s.us.max_order_usd,
            "max_portfolio_pct": s.us.max_portfolio_pct,
            "stop_loss_pct": s.us.stop_loss_pct,
            "take_profit_pct": s.us.take_profit_pct,
            "trailing_stop_pct": s.us.trailing_stop_pct,
        },
        "finnhub": {
            "api_key": s.finnhub.api_key,
        },
        "telegram": {
            "token": s.telegram.token,
            "chat_id": s.telegram.chat_id,
        },
        "trade": {
            "budget": s.budget_usd,
            "max_positions": s.max_positions,
            "level": 3,
            "auto_run": False,
            "schedule": {
                "enabled": False,
                "start_time": "23:30",
                "end_time": "06:00",
                "days": [0, 1, 2, 3, 4],
            },
        },
        "news": {
            "min_score": 70,
            "strong_score": 90,
            "finnhub_enabled": True,
            "edgar_enabled": True,
        },
        "profit_v13b": {
            "enabled": True,
        },
    }
