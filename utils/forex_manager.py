"""
utils/forex_manager.py — RossTrader_US

환율 리스크 관리.
USD/KRW 환율 조회 (KIS API 또는 fallback).
"""

from __future__ import annotations

import logging
import time as time_mod
from typing import Optional

import requests

from config.settings import settings

logger = logging.getLogger(__name__)


class ForexManager:
    """
    USD/KRW 환율 관리자.

    우선순위:
    1. KIS API 환율 조회
    2. .env 설정값 (USD_KRW_FALLBACK)
    """

    def __init__(self):
        self._cached_rate: Optional[float] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 3600.0  # 1시간 캐시

    def get_usd_krw(self, force_refresh: bool = False) -> float:
        """
        USD/KRW 환율 조회.

        Args:
            force_refresh: 캐시 무시하고 강제 조회

        Returns:
            float: USD 1달러당 KRW 환율
        """
        if not force_refresh and self._cached_rate is not None:
            if time_mod.time() - self._cache_time < self._cache_ttl:
                return self._cached_rate

        rate = self._fetch_from_kis()
        if rate is not None and rate > 0:
            self._cached_rate = rate
            self._cache_time = time_mod.time()
            logger.info("[ForexManager] 환율 갱신: 1 USD = %.2f KRW (KIS API)", rate)
            return rate

        fallback = settings.us.usd_krw_fallback
        logger.warning(
            "[ForexManager] KIS API 환율 조회 실패 — fallback 사용: %.2f KRW", fallback
        )
        self._cached_rate = fallback
        self._cache_time = time_mod.time()
        return fallback

    def _fetch_from_kis(self) -> Optional[float]:
        """KIS API 환율 조회."""
        try:
            base_url = settings.kis.base_url
            url = f"{base_url}/uapi/overseas-stock/v1/trading/inquire-rates"
            headers = {
                "Content-Type": "application/json",
                "tr_id": "HHDFS76200200",
            }
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            # KIS 응답 구조에 따라 조정 필요
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                rate = float(output.get("fwd_rtt", 0))
                if rate > 0:
                    return rate
        except Exception as e:
            logger.debug("[ForexManager] KIS 환율 조회 실패: %s", e)
        return None

    def usd_to_krw(self, usd_amount: float) -> float:
        """USD → KRW 변환."""
        rate = self.get_usd_krw()
        return usd_amount * rate

    def krw_to_usd(self, krw_amount: float) -> float:
        """KRW → USD 변환."""
        rate = self.get_usd_krw()
        return krw_amount / rate if rate > 0 else 0.0

    @property
    def current_rate(self) -> float:
        """현재 캐시된 환율 (없으면 fallback)."""
        if self._cached_rate is not None:
            return self._cached_rate
        return settings.us.usd_krw_fallback
