"""
config/settings.py — RossTrader_US

Pydantic 기반 전체 설정 관리.
환경변수(.env) → Pydantic Settings → 전역 config 객체.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class KISSettings:
    """
    한국투자증권(KIS) 해외주식 API 설정.
    속성을 접근할 때마다 os.getenv()에서 직접 읽음 (lazy-load).
    """

    @property
    def app_key(self) -> str:
        return os.getenv("KIS_APP_KEY", "")

    @property
    def app_secret(self) -> str:
        return os.getenv("KIS_APP_SECRET", "")

    @property
    def account_no(self) -> str:
        return os.getenv("KIS_ACCOUNT_NO", "")

    @property
    def base_url(self) -> str:
        return os.getenv("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")

    @property
    def is_real(self) -> bool:
        return os.getenv("KIS_IS_REAL", "false").lower() == "true"

    @property
    def default_exchange(self) -> str:
        return os.getenv("KIS_EXCHANGE", "NASD")

    @property
    def is_paper(self) -> bool:
        """is_real의 반대 (모의투자 여부)."""
        return not self.is_real

    def __repr__(self) -> str:
        ak = self.app_key
        return (
            f"KISSettings(app_key={ak[:8] + '***' if ak else '(empty)'}, "
            f"is_real={self.is_real})"
        )

    __str__ = __repr__


class USSettings(BaseSettings):
    """미국 시장 기본 설정."""

    model_config = SettingsConfigDict(extra="ignore")

    default_exchange: str = Field(default="NASD", alias="US_DEFAULT_EXCHANGE")
    usd_krw_fallback: float = Field(default=1350.0, alias="USD_KRW_FALLBACK")
    max_order_usd: float = Field(default=500.0, alias="US_MAX_ORDER_USD")
    max_portfolio_pct: float = Field(default=0.40, alias="US_MAX_PORTFOLIO_PCT")
    stop_loss_pct: float = Field(default=2.0, alias="US_STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=3.5, alias="US_TAKE_PROFIT_PCT")
    trailing_stop_pct: float = Field(default=1.0, alias="US_TRAILING_STOP_PCT")


class FinnhubSettings:
    """
    Finnhub API 설정.
    os.getenv() 직접 읽기 (lazy-load). KISSettings와 동일 패턴.
    """

    @property
    def api_key(self) -> str:
        return os.getenv("FINNHUB_API_KEY", "")


class TelegramSettings(BaseSettings):
    """Telegram 알림 설정."""

    model_config = SettingsConfigDict(extra="ignore")

    token: str = Field(default="", alias="TELEGRAM_TOKEN")
    chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")


class WebMonitorSettings(BaseSettings):
    """웹 모니터 설정."""

    model_config = SettingsConfigDict(extra="ignore")

    port: int = Field(default=5000, alias="WEB_MONITOR_PORT")
    password: str = Field(default="", alias="WEB_MONITOR_PASSWORD")
    ngrok_token: str = Field(default="", alias="NGROK_TOKEN")


class AppSettings(BaseSettings):
    """RossTrader_US 전역 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 하위 설정 ──
    kis: KISSettings = KISSettings()
    us: USSettings = USSettings()
    finnhub: FinnhubSettings = FinnhubSettings()
    telegram: TelegramSettings = TelegramSettings()
    web_monitor: WebMonitorSettings = WebMonitorSettings()

    # ── 트레이딩 기본값 ──
    budget_usd: float = Field(default=1000.0, alias="BUDGET_USD")
    max_positions: int = Field(default=5, alias="MAX_POSITIONS")

    @property
    def is_real_trading(self) -> bool:
        return self.kis.is_real

    @property
    def mode_str(self) -> str:
        return "실거래" if self.kis.is_real else "모의투자(가상계좌)"


def _try_load_env() -> None:
    """.env 파일 로드 시도 (python-dotenv)."""
    try:
        from dotenv import load_dotenv

        # 프로젝트 루트의 .env 파일 로드
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
            logger.info("[Settings] .env 로드 완료: %s", env_path)
        else:
            logger.warning("[Settings] .env 파일 없음: %s", env_path)
    except ImportError:
        logger.warning("[Settings] python-dotenv 미설치 — 환경변수 로드 불가")


# ── 전역 설정 인스턴스 ──
_try_load_env()

try:
    settings = AppSettings()
    logger.info(
        "[Settings] 초기화 완료 | mode=%s | exchange=%s",
        settings.mode_str,
        settings.us.default_exchange,
    )
except Exception as e:
    logger.error("[Settings] 초기화 실패: %s", e)
    settings = AppSettings(_env_file=None)  # fallback


def get_settings() -> AppSettings:
    return settings
