"""
nlp/finbert_scorer.py — RossTrader_US

FinBERT 기반 감성 점수화 유틸리티.
뉴스 → 감성 점수 변환.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from nlp.en_sentiment import EnglishSentimentAnalyzer, SentimentResult

logger = logging.getLogger(__name__)


class FinBERTScorer:
    """
    FinBERT 감성 점수화.
    뉴스 아이템을 받아 감성 점수 반환.
    """

    def __init__(self):
        self.analyzer = EnglishSentimentAnalyzer()
        logger.info("[FinBERTScorer] 초기화 완료")

    def score_news(self, title: str, summary: str = "") -> dict:
        """
        뉴스 감성 점수화.

        Returns:
            {
                "score": float,       # -1.0 ~ 1.0
                "label": str,         # positive/negative/neutral
                "positive": float,
                "negative": float,
                "neutral": float,
            }
        """
        text = f"{title}. {summary}" if summary else title
        result = self.analyzer.analyze(text)
        return {
            "score": result.score,
            "label": result.label,
            "positive": result.positive,
            "negative": result.negative,
            "neutral": result.neutral,
        }

    def score_news_batch(self, news_items: List[dict]) -> List[dict]:
        """배치 뉴스 감성 점수화."""
        results = []
        for item in news_items:
            title = item.get("title", "")
            summary = item.get("summary", "")
            score = self.score_news(title, summary)
            results.append({**item, "sentiment": score})
        return results
