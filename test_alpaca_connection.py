#!/usr/bin/env python3
"""
test_alpaca_connection.py — RossTrader_US

Alpaca API 미국 주식 연결 테스트.
1. .env → 설정 로드 확인
2. Alpaca 계좌 정보 조회
3. 미국 주식 시세 조회 (AAPL)

사용법:
    python3 test_alpaca_connection.py
"""

import logging
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def step1_check_env():
    print("\n" + "=" * 60)
    print("  [STEP 1] .env 설정 로드 확인")
    print("=" * 60)
    from config.settings import settings
    print(f"  ALPACA_API_KEY:     {settings.alpaca.api_key[:8]}{'*' * 8 if settings.alpaca.api_key else '(EMPTY)'}")
    print(f"  ALPACA_API_SECRET:  {'*' * 16 if settings.alpaca.api_secret else '(EMPTY)'}")
    print(f"  ALPACA_IS_PAPER:    {settings.alpaca.is_paper}")
    print(f"  EXCHANGE:           {settings.alpaca.default_exchange}")
    if not settings.alpaca.api_key or "your_alpaca" in settings.alpaca.api_key:
        logger.error("ALPACA_API_KEY 미설정")
        return False
    if not settings.alpaca.api_secret:
        logger.error("ALPACA_API_SECRET 미설정")
        return False
    logger.info("STEP 1 통과")
    return True


def step2_account_info():
    print("\n" + "=" * 60)
    print("  [STEP 2] Alpaca 계좌 정보 조회")
    print("=" * 60)
    from markets.us.alpaca_client import AlpacaClient
    client = AlpacaClient()
    if not client._check_client():
        logger.error("AlpacaClient 초기화 실패")
        return False, None
    try:
        acct = client.get_account_info()
        if acct:
            print(f"  계좌ID: {acct.get('id','N/A')} | 상태: {acct.get('status','N/A')}")
            print(f"  현금: ${acct.get('cash',0):.2f} | 포트폴리오: ${acct.get('portfolio_value',0):.2f}")
            print(f"  매수가능: ${acct.get('buying_power',0):.2f} | DT: {acct.get('daytrade_count',0)}회")
            logger.info("STEP 2 통과")
            return True, client
        else:
            logger.error("계좌 정보 비어있음")
            return False, client
    except Exception as e:
        logger.error(f"계좌 조회 실패: {e}")
        return False, None


def step3_price_query(client):
    print("\n" + "=" * 60)
    print("  [STEP 3] 시세 조회 (AAPL)")
    print("=" * 60)
    if client is None:
        logger.error("AlpacaClient 미초기화")
        return False
    try:
        pi = client.get_price("AAPL")
        if pi and pi.price > 0:
            print(f"  AAPL: ${pi.price:.2f} | {pi.timestamp}")
            logger.info("STEP 3 통과")
            return True
        else:
            print(f"  AAPL 응답: {pi} (장마감/휴장 가능)")
            return False
    except Exception as e:
        logger.error(f"시세 조회 실패: {e}")
        return False


def main():
    print("=" * 60)
    print("  RossTrader_US — Alpaca API 연결 테스트")
    print("=" * 60)
    if not step1_check_env():
        sys.exit(1)
    ok, client = step2_account_info()
    if not ok:
        print("\n계좌 조회 실패. API 키와 인터넷 연결을 확인하세요.")
        sys.exit(1)
    step3_price_query(client)
    print("\n" + "=" * 60)
    print("  테스트 완료!")
    print("=" * 60)

if __name__ == "__main__":
    main()
