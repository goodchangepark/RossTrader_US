"""
markets/us/options_flow_collector.py — RossTrader_US

옵션 플로우 데이터 수집기.
기관 투자자의 비정상적 옵션 거래 감지 → 가장 강력한 알파 소스 중 하나.

데이터 소스:
- Unusual Whales API (권장, 가장 포괄적)
- Tradier API (대안)
- Theta Data (대안)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OptionsFlowSignal:
    """옵션 플로우 신호."""
    symbol: str
    put_call_ratio: float = 1.0       # PCR < 0.5 = 강한 강세
    large_call_premium: float = 0.0    # 대형 콜 매수 프리미엄 ($)
    large_put_premium: float = 0.0     # 대형 풋 매수 프리미엄 ($)
    iv_rank: float = 50.0              # 내재 변동성 순위 (0~100)
    iv_percentile: float = 50.0
    gamma_exposure: float = 0.0        # 감마 익스포저 (+ = 풋 헷지, - = 콜 헷지)
    delta_exposure: float = 0.0
    max_pain: float = 0.0             # 최대 고통 가격
    unusual_call_count: int = 0
    unusual_put_count: int = 0
    score: float = 0.0                 # -1.0 ~ +1.0 통합 점수
    signal: str = "NEUTRAL"           # STRONG_BULLISH / BULLISH / NEUTRAL / BEARISH / STRONG_BEARISH


class OptionsFlowCollector:
    """
    옵션 플로우 데이터 수집기.
    Unusual Whales API를 통해 기관의 비정상적 옵션 거래 감지.

    API 키 설정 필요 (config.json 또는 환경변수):
    - UNUSUAL_WHALES_API_KEY
    """

    BASE_URL = "https://api.unusualwhales.com/api"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
        logger.info("[OptionsFlowCollector] 초기화 완료")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                timeout=15.0,
            )
        return self._client

    async def get_flow_data(self, symbol: str) -> OptionsFlowSignal:
        """
        특정 종목의 옵션 플로우 데이터 조회.

        Args:
            symbol: 종목 코드 (예: AAPL)

        Returns:
            OptionsFlowSignal
        """
        signal = OptionsFlowSignal(symbol=symbol)

        if not self.api_key:
            logger.debug("[OptionsFlow] API 키 없음, 더미 데이터 반환")
            return signal

        try:
            client = await self._get_client()

            # 1. 옵션 플로우 요약
            resp = await client.get(f"/flow/{symbol}")
            if resp.status_code == 200:
                data = resp.json()
                signal.put_call_ratio = data.get("put_call_ratio", 1.0)
                signal.large_call_premium = data.get("large_call_premium", 0)
                signal.large_put_premium = data.get("large_put_premium", 0)
                signal.unusual_call_count = data.get("unusual_call_count", 0)
                signal.unusual_put_count = data.get("unusual_put_count", 0)

            # 2. IV 데이터
            resp2 = await client.get(f"/options/{symbol}/greeks")
            if resp2.status_code == 200:
                data2 = resp2.json()
                signal.iv_rank = data2.get("iv_rank", 50)
                signal.iv_percentile = data2.get("iv_percentile", 50)
                signal.gamma_exposure = data2.get("gamma_exposure", 0)
                signal.delta_exposure = data2.get("delta_exposure", 0)
                signal.max_pain = data2.get("max_pain", 0)

            # 3. 통합 점수 계산
            signal.score = self._calculate_score(signal)
            signal.signal = self._classify_signal(signal.score)

            logger.info(
                "[OptionsFlow] %s | PCR=%.2f | IV Rank=%.0f%% | "
                "Unusual Call=%d Put=%d | Score=%.2f (%s)",
                symbol, signal.put_call_ratio, signal.iv_rank,
                signal.unusual_call_count, signal.unusual_put_count,
                signal.score, signal.signal,
            )

        except Exception as e:
            logger.warning("[OptionsFlow] %s 조회 실패: %s", symbol, e)

        return signal

    def _calculate_score(self, flow: OptionsFlowSignal) -> float:
        """
        옵션 플로우를 -1.0 ~ +1.0 통합 점수로 변환.

        양수 = 강세 신호 (콜 매수/풋 매도)
        음수 = 약세 신호 (풋 매수/콜 매도)
        """
        score = 0.0

        # PCR: < 0.5 = 강한 강세, > 1.5 = 강한 약세
        pcr = flow.put_call_ratio
        if pcr < 0.4:
            score += 0.4
        elif pcr < 0.6:
            score += 0.2
        elif pcr > 1.5:
            score -= 0.4
        elif pcr > 1.2:
            score -= 0.2

        # 비정상 콜 vs 풋 거래
        total_unusual = flow.unusual_call_count + flow.unusual_put_count
        if total_unusual > 0:
            call_ratio = flow.unusual_call_count / total_unusual
            if call_ratio > 0.7:
                score += 0.3
            elif call_ratio > 0.6:
                score += 0.15
            elif call_ratio < 0.3:
                score -= 0.3
            elif call_ratio < 0.4:
                score -= 0.15

        # 대형 프리미엄
        total_premium = flow.large_call_premium + flow.large_put_premium
        if total_premium > 1_000_000:  # $1M 이상이면 유의미
            if flow.large_call_premium > flow.large_put_premium * 2:
                score += 0.2
            elif flow.large_put_premium > flow.large_call_premium * 2:
                score -= 0.2

        # IV Rank: 80 이상 = 과열(풋 베팅), 20 이하 = 저평가(콜 베팅)
        if flow.iv_rank > 80:
            score -= 0.1
        elif flow.iv_rank < 20:
            score += 0.1

        # 바이어스 보정
        if flow.iv_percentile > 80 and flow.gamma_exposure < -100_000:
            score -= 0.1  # 고IV + 음감마 = 위험 신호

        return max(-1.0, min(1.0, round(score, 2)))

    @staticmethod
    def _classify_signal(score: float) -> str:
        if score >= 0.6:
            return "STRONG_BULLISH"
        elif score >= 0.2:
            return "BULLISH"
        elif score <= -0.6:
            return "STRONG_BEARISH"
        elif score <= -0.2:
            return "BEARISH"
        return "NEUTRAL"

    async def close(self):
        """HTTP 클라이언트 종료."""
        if self._client:
            await self._client.aclose()
            self._client = None
