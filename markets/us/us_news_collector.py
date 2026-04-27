"""
markets/us/us_news_collector.py — RossTrader_US

미국 주식 뉴스 수집기.
소스 우선순위:
  1. Finnhub API (무료, 분당 60콜) → 실시간 뉴스
  2. SEC EDGAR RSS → 공시 (8-K, 10-Q 등)
  3. Yahoo Finance RSS → 보조 뉴스
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
TZ_ET = ZoneInfo("America/New_York")


@dataclass
class USNewsItem:
    """미국 주식 뉴스 아이템."""
    title: str
    summary: str
    ticker: str
    source: str               # "finnhub" / "edgar" / "yahoo"
    published_at: datetime    # ET timezone-aware
    received_at: datetime = field(default_factory=lambda: datetime.now(TZ_ET))
    url: str = ""
    category: str = "general"  # "earnings" / "merger" / "analyst" 등
    is_edgar: bool = False
    text_hash: str = ""

    def __post_init__(self):
        if not self.text_hash:
            self.text_hash = hashlib.sha256(
                (self.title + self.ticker).encode()
            ).hexdigest()[:16]

    @property
    def freshness_seconds(self) -> float:
        """뉴스 신선도 (수신 후 경과 초)."""
        return (datetime.now(TZ_ET) - self.received_at).total_seconds()

    @property
    def full_text(self) -> str:
        return f"{self.title}. {self.summary}"


class FinnhubNewsCollector:
    """
    Finnhub API 기반 미국 주식 뉴스 수집.
    무료 플랜: 분당 60 API 콜.
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self):
        from config.settings import settings
        self.api_key = settings.finnhub.api_key
        if not self.api_key:
            logger.warning("[FinnhubNews] FINNHUB_API_KEY 미설정. 뉴스 수집 불가.")
        self._seen_hashes: set = set()

    def get_company_news(self, ticker: str, days_back: int = 1) -> List[USNewsItem]:
        """종목별 최신 뉴스 조회."""
        if not self.api_key:
            return []

        today = datetime.now(TZ_ET).date()
        from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        url = f"{self.BASE_URL}/company-news"
        params = {
            "symbol": ticker.upper(),
            "from": from_date,
            "to": to_date,
            "token": self.api_key,
        }

        try:
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            raw_list = resp.json()

            items = []
            for raw in raw_list[:20]:
                item = self._parse_item(raw, ticker)
                if item and item.text_hash not in self._seen_hashes:
                    self._seen_hashes.add(item.text_hash)
                    items.append(item)
            return items
        except Exception as e:
            logger.error("[FinnhubNews] %s 뉴스 조회 실패: %s", ticker, e)
            return []

    def get_market_news(self, category: str = "general") -> List[USNewsItem]:
        """전체 시장 뉴스."""
        if not self.api_key:
            return []

        url = f"{self.BASE_URL}/news"
        params = {"category": category, "token": self.api_key}
        try:
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            items = []
            for raw in resp.json()[:10]:
                item = self._parse_item(raw, "MARKET")
                if item:
                    items.append(item)
            return items
        except Exception as e:
            logger.error("[FinnhubNews] 시장 뉴스 조회 실패: %s", e)
            return []

    @staticmethod
    def _parse_item(raw: dict, ticker: str) -> Optional[USNewsItem]:
        try:
            published_ts = raw.get("datetime", 0)
            published_at = datetime.fromtimestamp(published_ts, tz=TZ_ET)
            return USNewsItem(
                title=raw.get("headline", ""),
                summary=raw.get("summary", ""),
                ticker=ticker,
                source="finnhub",
                published_at=published_at,
                url=raw.get("url", ""),
                category=raw.get("category", "general"),
            )
        except Exception:
            return None


class SECEdgarCollector:
    """
    SEC EDGAR RSS 기반 공시 수집.
    8-K (수시공시), 10-Q (분기보고서), 10-K (연간보고서)
    """

    EDGAR_RSS = "https://www.sec.gov/cgi-bin/browse-edgar"
    HEADERS = {"User-Agent": "RossTrader research@example.com"}

    def get_filings(self, ticker: str, form_type: str = "8-K") -> List[USNewsItem]:
        """SEC 공시 수집."""
        params = {
            "action": "getcompany",
            "company": ticker,
            "type": form_type,
            "dateb": "",
            "owner": "include",
            "count": "5",
            "output": "atom",
        }
        try:
            resp = requests.get(
                self.EDGAR_RSS, params=params, headers=self.HEADERS, timeout=10
            )
            resp.raise_for_status()
            return self._parse_rss(resp.text, ticker, form_type)
        except Exception as e:
            logger.error("[SECEdgar] %s %s 수집 실패: %s", ticker, form_type, e)
            return []

    @staticmethod
    def _parse_rss(xml_text: str, ticker: str, form_type: str) -> List[USNewsItem]:
        """RSS XML 파싱."""
        import xml.etree.ElementTree as ET
        items = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:5]:
                title = entry.findtext("atom:title", "", ns)
                updated = entry.findtext("atom:updated", "", ns)
                link_el = entry.find("atom:link", ns)
                url = link_el.attrib.get("href", "") if link_el else ""

                try:
                    pub_at = datetime.fromisoformat(
                        updated.replace("Z", "+00:00")
                    ).astimezone(TZ_ET)
                except Exception:
                    pub_at = datetime.now(TZ_ET)

                items.append(USNewsItem(
                    title=f"[SEC {form_type}] {ticker}: {title}",
                    summary=f"SEC {form_type} 공시 제출",
                    ticker=ticker,
                    source="edgar",
                    published_at=pub_at,
                    url=url,
                    category="earnings" if form_type in ("10-Q", "10-K") else "general",
                    is_edgar=True,
                ))
        except Exception as e:
            logger.error("[SECEdgar] RSS 파싱 실패: %s", e)
        return items


class USNewsAggregator:
    """
    미국 주식 뉴스 통합 수집기.
    Finnhub + SEC EDGAR 통합.
    """

    def __init__(self):
        self.finnhub = FinnhubNewsCollector()
        self.edgar = SECEdgarCollector()
        self._dedup_cache: set = set()

    def collect(self, tickers: List[str]) -> List[USNewsItem]:
        """
        지정된 종목 리스트의 뉴스를 모두 수집.
        최신순 정렬, 중복 제거 후 반환.
        """
        all_items: List[USNewsItem] = []

        for ticker in tickers:
            news = self.finnhub.get_company_news(ticker, days_back=1)
            all_items.extend(news)

            filings = self.edgar.get_filings(ticker, form_type="8-K")
            all_items.extend(filings)

            time.sleep(0.1)

        # 중복 제거
        unique_items = []
        for item in all_items:
            if item.text_hash not in self._dedup_cache:
                self._dedup_cache.add(item.text_hash)
                unique_items.append(item)

        # 캐시 크기 제한
        if len(self._dedup_cache) > 1000:
            self._dedup_cache = set(list(self._dedup_cache)[-500:])

        return sorted(unique_items, key=lambda x: x.published_at, reverse=True)
