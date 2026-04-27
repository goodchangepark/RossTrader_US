"""
gui/settings_dialog.py — RossTrader_US

설정 다이얼로그.
KIS API 설정, 매매 파라미터, 뉴스 소스 설정.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox,
    QSpinBox, QCheckBox, QGroupBox, QFormLayout,
    QWidget, QMessageBox,
)
from PyQt5.QtCore import Qt

from config.constants import APP_NAME

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """설정 다이얼로그."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config.copy()
        self.setWindowTitle(f"{APP_NAME} — 설정")
        self.setMinimumSize(550, 500)
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 탭
        tabs = QTabWidget()
        tabs.addTab(self._build_api_tab(), "KIS API")
        tabs.addTab(self._build_trade_tab(), "매매 설정")
        tabs.addTab(self._build_risk_tab(), "리스크 설정")
        tabs.addTab(self._build_news_tab(), "뉴스 설정")
        layout.addWidget(tabs)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("저장")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def _build_api_tab(self) -> QWidget:
        """KIS API 설정 탭."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.api_appkey = QLineEdit()
        self.api_appkey.setPlaceholderText("KIS 앱키 입력")
        form.addRow("App Key:", self.api_appkey)

        self.api_appsecret = QLineEdit()
        self.api_appsecret.setPlaceholderText("KIS 시크릿키 입력")
        self.api_appsecret.setEchoMode(QLineEdit.Password)
        form.addRow("App Secret:", self.api_appsecret)

        self.api_account = QLineEdit()
        self.api_account.setPlaceholderText("계좌번호 (8자리-2자리)")
        form.addRow("계좌번호:", self.api_account)

        self.api_is_real = QCheckBox("실거래 모드 (체크=실거래, 미체크=모의)")
        form.addRow(self.api_is_real)

        self.api_exchange = QLineEdit("NASD")
        self.api_exchange.setPlaceholderText("NASD/NYSE/AMEX")
        form.addRow("기본 거래소:", self.api_exchange)

        return tab

    def _build_trade_tab(self) -> QWidget:
        """매매 설정 탭."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.trade_budget = QDoubleSpinBox()
        self.trade_budget.setRange(100, 100000)
        self.trade_budget.setSingleStep(100)
        self.trade_budget.setPrefix("$ ")
        self.trade_budget.setDecimals(2)
        form.addRow("매매 예산 (USD):", self.trade_budget)

        self.trade_max_pos = QSpinBox()
        self.trade_max_pos.setRange(1, 20)
        form.addRow("최대 보유종목:", self.trade_max_pos)

        self.trade_level = QSpinBox()
        self.trade_level.setRange(0, 5)
        form.addRow("전략 레벨 (0~5):", self.trade_level)

        self.trade_sl = QDoubleSpinBox()
        self.trade_sl.setRange(0.5, 10.0)
        self.trade_sl.setSingleStep(0.5)
        self.trade_sl.setSuffix(" %")
        self.trade_sl.setDecimals(1)
        form.addRow("손절 (Stop Loss):", self.trade_sl)

        self.trade_tp = QDoubleSpinBox()
        self.trade_tp.setRange(1.0, 20.0)
        self.trade_tp.setSingleStep(0.5)
        self.trade_tp.setSuffix(" %")
        self.trade_tp.setDecimals(1)
        form.addRow("익절 (Take Profit):", self.trade_tp)

        self.trade_ts = QDoubleSpinBox()
        self.trade_ts.setRange(0.5, 5.0)
        self.trade_ts.setSingleStep(0.1)
        self.trade_ts.setSuffix(" %")
        self.trade_ts.setDecimals(1)
        form.addRow("트레일링 스탑:", self.trade_ts)

        return tab

    def _build_risk_tab(self) -> QWidget:
        """리스크 설정 탭."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.risk_max_order = QDoubleSpinBox()
        self.risk_max_order.setRange(100, 10000)
        self.risk_max_order.setSingleStep(100)
        self.risk_max_order.setPrefix("$ ")
        self.risk_max_order.setDecimals(2)
        form.addRow("최대 주문 금액:", self.risk_max_order)

        self.risk_max_portfolio = QDoubleSpinBox()
        self.risk_max_portfolio.setRange(0.1, 0.5)
        self.risk_max_portfolio.setSingleStep(0.05)
        self.risk_max_portfolio.setDecimals(2)
        form.addRow("종목당 최대 비중:", self.risk_max_portfolio)

        self.risk_daily_loss = QDoubleSpinBox()
        self.risk_daily_loss.setRange(10, 500)
        self.risk_daily_loss.setSingleStep(10)
        self.risk_daily_loss.setPrefix("$ ")
        self.risk_daily_loss.setDecimals(2)
        form.addRow("일일 손실 한도:", self.risk_daily_loss)

        self.risk_max_trades = QSpinBox()
        self.risk_max_trades.setRange(5, 50)
        form.addRow("일일 최대 거래횟수:", self.risk_max_trades)

        self.risk_forex_fallback = QDoubleSpinBox()
        self.risk_forex_fallback.setRange(1000, 2000)
        self.risk_forex_fallback.setSingleStep(10)
        self.risk_forex_fallback.setDecimals(2)
        form.addRow("USD/KRW 비상 환율:", self.risk_forex_fallback)

        return tab

    def _build_news_tab(self) -> QWidget:
        """뉴스 설정 탭."""
        tab = QWidget()
        form = QFormLayout(tab)

        self.news_finnhub_key = QLineEdit()
        self.news_finnhub_key.setPlaceholderText("Finnhub API 키")
        form.addRow("Finnhub API Key:", self.news_finnhub_key)

        self.news_finnhub_enabled = QCheckBox("Finnhub 뉴스 사용")
        self.news_finnhub_enabled.setChecked(True)
        form.addRow(self.news_finnhub_enabled)

        self.news_edgar_enabled = QCheckBox("SEC EDGAR 공시 수집")
        self.news_edgar_enabled.setChecked(True)
        form.addRow(self.news_edgar_enabled)

        return tab

    def _load_config(self):
        """설정을 UI에 로드."""
        c = self._config

        # API
        kis = c.get("kis", {})
        self.api_appkey.setText(kis.get("app_key", ""))
        self.api_appsecret.setText(kis.get("app_secret", ""))
        self.api_account.setText(kis.get("account_no", ""))
        self.api_is_real.setChecked(kis.get("is_real", False))
        self.api_exchange.setText(c.get("us", {}).get("default_exchange", "NASD"))

        # Trade
        trade = c.get("trade", {})
        self.trade_budget.setValue(trade.get("budget", 1000))
        self.trade_max_pos.setValue(trade.get("max_positions", 5))
        self.trade_level.setValue(trade.get("level", 3))
        self.trade_sl.setValue(trade.get("stop_loss_pct", 2.0))
        self.trade_tp.setValue(trade.get("take_profit_pct", 3.5))
        self.trade_ts.setValue(trade.get("trailing_stop_pct", 1.0))

        # Risk
        us = c.get("us", {})
        self.risk_max_order.setValue(us.get("max_order_usd", 500))
        self.risk_max_portfolio.setValue(us.get("max_portfolio_pct", 0.4))
        self.risk_daily_loss.setValue(us.get("daily_loss_limit_usd", 50))
        self.risk_max_trades.setValue(us.get("max_daily_trades", 20))
        self.risk_forex_fallback.setValue(c.get("forex", {}).get("usd_krw_fallback", 1350.0))

        # News
        news = c.get("news", {})
        self.news_finnhub_key.setText(c.get("finnhub_api_key", ""))
        self.news_finnhub_enabled.setChecked(news.get("finnhub_enabled", True))
        self.news_edgar_enabled.setChecked(news.get("edgar_enabled", True))

    def get_config(self) -> dict:
        """UI에서 설정 수집."""
        c = self._config

        # API
        kis = c.setdefault("kis", {})
        kis["app_key"] = self.api_appkey.text().strip()
        kis["app_secret"] = self.api_appsecret.text().strip()
        kis["account_no"] = self.api_account.text().strip()
        kis["is_real"] = self.api_is_real.isChecked()
        us = c.setdefault("us", {})
        us["default_exchange"] = self.api_exchange.text().strip().upper()

        # Trade
        trade = c.setdefault("trade", {})
        trade["budget"] = self.trade_budget.value()
        trade["max_positions"] = self.trade_max_pos.value()
        trade["level"] = self.trade_level.value()
        trade["stop_loss_pct"] = self.trade_sl.value()
        trade["take_profit_pct"] = self.trade_tp.value()
        trade["trailing_stop_pct"] = self.trade_ts.value()

        # Risk
        us["max_order_usd"] = self.risk_max_order.value()
        us["max_portfolio_pct"] = self.risk_max_portfolio.value()
        us["daily_loss_limit_usd"] = self.risk_daily_loss.value()
        us["max_daily_trades"] = self.risk_max_trades.value()
        c.setdefault("forex", {})["usd_krw_fallback"] = self.risk_forex_fallback.value()

        # News
        c["finnhub_api_key"] = self.news_finnhub_key.text().strip()
        news = c.setdefault("news", {})
        news["finnhub_enabled"] = self.news_finnhub_enabled.isChecked()
        news["edgar_enabled"] = self.news_edgar_enabled.isChecked()

        return c
