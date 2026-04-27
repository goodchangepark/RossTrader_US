"""
markets/us/kis_client.py — RossTrader_US

한국투자증권(KIS) 해외주식 API 매매 클라이언트.
AbstractMarket 인터페이스를 구현.

KIS API (모의투자):
  Base URL: https://openapivts.koreainvestment.com:29443
KIS API (실전투자):
  Base URL: https://openapi.koreainvestment.com:9443

사용 예:
    client = KISClient()
    result = client.buy("AAPL", qty=1)
    price = client.get_price("TSLA")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import List, Optional

import requests

from config.settings import settings
from markets.base import AbstractMarket, OrderResult, PriceInfo, BalanceInfo
from markets.us.us_session import us_session

logger = logging.getLogger(__name__)


class KISClient(AbstractMarket):
    """
    한국투자증권(KIS) 해외주식 API 매매 클라이언트.
    AbstractMarket 인터페이스 구현.

    KIS API 특징:
    - 접근토큰 발급 필요 (app_key + app_secret -> access_token)
    - 해시키 필요 (body -> SHA-256 hash -> Base64)
    - 미국 주식은 정규장(9:30~16:00 ET)만 거래 가능
    - 모의투자 URL: https://openapivts.koreainvestment.com:29443
    - 실전투자 URL: https://openapi.koreainvestment.com:9443
    """

    def __init__(self):
        self.app_key = settings.kis.app_key
        self.app_secret = settings.kis.app_secret
        self.account_no = settings.kis.account_no
        self.base_url = settings.kis.base_url.rstrip("/")
        self.is_real = settings.kis.is_real
        self.default_exchange = settings.kis.default_exchange

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if self.app_key and self.app_secret and self.account_no:
            logger.info(
                "[KISClient] 초기화 완료 | 모드: %s | 계좌: %s | 거래소: %s",
                "실거래" if self.is_real else "모의투자(가상계좌)",
                self.account_no,
                self.default_exchange,
            )
        else:
            logger.warning("[KISClient] API 키 또는 계좌번호 미설정")

    # -- Token 관리 --------------------------------------------------

    def _ensure_token(self) -> bool:
        """
        접근토큰 확인/갱신.
        만료 5분 전이면 자동 갱신.

        Returns:
            bool: 토큰 발급 성공 여부
        """
        if self._access_token and time.time() < self._token_expires_at - 300:
            return True

        try:
            url = f"{self.base_url}/oauth2/tokenP"
            headers = {"Content-Type": "application/json"}
            body = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            }

            resp = requests.post(url, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            self._access_token = data.get("access_token", "")
            expires_in = data.get("expires_in", 86400)  # 기본 24시간
            self._token_expires_at = time.time() + expires_in

            logger.info(
                "[KISClient] 접근토큰 발급 완료 (expires_in=%ds)", expires_in
            )
            return bool(self._access_token)
        except Exception as e:
            logger.error("[KISClient] 접근토큰 발급 실패: %s", e)
            return False

    def _make_hashkey(self, data: dict) -> str:
        """
        hashkey 생성 (주문 시 필요).

        Args:
            data: API 요청 body dict

        Returns:
            str: Base64로 인코딩된 SHA-256 hash
        """
        try:
            json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            hash_obj = hashlib.sha256(json_str.encode("utf-8"))
            return hash_obj.hexdigest()
        except Exception as e:
            logger.warning("[KISClient] hashkey 생성 실패: %s", e)
            return ""

    def _get_headers(self, tr_id: str) -> dict:
        """
        API 요청 헤더 생성.

        Args:
            tr_id: KIS API 거래ID (예: "JTTT1002U" = 해외주식 매수)

        Returns:
            dict: HTTP 헤더
        """
        if not self._ensure_token():
            return {}

        return {
            "Content-Type": "application/json",
            "authorization": "Bearer {}".format(self._access_token),
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }

    # -- AbstractMarket 구현 ------------------------------------------

    def is_tradeable(self) -> bool:
        """
        KIS API 거래 가능 시간 확인.
        KIS는 미국 정규장(9:30~16:00 ET)만 지원.
        """
        return us_session.is_regular_open()

    def buy(
        self,
        ticker: str,
        qty: int,
        price: float = 0.0,
    ) -> OrderResult:
        """미국 주식 매수 (KIS API)."""
        if not self.is_tradeable():
            return OrderResult(
                success=False,
                error_msg="거래 불가 시간 (KIS는 정규장만 지원)",
            )

        if not self._check_ready():
            return OrderResult(success=False, error_msg="KISClient 미초기화")

        try:
            # 계좌번호 파싱 (8자리-2자리)
            account_parts = self.account_no.split("-")
            if len(account_parts) != 2:
                return OrderResult(success=False, error_msg="계좌번호 형식 오류 (8자리-2자리)")

            body = {
                "CANO": account_parts[0],           # 종합계좌번호 (8자리)
                "ACNT_PRDT_CD": account_parts[1],    # 계좌상품코드 (2자리)
                "OVRS_EXCG_CD": self.default_exchange,  # 해외거래소코드
                "PDNO": ticker.upper(),               # 종목코드
                "ORD_QTY": str(qty),                  # 주문수량
                "OVRS_ORD_UNPR": str(price) if price > 0 else "0",  # 해외주문단가
                "ORD_SVR_DVSN_CD": "0",               # 주문서버구분 (0=현물)
            }

            # 시장가/지정가 구분
            if price > 0:
                body["ORD_DVSN"] = "00"  # 지정가
            else:
                body["ORD_DVSN"] = "01"  # 시장가

            tr_id = "JTTT1002U"  # 해외주식 매수 (모의/실전 동일)
            body["hashkey"] = self._make_hashkey(body)
            headers = self._get_headers(tr_id)

            url = "{}/uapi/overseas-stock/v1/trading/order".format(self.base_url)
            resp = requests.post(url, headers=headers, json=body, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                order_no = output.get("ODNO", "")
                logger.info(
                    "[KISClient] 매수 성공 | %s %d주 | 주문번호: %s",
                    ticker, qty, order_no,
                )
                return OrderResult(
                    success=True,
                    order_no=order_no,
                    ticker=ticker,
                    exchange=self.default_exchange,
                    direction="buy",
                    qty=qty,
                    price=price,
                    raw_response=data,
                )
            else:
                error_msg = data.get("msg1", data.get("msg_cd", "알 수 없는 오류"))
                logger.error("[KISClient] 매수 실패 | %s | %s", ticker, error_msg)
                return OrderResult(
                    success=False, ticker=ticker, error_msg=error_msg,
                )

        except Exception as e:
            logger.error("[KISClient] 매수 실패 | %s | %s", ticker, e)
            return OrderResult(success=False, ticker=ticker, error_msg=str(e))

    def sell(
        self,
        ticker: str,
        qty: int,
        price: float = 0.0,
    ) -> OrderResult:
        """미국 주식 매도 (KIS API)."""
        if not self.is_tradeable():
            return OrderResult(
                success=False,
                error_msg="거래 불가 시간 (KIS는 정규장만 지원)",
            )

        if not self._check_ready():
            return OrderResult(success=False, error_msg="KISClient 미초기화")

        try:
            account_parts = self.account_no.split("-")
            if len(account_parts) != 2:
                return OrderResult(success=False, error_msg="계좌번호 형식 오류 (8자리-2자리)")

            body = {
                "CANO": account_parts[0],
                "ACNT_PRDT_CD": account_parts[1],
                "OVRS_EXCG_CD": self.default_exchange,
                "PDNO": ticker.upper(),
                "ORD_QTY": str(qty),
                "OVRS_ORD_UNPR": str(price) if price > 0 else "0",
                "ORD_SVR_DVSN_CD": "0",
            }

            if price > 0:
                body["ORD_DVSN"] = "00"  # 지정가
            else:
                body["ORD_DVSN"] = "01"  # 시장가

            tr_id = "JTTT1006U"  # 해외주식 매도 (모의/실전 동일)
            body["hashkey"] = self._make_hashkey(body)
            headers = self._get_headers(tr_id)

            url = "{}/uapi/overseas-stock/v1/trading/order".format(self.base_url)
            resp = requests.post(url, headers=headers, json=body, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                order_no = output.get("ODNO", "")
                logger.info(
                    "[KISClient] 매도 성공 | %s %d주 | 주문번호: %s",
                    ticker, qty, order_no,
                )
                return OrderResult(
                    success=True,
                    order_no=order_no,
                    ticker=ticker,
                    exchange=self.default_exchange,
                    direction="sell",
                    qty=qty,
                    price=price,
                    raw_response=data,
                )
            else:
                error_msg = data.get("msg1", data.get("msg_cd", "알 수 없는 오류"))
                logger.error("[KISClient] 매도 실패 | %s | %s", ticker, error_msg)
                return OrderResult(
                    success=False, ticker=ticker, error_msg=error_msg,
                )

        except Exception as e:
            logger.error("[KISClient] 매도 실패 | %s | %s", ticker, e)
            return OrderResult(success=False, ticker=ticker, error_msg=str(e))

    def get_price(self, ticker: str) -> Optional[PriceInfo]:
        """
        미국 주식 현재가 조회 (KIS API 해외주식 현재체결가).

        TR_ID: HHDFS00000300 (모의/실전 동일)
        """
        if not self._check_ready():
            return None

        try:
            headers = self._get_headers("HHDFS00000300")
            params = {
                "AUTH": "",
                "EXCD": self.default_exchange,
                "SYMB": ticker.upper(),
            }

            url = "{}/uapi/overseas-stock/v1/quotations/price".format(self.base_url)
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                price = float(output.get("last", output.get("prpr", 0)))
                open_price = float(output.get("open", 0))
                high = float(output.get("high", 0))
                low = float(output.get("low", 0))
                volume = int(output.get("vol", 0))
                change_pct = float(output.get("rate", output.get("prdy_vrss", 0)))

                return PriceInfo(
                    ticker=ticker,
                    exchange=self.default_exchange,
                    price=price,
                    open=open_price,
                    high=high,
                    low=low,
                    volume=volume,
                    change_pct=change_pct,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            else:
                logger.warning(
                    "[KISClient] 시세 조회 실패 | %s | %s",
                    ticker, data.get("msg1", ""),
                )
                return None

        except Exception as e:
            logger.error("[KISClient] 시세 조회 실패 | %s | %s", ticker, e)
            return None

    def get_balance(self) -> BalanceInfo:
        """
        계좌 잔고 및 해외주식 포지션 조회.

        TR_ID:
          - 해외주식 잔고조회: VTTS3012R (모의), TTTS3012R (실전)
        """
        if not self._check_ready():
            return BalanceInfo()

        try:
            account_parts = self.account_no.split("-")
            if len(account_parts) != 2:
                return BalanceInfo()

            tr_id = "TTTS3012R" if self.is_real else "VTTS3012R"
            headers = self._get_headers(tr_id)

            params = {
                "CANO": account_parts[0],
                "ACNT_PRDT_CD": account_parts[1],
                "OVRS_EXCG_CD": self.default_exchange,
                "TR_CRCY_CD": "USD",       # 거래통화코드 (USD/HKD/CNY/JPY/VND)
                "CTX_AREA_FK200": "",      # 연속조회검색조건200 (최초조회 시 공란)
                "CTX_AREA_NK200": "",      # 연속조회키200 (최초조회 시 공란)
            }

            url = "{}/uapi/overseas-stock/v1/trading/inquire-balance".format(self.base_url)
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            total_usd = 0.0
            cash_usd = 0.0
            positions = []

            if data.get("rt_cd") == "0":
                outputs = data.get("output1", [])
                output2 = data.get("output2", {})

                # 현금 잔고 (USD)
                cash_usd = float(output2.get("frcr_dncl_amt_2", output2.get("frcr_evlu_amt2", 0)))

                # 포지션
                for item in outputs:
                    try:
                        qty = int(float(item.get("ovrs_cblc_qty", 0)))
                        if qty <= 0:
                            continue

                        avg_price = float(item.get("pchs_avg_pric", 0))
                        current_price = float(item.get("ovrs_now_pric", 0))
                        market_value = float(item.get("ovrs_cblc_evlu_amt", 0))

                        positions.append({
                            "ticker": item.get("ovrs_item_cd", ""),
                            "name": item.get("rspt_name", item.get("ovrs_item_cd", "")),
                            "qty": qty,
                            "avg_price": avg_price,
                            "current_price": current_price,
                            "total_value": market_value,
                            "profit_pct": float(item.get("evlu_pfls_rt", 0)),
                        })

                        total_usd += market_value
                    except Exception:
                        continue

                # 총 평가금액 = 현금 + 포지션 평가액
                total_usd = float(output2.get("frcr_evlu_amt2", total_usd + cash_usd))

            logger.info(
                "[KISClient] 잔고 조회 완료 | total=$%.2f | cash=$%.2f | positions=%d",
                total_usd, cash_usd, len(positions),
            )
            return BalanceInfo(
                total_usd=total_usd,
                cash_usd=cash_usd,
                positions=positions,
            )

        except requests.exceptions.HTTPError as e:
            logger.error(
                "[KISClient] 잔고 조회 실패: %s | body=%s",
                e,
                getattr(e.response, "text", ""),
            )
            return BalanceInfo()
        except Exception as e:
            logger.error("[KISClient] 잔고 조회 예외: %s", e)
            return BalanceInfo()

    def to_base_currency(self, amount: float) -> float:
        """USD -> KRW 변환."""
        try:
            from utils.forex_manager import ForexManager
            return ForexManager().get_usd_krw() * amount
        except Exception:
            return settings.us.usd_krw_fallback * amount

    def collect_news(self, tickers: List[str]) -> list:
        """뉴스 수집 (USNewsAggregator 위임)."""
        try:
            from markets.us.us_news_collector import USNewsAggregator
            aggregator = USNewsAggregator()
            return aggregator.collect(tickers)
        except Exception as e:
            logger.error("[KISClient] 뉴스 수집 실패: %s", e)
            return []

    def get_market_status(self) -> dict:
        """시장 상태 요약."""
        status = us_session.session_summary()
        status["broker"] = "KIS(한국투자증권)"
        status["mode"] = "모의투자" if not self.is_real else "실거래"
        return status

    # -- Account Info ------------------------------------------------

    def get_account_info(self) -> dict:
        """
        계좌 정보 조회 (상세).

        Returns:
            dict: 계좌 기본 정보
        """
        if not self._check_ready():
            return {}

        try:
            account_parts = self.account_no.split("-")
            if len(account_parts) != 2:
                return {}

            tr_id = "TTTS3012R" if self.is_real else "VTTS3012R"
            headers = self._get_headers(tr_id)
            params = {
                "CANO": account_parts[0],
                "ACNT_PRDT_CD": account_parts[1],
                "OVRS_EXCG_CD": self.default_exchange,
                "TR_CRCY_CD": "USD",       # 거래통화코드 (USD/HKD/CNY/JPY/VND)
                "CTX_AREA_FK200": "",      # 연속조회검색조건200 (최초조회 시 공란)
                "CTX_AREA_NK200": "",      # 연속조회키200 (최초조회 시 공란)
            }

            url = "{}/uapi/overseas-stock/v1/trading/inquire-balance".format(self.base_url)
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") == "0":
                output2 = data.get("output2", {})
                return {
                    "account_no": self.account_no,
                    "status": "connected",
                    "cash": float(output2.get("frcr_dncl_amt_2", 0)),
                    "portfolio_value": float(output2.get("frcr_evlu_amt2", 0)),
                    "buying_power": float(output2.get("frcr_buy_amt2", 0)),
                }
            return {}
        except requests.exceptions.HTTPError as e:
            logger.error(
                "[KISClient] 계좌 정보 조회 실패: %s | body=%s",
                e,
                getattr(e.response, "text", ""),
            )
            return {}
        except Exception as e:
            logger.error("[KISClient] 계좌 정보 조회 실패: %s", e)
            return {}

    def get_positions(self) -> List[dict]:
        """현재 포지션 목록."""
        bal = self.get_balance()
        return bal.positions

    def cancel_all_orders(self) -> bool:
        """
        모든 미체결 주문 취소.

        TR_ID: JTTT1003U (모의), TTTS1003U (실전)
        """
        if not self._check_ready():
            return False

        try:
            # 미체결 주문 조회
            orders = self._get_pending_orders()
            if not orders:
                logger.info("[KISClient] 취소할 미체결 주문 없음")
                return True

            tr_id = "TTTS1003U" if self.is_real else "JTTT1003U"
            account_parts = self.account_no.split("-")
            cancelled = 0
            for order in orders:
                try:
                    body = {
                        "CANO": account_parts[0],
                        "ACNT_PRDT_CD": account_parts[1],
                        "OVRS_EXCG_CD": self.default_exchange,
                        "PDNO": order.get("pdno", ""),
                        "ORGN_ODNO": order.get("odno", ""),
                        "ORD_QTY": order.get("ord_qty", "0"),
                        "OVRS_ORD_UNPR": "0",
                        "ORD_SVR_DVSN_CD": "0",
                    }
                    body["hashkey"] = self._make_hashkey(body)
                    headers = self._get_headers(tr_id)

                    url = "{}/uapi/overseas-stock/v1/training/revoke-order".format(self.base_url)
                    resp = requests.post(url, headers=headers, json=body, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("rt_cd") == "0":
                        cancelled += 1

                except Exception:
                    continue

            logger.info("[KISClient] 주문 취소 완료: %d건", cancelled)
            return True

        except Exception as e:
            logger.error("[KISClient] 주문 취소 실패: %s", e)
            return False

    def _get_pending_orders(self) -> List[dict]:
        """
        미체결 주문 목록 조회.

        TR_ID: JTTT3003R (모의), TTTS3003R (실전)
        """
        try:
            account_parts = self.account_no.split("-")
            if len(account_parts) != 2:
                return []

            tr_id = "TTTS3003R" if self.is_real else "JTTT3003R"
            headers = self._get_headers(tr_id)
            params = {
                "CANO": account_parts[0],
                "ACNT_PRDT_CD": account_parts[1],
                "OVRS_EXCG_CD": self.default_exchange,
                "SORT_SQN": "DS",          # 정렬순서 (DS=역순)
                "ORD_ORGNO": "",
                "ODNO": "",
            }

            url = "{}/uapi/overseas-stock/v1/trading/inquire-nccs".format(self.base_url)
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("rt_cd") == "0":
                return data.get("output1", [])
            return []

        except Exception as e:
            logger.warning("[KISClient] 미체결 주문 조회 실패: %s", e)
            return []

    # -- Internal ----------------------------------------------------

    def _check_ready(self) -> bool:
        """KIS 클라이언트 초기화 상태 확인."""
        if not self.app_key or not self.app_secret:
            logger.warning("[KISClient] API 키 미설정")
            return False
        if not self.account_no:
            logger.warning("[KISClient] 계좌번호 미설정")
            return False
        return True
