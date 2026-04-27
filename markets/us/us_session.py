"""
markets/us/us_session.py — RossTrader_US

미국 주식 시장 세션 관리.
- 한국 시간(KST) ↔ 미국 동부 시간(ET) 변환
- 정규장 / 프리마켓 / 애프터마켓 판별
- 거래 가능 여부 판단 (KIS API는 정규장만 지원)
- ORB 기준 시간 계산 (ET 9:30~10:30)
- 장 마감 강제 청산 시각
"""

from __future__ import annotations

import logging
from datetime import datetime, time, date, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 타임존 상수
TZ_KST = ZoneInfo("Asia/Seoul")
TZ_ET = ZoneInfo("America/New_York")


class USMarketSession(Enum):
    """미국 시장 세션 구분."""
    PRE_MARKET = "pre_market"      # 프리마켓 ET 04:00~09:30
    REGULAR = "regular"            # 정규장 ET 09:30~16:00
    AFTER_HOURS = "after_hours"    # 애프터마켓 ET 16:00~20:00
    CLOSED = "closed"              # 휴장


class USMarketSessionManager:
    """
    미국 주식 시장 세션 관리자.

    사용 예:
        mgr = USMarketSessionManager()
        print(mgr.current_session())       # USMarketSession.REGULAR
        print(mgr.is_regular_open())       # True
        print(mgr.orb_end_time_kst())      # (한국시간 문자열)
        print(mgr.now_et())                # ET 현재 시각
    """

    # ── 정규장 시간 (ET) ──
    REGULAR_OPEN = time(9, 30)
    REGULAR_CLOSE = time(16, 0)

    # ── 프리마켓 (ET) ──
    PRE_OPEN = time(4, 0)
    PRE_CLOSE = time(9, 30)

    # ── 애프터마켓 (ET) ──
    AFTER_OPEN = time(16, 0)
    AFTER_CLOSE = time(20, 0)

    # ── ORB 범위 (ET) ──
    ORB_START = time(9, 30)
    ORB_END = time(10, 30)

    # ── 강제 청산 시각 (ET, 장 마감 10분 전) ──
    FORCE_FLAT_TIME = time(15, 50)

    # ── 미국 휴장일 (2025~2026, ET 기준) ──
    US_HOLIDAYS = {
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }

    def now_et(self) -> datetime:
        """현재 ET 시각."""
        return datetime.now(TZ_ET)

    def now_kst(self) -> datetime:
        """현재 KST 시각."""
        return datetime.now(TZ_KST)

    def et_to_kst(self, et_time: datetime) -> datetime:
        """ET → KST 변환."""
        return et_time.astimezone(TZ_KST)

    def kst_to_et(self, kst_time: datetime) -> datetime:
        """KST → ET 변환."""
        return kst_time.astimezone(TZ_ET)

    def is_us_holiday(self, check_date: date | None = None) -> bool:
        """미국 휴장일 여부 (ET 기준 날짜)."""
        if check_date is None:
            check_date = self.now_et().date()
        return check_date in self.US_HOLIDAYS

    def is_weekday(self, check_date: date | None = None) -> bool:
        """ET 기준 평일 여부."""
        if check_date is None:
            check_date = self.now_et().date()
        return check_date.weekday() < 5

    def current_session(self) -> USMarketSession:
        """현재 시장 세션 반환."""
        now_et = self.now_et()

        # 주말/휴장일
        if not self.is_weekday(now_et.date()) or self.is_us_holiday(now_et.date()):
            return USMarketSession.CLOSED

        t = now_et.time()

        if self.REGULAR_OPEN <= t < self.REGULAR_CLOSE:
            return USMarketSession.REGULAR
        elif self.PRE_OPEN <= t < self.PRE_CLOSE:
            return USMarketSession.PRE_MARKET
        elif self.AFTER_OPEN <= t < self.AFTER_CLOSE:
            return USMarketSession.AFTER_HOURS
        else:
            return USMarketSession.CLOSED

    def is_regular_open(self) -> bool:
        """정규장 거래 가능 여부 (KIS API 지원 시간)."""
        return self.current_session() == USMarketSession.REGULAR

    def is_tradeable(self) -> bool:
        """
        KIS API 기준 거래 가능 여부.
        KIS는 미국 정규장만 지원하므로 REGULAR만 True.
        """
        return self.is_regular_open()

    def minutes_to_open(self) -> int:
        """정규장 시작까지 남은 분 (정규장 중이면 0)."""
        now_et = self.now_et()
        if self.is_regular_open():
            return 0
        open_today = now_et.replace(
            hour=self.REGULAR_OPEN.hour,
            minute=self.REGULAR_OPEN.minute,
            second=0, microsecond=0,
        )
        if now_et > open_today:
            open_today += timedelta(days=1)
        diff = (open_today - now_et).total_seconds() / 60
        return max(0, int(diff))

    def minutes_since_open(self) -> int:
        """정규장 시작 후 경과 분 (장 미시작이면 -1)."""
        if not self.is_regular_open():
            return -1
        now_et = self.now_et()
        open_today = now_et.replace(
            hour=self.REGULAR_OPEN.hour,
            minute=self.REGULAR_OPEN.minute,
            second=0, microsecond=0,
        )
        return int((now_et - open_today).total_seconds() / 60)

    def is_orb_period(self) -> bool:
        """ORB 기간 여부 (ET 9:30~10:30)."""
        now_et = self.now_et()
        if not self.is_regular_open():
            return False
        t = now_et.time()
        return self.ORB_START <= t <= self.ORB_END

    def orb_end_time_kst(self) -> str:
        """ORB 종료 시각을 KST 문자열로 반환 (표시용)."""
        now_et = self.now_et()
        orb_end_et = now_et.replace(
            hour=self.ORB_END.hour,
            minute=self.ORB_END.minute,
            second=0, microsecond=0,
        )
        orb_end_kst = self.et_to_kst(orb_end_et)
        return orb_end_kst.strftime("%H:%M KST")

    def force_flat_time_kst(self) -> str:
        """강제 청산 시각을 KST 문자열로 반환."""
        now_et = self.now_et()
        flat_et = now_et.replace(
            hour=self.FORCE_FLAT_TIME.hour,
            minute=self.FORCE_FLAT_TIME.minute,
            second=0, microsecond=0,
        )
        flat_kst = self.et_to_kst(flat_et)
        return flat_kst.strftime("%H:%M KST")

    def should_force_flat(self) -> bool:
        """장 마감 10분 전 강제 청산 여부."""
        now_et = self.now_et()
        if not self.is_regular_open():
            return False
        t = now_et.time()
        return t >= self.FORCE_FLAT_TIME

    def session_summary(self) -> dict:
        """현재 세션 요약 (GUI 표시용)."""
        session = self.current_session()
        return {
            "session": session.value,
            "is_tradeable": self.is_tradeable(),
            "now_et": self.now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
            "now_kst": self.now_kst().strftime("%Y-%m-%d %H:%M:%S KST"),
            "minutes_since_open": self.minutes_since_open(),
            "is_orb_period": self.is_orb_period(),
            "should_force_flat": self.should_force_flat(),
            "force_flat_kst": self.force_flat_time_kst(),
            "orb_end_kst": self.orb_end_time_kst(),
        }


# 전역 싱글톤
us_session = USMarketSessionManager()
