"""
nlp/en_sentiment.py — RossTrader_US

영어 감성 분석 모듈.
FinBERT 기반 뉴스 감성 점수화.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class SentimentResult:
    """감성 분석 결과."""
    def __init__(self, text: str, positive: float, negative: float, neutral: float):
        self.text = text
        self.positive = positive
        self.negative = negative
        self.neutral = neutral

    @property
    def score(self) -> float:
        """감성 점수 (-1.0 ~ 1.0)."""
        return self.positive - self.negative

    @property
    def label(self) -> str:
        if self.score > 0.3:
            return "positive"
        elif self.score < -0.3:
            return "negative"
        return "neutral"

    def __repr__(self) -> str:
        return f"SentimentResult(score={self.score:.3f}, label={self.label})"


class EnglishSentimentAnalyzer:
    """
    영어 감성 분석기.
    우선순위: 1. FinBERT 모델, 2. Rule-based fallback.
    """

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._model_loaded = False
        self._model_name = "ProsusAI/finbert"  # 금융 특화 BERT
        logger.info("[EN_Sentiment] 초기화 완료 (FinBERT lazy-load)")

    def _load_model(self) -> bool:
        """FinBERT 모델 로드 (lazy)."""
        if self._model_loaded:
            return True
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self._model_name, num_labels=3
            )
            self._model.eval()
            self._model_loaded = True
            logger.info("[EN_Sentiment] FinBERT 모델 로드 완료: %s", self._model_name)
            return True
        except Exception as e:
            logger.warning("[EN_Sentiment] FinBERT 로드 실패: %s — Rule-base fallback", e)
            self._model_loaded = False
            return False

    def analyze(self, text: str) -> SentimentResult:
        """텍스트 감성 분석."""
        if not text or not text.strip():
            return SentimentResult(text, 0.0, 0.0, 1.0)

        if self._load_model():
            return self._analyze_with_model(text)
        else:
            return self._analyze_with_rules(text)

    def analyze_batch(self, texts: List[str]) -> List[SentimentResult]:
        """여러 텍스트 배치 분석."""
        return [self.analyze(t) for t in texts]

    def _analyze_with_model(self, text: str) -> SentimentResult:
        """FinBERT 모델 분석."""
        try:
            import torch
            inputs = self._tokenizer(
                text, return_tensors="pt",
                truncation=True, max_length=512,
            )
            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

            # FinBERT: 0=positive, 1=negative, 2=neutral
            positive = float(probs[0][0])
            negative = float(probs[0][1])
            neutral = float(probs[0][2])

            return SentimentResult(text, positive, negative, neutral)
        except Exception as e:
            logger.error("[EN_Sentiment] 모델 분석 실패: %s", e)
            return self._analyze_with_rules(text)

    def _analyze_with_rules(self, text: str) -> SentimentResult:
        """Rule-based fallback 감성 분석."""
        text_lower = text.lower()

        positive_words = {
            "up", "rise", "gain", "profit", "growth", "positive", "upgrade",
            "buy", "strong", "bullish", "outperform", "beat", "surge",
            "approve", "launch", "partner", "contract", "award", "breakthrough",
        }
        negative_words = {
            "down", "fall", "drop", "loss", "decline", "negative", "downgrade",
            "sell", "weak", "bearish", "underperform", "miss", "plunge",
            "investigation", "lawsuit", "fine", "penalty", "recall", "delay",
        }

        words = set(text_lower.split())
        pos_count = len(words & positive_words)
        neg_count = len(words & negative_words)
        total = pos_count + neg_count

        if total == 0:
            return SentimentResult(text, 0.0, 0.0, 1.0)

        positive = pos_count / total if total > 0 else 0.0
        negative = neg_count / total if total > 0 else 0.0
        neutral = 1.0 - positive - negative
        if neutral < 0:
            neutral = 0.0

        return SentimentResult(text, positive, negative, neutral)
