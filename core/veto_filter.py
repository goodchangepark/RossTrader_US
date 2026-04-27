"""
core/veto_filter.py — RossTrader_US

부정 이벤트 차단 (Veto) 필터.
뉴스 기반 강한 이벤트 감지 및 runner 차단.
기존 RossTrader veto_filter.py 로직 참고, 미국 키워드 적용.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from config.constants import (
    STRONG_EVENT_TYPES,
    EVENT_TYPE_PATTERNS,
)

logger = logging.getLogger(__name__)


class VetoFilter:
    """
    부정 이벤트 차단 필터.
    뉴스에서 강한 이벤트(계약체결, 실적호전, 승인, 자사주매입)를 감지하여
    runner 진입을 차단하거나 허용.

    사용 예:
        veto = VetoFilter()
        result = veto.check("AAPL", "Apple announces $10B buyback")
        if result["is_strong_event"]:
            print("강한 이벤트! runner 차단")
    """

    def __init__(self):
        # 패턴 컴파일 (대소문자 구분 없이)
        self._compiled: Dict[str, List[re.Pattern]] = {}
        for event_type, patterns in EVENT_TYPE_PATTERNS.items():
            self._compiled[event_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def check(self, ticker: str, news_text: str) -> dict:
        """
        뉴스 텍스트에 대해 veto 체크.

        Returns:
            {
                "is_strong_event": bool,
                "event_types": [str],
                "matched_patterns": [str],
                "should_block": bool
            }
        """
        result = {
            "is_strong_event": False,
            "event_types": [],
            "matched_patterns": [],
            "should_block": False,
        }

        for event_type, patterns in self._compiled.items():
            for pattern in patterns:
                if pattern.search(news_text):
                    if event_type not in result["event_types"]:
                        result["event_types"].append(event_type)
                    result["matched_patterns"].append(pattern.pattern)
                    result["is_strong_event"] = True
                    logger.info(
                        "[VetoFilter] 강한 이벤트 감지 | %s | type=%s | pattern=%s",
                        ticker, event_type, pattern.pattern,
                    )

        # 강한 이벤트면 runner 차단 (should_block = True)
        if result["is_strong_event"]:
            result["should_block"] = True

        return result

    def is_blocked(self, ticker: str, news_text: str) -> bool:
        """차단 여부만 빠르게 확인."""
        return self.check(ticker, news_text)["should_block"]

    def get_strong_event_types(self, ticker: str, news_text: str) -> List[str]:
        """감지된 강한 이벤트 타입 반환."""
        return self.check(ticker, news_text)["event_types"]
