"""
nlp/news_processor.py — RossTrader_US

뉴스 전처리기.
뉴스 정규화, 토큰화, 키워드 추출.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

from nlp.finbert_scorer import FinBERTScorer

logger = logging.getLogger(__name__)


class NewsProcessor:
    """
    뉴스 전처리기.
    - 텍스트 정규화
    - 키워드 추출
    - 감성 분석 연동
    """

    def __init__(self):
        self.scorer = FinBERTScorer()

    def process(self, title: str, summary: str = "", ticker: str = "") -> dict:
        """
        뉴스 아이템 처리.

        Returns:
            {
                "title": str,
                "summary": str,
                "ticker": str,
                "keywords": [str],
                "sentiment": {...},
            }
        """
        clean_title = self._clean_text(title)
        clean_summary = self._clean_text(summary) if summary else ""
        keywords = self._extract_keywords(clean_title + " " + clean_summary)
        sentiment = self.scorer.score_news(clean_title, clean_summary)

        return {
            "title": clean_title,
            "summary": clean_summary,
            "ticker": ticker,
            "keywords": keywords,
            "sentiment": sentiment,
        }

    def process_batch(self, news_items: List[Dict]) -> List[Dict]:
        """배치 처리."""
        return [self.process(
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            ticker=item.get("ticker", ""),
        ) for item in news_items]

    @staticmethod
    def _clean_text(text: str) -> str:
        """텍스트 정규화."""
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text

    @staticmethod
    def _extract_keywords(text: str, max_count: int = 10) -> List[str]:
        """키워드 추출 (빈도 기반)."""
        # 불용어
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "is", "are", "was", "were", "be",
            "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "this", "that", "these", "those", "it", "its", "they", "them",
        }

        words = re.findall(r"[A-Za-z]{2,}", text.lower())
        freq: Dict[str, int] = {}
        for word in words:
            if word not in stopwords:
                freq[word] = freq.get(word, 0) + 1

        sorted_words = sorted(freq.items(), key=lambda x: -x[1])
        return [word for word, _ in sorted_words[:max_count]]
