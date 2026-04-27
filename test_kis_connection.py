#!/usr/bin/env python3
"""
test_kis_connection.py — RossTrader_US

한국투자증권(KIS) 해외주식 API 연결 테스트.
실제 API 호출 없이 설정 및 객체 초기화만 테스트하려면 '--dry-run'을 인자로 전달하세요.

사용법:
    python test_kis_connection.py --dry-run     # 설정 검증만
    python test_kis_connection.py                # 실제 API 연결 테스트
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.abspath("."))

import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

from config.settings import settings


def test_dry_run():
    """설정 검증만 수행 (API 호출 없음)."""
    print("=" * 60)
    print("  한국투자증권(KIS) API 설정 검증 (dry-run)")
    print("=" * 60)

    print(f"\n  KIS_APP_KEY:     {settings.kis.app_key[:8] + '****' if settings.kis.app_key else '(EMPTY)'}")
    print(f"  KIS_APP_SECRET:  {'*' * 16 if settings.kis.app_secret else '(EMPTY)'}")
    print(f"  KIS_ACCOUNT_NO:  {settings.kis.account_no}")
    print(f"  KIS_BASE_URL:    {settings.kis.base_url}")
    print(f"  KIS_IS_REAL:     {settings.kis.is_real}")
    print(f"  KIS_EXCHANGE:    {settings.kis.default_exchange}")

    if not settings.kis.app_key or "your_kis" in settings.kis.app_key:
        print("\n  ❌ KIS_APP_KEY가 설정되지 않았거나 기본값입니다.")
        print("     .env 파일에 실제 KIS 앱키를 설정하세요.")
        return False

    if not settings.kis.app_secret:
        print("\n  ❌ KIS_APP_SECRET이 설정되지 않았습니다.")
        return False

    if not settings.kis.account_no:
        print("\n  ❌ KIS_ACCOUNT_NO가 설정되지 않았습니다.")
        return False

    print("\n  ✅ 설정 검증 완료. 모든 필수 값이 설정되어 있습니다.")
    return True


def test_actual_connection():
    """실제 KIS API 연결 테스트 (토큰 발급 → 시세 조회 → 잔고 조회)."""
    print("=" * 60)
    print("  한국투자증권(KIS) API 실제 연결 테스트")
    print("=" * 60)

    # 1. KISClient 초기화
    print("\n[1] KISClient 초기화 중...")
    from markets.us.kis_client import KISClient

    client = KISClient()
    if not client._check_ready():
        print("  ❌ KISClient 초기화 실패 — API 키/계좌번호 확인 필요")
        return False
    print("  ✅ KISClient 초기화 완료")
    print(f"     모드: {'실거래' if client.is_real else '모의투자(가상계좌)'}")
    print(f"     계좌: {client.account_no}")
    print(f"     거래소: {client.default_exchange}")

    # 2. 접근토큰 발급
    print("\n[2] 접근토큰 발급 중...")
    if not client._ensure_token():
        print("  ❌ 접근토큰 발급 실패")
        return False
    print("  ✅ 접근토큰 발급 완료")

    # 3. 시세 조회 (AAPL)
    print("\n[3] 시세 조회 (AAPL)...")
    price_info = client.get_price("AAPL")
    if price_info:
        print(f"  ✅ AAPL 현재가: ${price_info.price:.2f}")
        print(f"     변동: {price_info.change_pct:+.2f}%")
        print(f"     고가: ${price_info.high:.2f} / 저가: ${price_info.low:.2f}")
        print(f"     거래량: {price_info.volume:,}")
    else:
        print("  ⚠️  시세 조회 실패 (장 종료 또는 API 오류)")

    # 4. 잔고 조회
    print("\n[4] 잔고 조회 중...")
    balance = client.get_balance()
    print(f"  ✅ 총 평가금액: ${balance.total_usd:,.2f}")
    print(f"     예수금(USD): ${balance.cash_usd:,.2f}")
    print(f"     보유종목: {len(balance.positions)}개")
    for pos in balance.positions:
        print(f"       - {pos.get('ticker', '')}: {pos.get('qty', 0)}주 "
              f"@ ${pos.get('current_price', 0):.2f} "
              f"(평가: ${pos.get('total_value', 0):.2f})")

    print("\n" + "=" * 60)
    print("  모든 테스트 완료 ✅")
    print("=" * 60)
    return True


def main():
    parser = argparse.ArgumentParser(description="KIS API 연결 테스트")
    parser.add_argument("--dry-run", action="store_true", help="설정 검증만 수행")
    args = parser.parse_args()

    if args.dry_run:
        success = test_dry_run()
    else:
        success = test_actual_connection()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
