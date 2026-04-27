"""
gui/main_window.py — RossTrader_US

메인 GUI 윈도우.
기존 RossTrader gui/main_window.py 참고, 미국 주식 시장에 맞게 재설계.

- config.json (루트) 환경설정
- Python logging → GUI 로그박스 연결 (QtLogHandler)
- 다크 테마 적용
- 미국 장 세션 표시 (ET/KST 시간)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QLabel, QHeaderView, QLCDNumber, QSplitter, QFrame,
    QSlider, QGroupBox, QGridLayout, QStackedWidget,
    QMenuBar, QAction, QMessageBox, QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPixmap

import pandas as pd
import yfinance as yf

from config.constants import APP_NAME, VERSION

logger = logging.getLogger(__name__)

# 프로젝트 루트 경로
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.json"


# ══════════════════════════════════════════════════════════════════
# Qt 로그 핸들러
# ══════════════════════════════════════════════════════════════════
class QtLogHandler(logging.Handler):
    """Python logging → GUI 로그박스 연결."""
    def __init__(self, signal):
        super().__init__()
        self._signal = signal
        self.setFormatter(logging.Formatter(
            "[%(asctime)s] %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._signal.emit(msg)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# 메인 윈도우
# ══════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    _log_signal = pyqtSignal(str)
    _market_data_signal = pyqtSignal(dict, str)  # (data, time) 시그널

    def __init__(self):
        super().__init__()
        self._ctrl = None
        self._trader_thread = None
        self._broker = None
        self._news_collector = None
        self._market_cells = {}
        self._schedule_active = False
        self._config: dict = self._load_config()
        self._positions_rows = []
        self._fetching_market_data = False  # 중복 실행 방지 플래그

        # UI 빌드
        self._init_ui()
        self._apply_dark_theme()

        # 1초 클록 타이머
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

        # 10초 마켓 상태 체크 타이머
        self._market_timer = QTimer(self)
        self._market_timer.timeout.connect(self._update_market_status)
        self._market_timer.start(10000)

        # 15초 시장 지표 갱신 타이머 (S&P500, NASDAQ, VIX, 환율 등)
        self._index_timer = QTimer(self)
        self._index_timer.timeout.connect(self._update_market_data)
        self._index_timer.start(15000)

        # 시장 데이터 시그널 연결
        self._market_data_signal.connect(self._update_market_cells)

        # Python 루트 로거 → GUI 로그박스 연결
        self._qt_log_handler = QtLogHandler(self._log_signal)
        self._qt_log_handler.setLevel(logging.INFO)
        self._log_signal.connect(self._on_log)
        logging.getLogger().addHandler(self._qt_log_handler)
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

        # 1.5초 후 broker 초기화
        QTimer.singleShot(1500, self._init_broker_on_start)
        # 2초 후 controller 초기화
        QTimer.singleShot(500, self._init_controller)

        # 2초 후 첫 시장 지표 데이터 로드
        QTimer.singleShot(2000, self._update_market_data)

        self._append_log(f"{APP_NAME} v{VERSION} 초기화 완료")

    def _init_controller(self):
        """Controller 초기화."""
        from gui.main_window_controller import MainWindowController
        self._ctrl = MainWindowController(view=self)

    # ── 설정 로드 ─────────────────────────────────────
    def _load_config(self) -> dict:
        """config.json 로드."""
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info("[MainWindow] config.json 로드 완료")
            return cfg
        except Exception as e:
            logger.warning("[MainWindow] config.json 로드 실패: %s", e)
            return {
                "trade": {"budget": 1000, "max_positions": 5, "level": 3},
                "us": {"default_exchange": "NASD"},
                "news": {"finnhub_enabled": True, "edgar_enabled": True},
            }

    def _init_broker_on_start(self):
        """시작 시 broker 초기화."""
        try:
            from markets.us.kis_client import KISClient
            from markets.us.us_news_collector import USNewsAggregator
            self._broker = KISClient()
            self._news_collector = USNewsAggregator()
            # 잔고 표시
            bal = self._broker.get_balance()
            self.lcd_total.setText(f"${bal.total_usd:,.2f}")
            self.lcd_cash.setText(f"${bal.cash_usd:,.2f}")
            self._append_log("[MainWindow] Broker 초기화 완료")
            # 보유 종목 갱신
            self._refresh_positions()
        except Exception as e:
            logger.warning("[MainWindow] broker 초기화 실패: %s", e)

    # ── UI 초기화 ─────────────────────────────────────
    def _init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{VERSION} — 미국 주식 매매")
        self.setMinimumSize(1280, 800)

        # 메뉴바
        self._build_menu_bar()

        # 상태바
        self.statusBar().showMessage(f"{APP_NAME} v{VERSION}  |  미국 주식 자동매매")
        self.statusBar().setStyleSheet(
            "QStatusBar { background:#0f0f1a; color:#666; font-size:10px;"
            " border-top:1px solid #3d3d6b; }"
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(4)
        root.setContentsMargins(8, 8, 8, 8)

        # 상단 바
        root.addLayout(self._build_top_bar())

        # 시장 현황 패널
        root.addWidget(self._build_market_panel())

        # 미국 장 세션 패널
        root.addWidget(self._build_session_panel())

        # 잔고 표시줄
        root.addLayout(self._build_balance_row())

        # 탭 바
        root.addLayout(self._build_tab_bar())

        # 스택 위젯 (탭 페이지)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_trade_page())     # 0: 매매 현황
        self.stack.addWidget(self._build_positions_page())  # 1: 보유종목
        self.stack.addWidget(self._build_watchlist_page())  # 2: 관심종목
        self.stack.addWidget(self._build_analytics_page())  # 3: 분석
        self.stack.addWidget(self._build_backtest_page())   # 4: 백테스팅
        root.addWidget(self.stack, stretch=1)

    def _build_menu_bar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet(
            "QMenuBar { background-color:#0f0f1a; color:#e0e0e0;"
            " border-bottom:1px solid #3d3d6b; font-size:11px; }"
            "QMenuBar::item:selected { background-color:#2c2c54; }"
            "QMenu { background-color:#1a1a2e; color:#e0e0e0;"
            " border:1px solid #3d3d6b; }"
            "QMenu::item:selected { background-color:#2c2c54; }"
            "QMenu::separator { height:1px; background:#3d3d6b; margin:3px 8px; }"
        )

        file_menu = menubar.addMenu("파일(&F)")
        act_settings = QAction("설정", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        file_menu.addSeparator()
        act_exit = QAction("종료", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        trade_menu = menubar.addMenu("매매(&T)")
        act_force_sell = QAction("전체 강제매도", self)
        act_force_sell.triggered.connect(self._force_sell_all)
        trade_menu.addAction(act_force_sell)
        act_reset = QAction("일일 통계 리셋", self)
        act_reset.triggered.connect(self._reset_daily_stats)
        trade_menu.addAction(act_reset)

        help_menu = menubar.addMenu("도움말(&H)")
        act_about = QAction(f"{APP_NAME} 정보", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _show_about(self):
        msg = QMessageBox(self)
        msg.setWindowTitle(f"{APP_NAME} 정보")
        msg.setIcon(QMessageBox.Information)
        msg.setText(
            f"<h2>{APP_NAME}</h2>"
            f"<p><b>버전:</b> {VERSION}</p>"
            f"<p><b>설명:</b> 미국 주식 AI 뉴스 기반 자동 트레이딩 시스템</p>"
            f"<p><b>API:</b> 한국투자증권(KIS) 해외주식 API (모의투자/실전)</p>"
            f"<p><b>지원:</b> NASD, NYSE, AMEX</p>"
        )
        msg.exec_()

    # ── 상단 바 ───────────────────────────────────────
    def _build_top_bar(self):
        hbox = QHBoxLayout()
        self.btn_start = QPushButton("자동매매 시작")
        self.btn_stop = QPushButton("정지")
        self.btn_cfg = QPushButton("설정")
        self.lbl_status = QLabel("대기 중")
        self.lbl_status.setStyleSheet("color:#f39c12; font-weight:bold;")
        self.lbl_session = QLabel("")
        self.lbl_session.setStyleSheet("color:#666; font-size:10px;")
        self.lbl_clock = QLabel("--:--:--")
        self.lbl_clock.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.btn_start.clicked.connect(self._start_trader)
        self.btn_stop.clicked.connect(self._stop_trader)
        self.btn_cfg.clicked.connect(self._open_settings)
        self.btn_stop.setEnabled(False)

        for btn in (self.btn_start, self.btn_stop, self.btn_cfg):
            btn.setFixedHeight(32)

        hbox.addWidget(self.btn_start)
        hbox.addWidget(self.btn_stop)
        hbox.addWidget(self.btn_cfg)
        hbox.addWidget(self.lbl_status)
        hbox.addSpacing(12)
        hbox.addWidget(self.lbl_session)
        hbox.addStretch()
        hbox.addWidget(self.lbl_clock)
        return hbox

    # ── 시장 현황 패널 ────────────────────────────────
    def _build_market_panel(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setFixedHeight(88)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(6, 4, 6, 4)

        groups = [
            ("미국 지수", [("SPX", "S&P500", ""), ("IXIC", "NASDAQ", ""), ("DJI", "DOW", "")]),
            ("환율", [("USDKRW", "USD/KRW", ""), ("DXY", "달러인덱스", "")]),
            ("변동성", [("VIX", "VIX", ""), ("US10Y", "10년물", "%")]),
        ]

        font_name = QFont("맑은 고딕", 11)
        font_price = QFont("맑은 고딕", 14, QFont.Bold)
        font_chg = QFont("맑은 고딕", 11)

        first_group = True
        for _, cols in groups:
            if not first_group:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setStyleSheet("color:#555;")
                outer.addWidget(sep)
            first_group = False

            grp = QWidget()
            grid = QGridLayout(grp)
            grid.setContentsMargins(4, 2, 4, 2)
            grid.setHorizontalSpacing(0)
            grid.setVerticalSpacing(1)

            for ci, (key, name, suffix) in enumerate(cols):
                lbl_name = QLabel(name)
                lbl_name.setFont(font_name)
                lbl_name.setAlignment(Qt.AlignCenter)
                lbl_name.setFixedWidth(78)
                lbl_name.setStyleSheet("color:#aaa;")

                lbl_price = QLabel("--")
                lbl_price.setFont(font_price)
                lbl_price.setAlignment(Qt.AlignCenter)
                lbl_price.setFixedWidth(78)
                lbl_price.setStyleSheet("color:#fff;")

                lbl_chg = QLabel("--")
                lbl_chg.setFont(font_chg)
                lbl_chg.setAlignment(Qt.AlignCenter)
                lbl_chg.setFixedWidth(78)
                lbl_chg.setStyleSheet("color:#aaa;")

                grid.addWidget(lbl_name, 0, ci)
                grid.addWidget(lbl_price, 1, ci)
                grid.addWidget(lbl_chg, 2, ci)
                self._market_cells[key] = {"price": lbl_price, "chg": lbl_chg, "suffix": suffix}

            outer.addWidget(grp)

        outer.addStretch()
        self.lbl_market_updated = QLabel("갱신 --:--:--")
        self.lbl_market_updated.setStyleSheet("color:#666; font-size:10px;")
        self.lbl_market_updated.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        outer.addWidget(self.lbl_market_updated)
        return frame

    # ── 장 세션 패널 ─────────────────────────────────
    def _build_session_panel(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setFixedHeight(36)
        hbox = QHBoxLayout(frame)
        hbox.setContentsMargins(8, 2, 8, 2)

        self.lbl_et_time = QLabel("ET: --:--:--")
        self.lbl_et_time.setStyleSheet("color:#e0e0e0; font-weight:bold; font-size:11px;")
        self.lbl_kst_time = QLabel("KST: --:--:--")
        self.lbl_kst_time.setStyleSheet("color:#e0e0e0; font-size:11px;")
        self.lbl_session_status = QLabel("● 대기")
        self.lbl_session_status.setStyleSheet("color:#f39c12; font-weight:bold; font-size:11px;")
        self.lbl_orb_info = QLabel("")
        self.lbl_orb_info.setStyleSheet("color:#666; font-size:10px;")
        self.lbl_force_flat = QLabel("")
        self.lbl_force_flat.setStyleSheet("color:#e74c3c; font-size:10px;")

        hbox.addWidget(self.lbl_et_time)
        hbox.addSpacing(16)
        hbox.addWidget(self.lbl_kst_time)
        hbox.addSpacing(16)
        hbox.addWidget(self.lbl_session_status)
        hbox.addSpacing(16)
        hbox.addWidget(self.lbl_orb_info)
        hbox.addSpacing(16)
        hbox.addWidget(self.lbl_force_flat)
        hbox.addStretch()
        return frame

    # ── 잔고 표시줄 ──────────────────────────────────
    def _build_balance_row(self):
        hbox = QHBoxLayout()

        def make_label(title):
            grp = QGroupBox(title)
            grp.setFixedHeight(60)
            v = QVBoxLayout(grp)
            v.setContentsMargins(4, 2, 4, 2)
            lbl = QLabel("$0.00")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet(
                "background:#1a1a2e; color:#2ecc71; font-size:16px;"
                " font-weight:bold; font-family:Consolas; padding-right:6px;"
            )
            v.addWidget(lbl)
            return grp, lbl

        grp1, self.lcd_total = make_label("총 평가금액")
        grp2, self.lcd_profit = make_label("오늘 손익")
        grp3, self.lcd_cash = make_label("예수금(USD)")
        grp4, self.lcd_positions = make_label("보유종목")

        hbox.addWidget(grp1)
        hbox.addWidget(grp2)
        hbox.addWidget(grp3)
        hbox.addWidget(grp4)
        return hbox

    # ── 탭 바 ─────────────────────────────────────────
    def _build_tab_bar(self):
        hbox = QHBoxLayout()
        tabs = ["매매 현황", "보유종목", "관심종목", "분석", "백테스팅"]
        self._tab_buttons = []
        for i, name in enumerate(tabs):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            self._tab_buttons.append(btn)
            hbox.addWidget(btn)
        self._tab_buttons[0].setChecked(True)
        hbox.addStretch()
        return hbox

    def _switch_tab(self, idx: int):
        """탭 전환."""
        for i, btn in enumerate(self._tab_buttons):
            btn.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    # ── 탭 페이지 ─────────────────────────────────────
    def _build_trade_page(self):
        """매매 현황 페이지."""
        page = QWidget()
        vbox = QVBoxLayout(page)

        # 매매 로그
        lbl = QLabel("매매 로그")
        lbl.setStyleSheet("color:#e0e0e0; font-weight:bold; font-size:12px;")
        vbox.addWidget(lbl)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(
            "background:#0a0a15; color:#e0e0e0; font-family:Consolas; font-size:11px;"
            " border:1px solid #3d3d6b;"
        )
        vbox.addWidget(self.log_box, stretch=1)

        # 매매 내역 테이블
        lbl2 = QLabel("오늘 매매 내역")
        lbl2.setStyleSheet("color:#e0e0e0; font-weight:bold; font-size:12px; margin-top:8px;")
        vbox.addWidget(lbl2)

        self.trade_table = QTableWidget(0, 8)
        self.trade_table.setHorizontalHeaderLabels([
            "시간", "종목", "구분", "수량", "가격(USD)", "손익(USD)", "수익률", "사유"
        ])
        self.trade_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.trade_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.trade_table.setAlternatingRowColors(True)
        self.trade_table.setStyleSheet("""
            QTableWidget { font-size:12px; }
            QHeaderView::section { background:#2c3e50; color:white; padding:4px; }
        """)
        vbox.addWidget(self.trade_table)

        return page

    def _build_positions_page(self):
        """보유종목 현황 페이지."""
        page = QWidget()
        vbox = QVBoxLayout(page)

        # 요약
        summary = QFrame()
        summary.setFrameShape(QFrame.StyledPanel)
        summary.setFixedHeight(50)
        sl = QHBoxLayout(summary)
        self.lbl_pos_count = QLabel("보유종목: 0개")
        self.lbl_pos_eval = QLabel("전체평가: $0.00")
        self.lbl_pos_profit = QLabel("평가손익: $0.00")
        self.lbl_pos_pct = QLabel("수익률: 0.00%")
        for lb in [self.lbl_pos_count, self.lbl_pos_eval, self.lbl_pos_profit, self.lbl_pos_pct]:
            lb.setStyleSheet("font-size:13px; font-weight:bold; padding:4px 16px;")
        sl.addWidget(self.lbl_pos_count)
        sl.addWidget(self.lbl_pos_eval)
        sl.addWidget(self.lbl_pos_profit)
        sl.addWidget(self.lbl_pos_pct)

        btn_refresh = QPushButton("새로고침")
        btn_refresh.setFixedWidth(90)
        btn_refresh.clicked.connect(self._refresh_positions)
        btn_force_sell = QPushButton("강제매도")
        btn_force_sell.setFixedWidth(90)
        btn_force_sell.setStyleSheet("background:#e74c3c; color:white; font-weight:bold;")
        btn_force_sell.clicked.connect(self._force_sell)
        btn_sell_all = QPushButton("전체매도")
        btn_sell_all.setFixedWidth(90)
        btn_sell_all.setStyleSheet("background:#c0392b; color:white; font-weight:bold;")
        btn_sell_all.clicked.connect(self._force_sell_all)
        sl.addWidget(btn_force_sell)
        sl.addWidget(btn_sell_all)
        sl.addWidget(btn_refresh)
        sl.addStretch()
        vbox.addWidget(summary)

        # 보유종목 테이블 (체크박스 0열)
        self.positions_table = QTableWidget(0, 10)
        self.positions_table.setHorizontalHeaderLabels([
            "선택", "티커", "종목명", "매입가($)", "현재가($)",
            "수익률(%)", "수량", "평가금액($)", "평가손익($)", "매수시각"
        ])
        self.positions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.positions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.positions_table.setAlternatingRowColors(True)
        self.positions_table.setStyleSheet("""
            QTableWidget { font-size:12px; }
            QHeaderView::section { background:#2c3e50; color:white; padding:4px; }
        """)
        vbox.addWidget(self.positions_table)

        # 30초 자동 갱신
        self._pos_timer = QTimer()
        self._pos_timer.timeout.connect(self._refresh_positions)
        self._pos_timer.start(30000)

        return page

    def _build_watchlist_page(self):
        """관심종목 페이지."""
        page = QWidget()
        vbox = QVBoxLayout(page)

        top = QHBoxLayout()
        self.watchlist_input = QTextEdit()
        self.watchlist_input.setPlaceholderText("AAPL, TSLA, NVDA, ...")
        self.watchlist_input.setFixedHeight(30)
        self.watchlist_input.setStyleSheet("background:#1a1a2e; color:#e0e0e0; border:1px solid #3d3d6b;")
        btn_add = QPushButton("추가")
        btn_add.setFixedWidth(60)
        btn_add.clicked.connect(self._add_to_watchlist)
        top.addWidget(QLabel("티커 추가:"))
        top.addWidget(self.watchlist_input)
        top.addWidget(btn_add)
        top.addStretch()
        vbox.addLayout(top)

        self.watchlist_table = QTableWidget(0, 6)
        self.watchlist_table.setHorizontalHeaderLabels([
            "티커", "현재가($)", "변동(%)", "섹터", "Volume", "액션"
        ])
        self.watchlist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.watchlist_table.setEditTriggers(QTableWidget.NoEditTriggers)
        vbox.addWidget(self.watchlist_table)

        return page

    def _build_analytics_page(self):
        """분석 페이지."""
        from gui.analytics_widget import AnalyticsWidget
        return AnalyticsWidget(self)

    def _build_backtest_page(self):
        """백테스팅 페이지."""
        from gui.backtest_widget import BacktestWidget
        return BacktestWidget(self)

    # ── 장 세션 업데이트 ─────────────────────────────
    def _update_market_status(self):
        """시장 상태 주기적 업데이트."""
        try:
            from markets.us.us_session import us_session
            summary = us_session.session_summary()
            self.lbl_et_time.setText(f"ET: {summary['now_et']}")
            self.lbl_kst_time.setText(f"KST: {summary['now_kst']}")

            session = summary["session"]
            if session == "regular":
                self.lbl_session_status.setText("● 정규장")
                self.lbl_session_status.setStyleSheet("color:#2ecc71; font-weight:bold; font-size:11px;")
            elif session == "pre_market":
                self.lbl_session_status.setText("● 프리마켓")
                self.lbl_session_status.setStyleSheet("color:#f39c12; font-weight:bold; font-size:11px;")
            elif session == "after_hours":
                self.lbl_session_status.setText("● 애프터마켓")
                self.lbl_session_status.setStyleSheet("color:#e67e22; font-weight:bold; font-size:11px;")
            else:
                self.lbl_session_status.setText("● 휴장")
                self.lbl_session_status.setStyleSheet("color:#e74c3c; font-weight:bold; font-size:11px;")

            if summary["is_orb_period"]:
                self.lbl_orb_info.setText(f"ORB 진행 중 (종료: {summary['orb_end_kst']})")
                self.lbl_orb_info.setStyleSheet("color:#f1c40f; font-size:10px;")
            else:
                self.lbl_orb_info.setText("")

            if summary["should_force_flat"]:
                self.lbl_force_flat.setText(f"⚠ 장 마감 임박! 강제 청산: {summary['force_flat_kst']}")
                self.lbl_force_flat.setStyleSheet("color:#e74c3c; font-weight:bold; font-size:10px;")
            else:
                self.lbl_force_flat.setText("")
        except Exception:
            pass

    # ── 시장 지표 데이터 갱신 (S&P500, NASDAQ, DOW, USD/KRW, DXY, VIX, 10년물) ──
    def _update_market_data(self):
        """
        yfinance Ticker.history()로 시장 지표 실시간 데이터를 조회하여 UI 업데이트.
        개별 Ticker 객체를 사용하여 shared._LOCK 문제 회피.
        """
        if self._fetching_market_data:
            return
        self._fetching_market_data = True

        import threading

        def _fetch_one(symbol: str) -> dict | None:
            """단일 심볼의 최근 5일 데이터를 조회하여 {price, chg_pct, chg_val} 반환."""
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d", interval="1d")
                if hist is None or hist.empty or 'Close' not in hist.columns:
                    logger.warning("[MarketData] %s: 데이터 없음", symbol)
                    return None
                closes = hist['Close'].dropna()
                if len(closes) == 0:
                    return None
                last_price = float(closes.iloc[-1])
                prev_price = float(closes.iloc[-2]) if len(closes) >= 2 else last_price
                change_pct = ((last_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0
                change_val = last_price - prev_price
                return {"price": last_price, "chg_pct": change_pct, "chg_val": change_val}
            except Exception as e:
                logger.warning("[MarketData] %s 조회 실패: %s", symbol, e)
                return None

        def _fetch():
            try:
                ticker_map = {
                    "SPX": ("^GSPC", "지수"),
                    "IXIC": ("^IXIC", "지수"),
                    "DJI": ("^DJI", "지수"),
                    "USDKRW": ("USDKRW=X", "환율"),
                    "DXY": ("DX-Y.NYB", "지수"),
                    "VIX": ("^VIX", "지수"),
                    "US10Y": ("^TNX", "금리"),
                }

                market_data = {}
                for key, (symbol, itype) in ticker_map.items():
                    result = _fetch_one(symbol)
                    if result is None:
                        continue

                    # 지표별 표시 방식:
                    # - 지수/VIX: 등락률(%) 표시
                    # - USDKRW(환율): 가격 차이(원) 표시
                    # - US10Y(금리): 등락률(%) 표시
                    if key == "USDKRW":
                        display_chg = result["chg_val"]
                    else:
                        display_chg = result["chg_pct"]

                    market_data[key] = {
                        "price": result["price"],
                        "chg": display_chg,
                        "symbol": symbol,
                    }

                now = datetime.now().strftime("%H:%M:%S")
                logger.info("[MarketData] %d개 지표 로드 완료 (%s)", len(market_data), now)
                # pyqtSignal로 메인스레드에 안전하게 전달
                self._market_data_signal.emit(market_data, now)

            except Exception as e:
                logger.warning("[MarketData] 조회 오류: %s", e)
            finally:
                self._fetching_market_data = False

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_market_cells(self, data: dict, update_time: str):
        """시장 지표 UI 셀 업데이트."""
        try:
            for key, info in data.items():
                cell = self._market_cells.get(key)
                if not cell:
                    continue

                price_val = info["price"]
                chg_val = info["chg"]
                suffix = cell["suffix"]

                # 가격 표시
                if key == "USDKRW":
                    price_str = f"{price_val:.2f}"
                elif key == "US10Y":
                    price_str = f"{price_val:.2f}%"
                elif key == "VIX":
                    price_str = f"{price_val:.2f}"
                else:
                    price_str = f"{price_val:,.2f}"

                cell["price"].setText(price_str)

                # 등락률 표시
                if chg_val > 0:
                    color = "#e74c3c"  # 상승 빨강
                    prefix = "+"
                elif chg_val < 0:
                    color = "#3498db"  # 하락 파랑
                    prefix = ""
                else:
                    color = "#aaa"
                    prefix = ""

                if key == "USDKRW":
                    chg_str = f"{prefix}{chg_val:.2f}"
                elif key == "US10Y":
                    chg_str = f"{prefix}{chg_val:.2f}%"
                else:
                    chg_str = f"{prefix}{chg_val:.2f}%"

                cell["price"].setStyleSheet(f"color:{color}; font-size:14px; font-weight:bold;")
                cell["chg"].setText(chg_str)
                cell["chg"].setStyleSheet(f"color:{color};")

            self.lbl_market_updated.setText(f"갱신 {update_time}")

        except Exception as e:
            logger.debug("[MarketData] UI 업데이트 오류: %s", e)

    # ── 시계 업데이트 ────────────────────────────────
    def _update_clock(self):
        now = datetime.now()
        self.lbl_clock.setText(now.strftime("%H:%M:%S"))

    # ── 로그 ──────────────────────────────────────────
    def _append_log(self, msg: str):
        """로그박스에 메시지 추가."""
        try:
            self.log_box.append(msg)
            sb = self.log_box.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass

    def _on_log(self, msg: str):
        """로그 시그널 수신."""
        self._append_log(msg)

    # ── 매매 시작/정지 ───────────────────────────────
    def _start_trader(self):
        try:
            from utils.news_trader import NewsTraderThread
            if self._trader_thread and getattr(self._trader_thread, "_running", False):
                self._append_log("[Main] 이미 자동매매 실행 중")
                return

            self._trader_thread = NewsTraderThread(
                cfg=self._config,
                broker=self._broker,
                news_collector=self._news_collector,
            )
            self._trader_thread.log_signal.connect(self._on_log)
            self._trader_thread.trade_signal.connect(self._on_trade_signal)
            self._trader_thread.start()

            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.lbl_status.setText("● 매매 중")
            self.lbl_status.setStyleSheet("color:#2ecc71; font-weight:bold;")
            self._append_log("[Main] 자동매매 시작")
        except Exception as e:
            self._append_log(f"[Main] 자동매매 시작 실패: {e}")

    def _stop_trader(self):
        if self._trader_thread:
            self._trader_thread.stop()
            self._trader_thread = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("● 중지")
        self.lbl_status.setStyleSheet("color:#e74c3c; font-weight:bold;")
        self._append_log("[Main] 자동매매 중지")

    def _on_trade_signal(self, info: dict):
        """매매 시그널 수신 → 테이블 업데이트."""
        try:
            row = self.trade_table.rowCount()
            self.trade_table.insertRow(row)
            items = [
                info.get("time", ""),
                info.get("ticker", ""),
                info.get("side", ""),
                str(info.get("qty", 0)),
                f"${info.get('price', 0):.2f}",
                f"${info.get('profit', 0):.2f}",
                f"{info.get('profit_pct', 0):+.2f}%",
                info.get("reason", ""),
            ]
            for col, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                self.trade_table.setItem(row, col, item)
        except Exception:
            pass

    # ── 보유종목 ─────────────────────────────────────
    def _refresh_positions(self):
        """보유종목 갱신."""
        import threading
        def _load():
            try:
                positions = {}
                if self._trader_thread and hasattr(self._trader_thread, '_positions'):
                    positions = dict(getattr(self._trader_thread, '_positions', {}))
                if not positions and self._broker:
                    bal = self._broker.get_balance()
                    for p in bal.positions:
                        positions[p["ticker"]] = {
                            "name": p["name"],
                            "qty": p["qty"],
                            "avg_price": p["avg_price"],
                            "current_price": p["current_price"],
                        }
                rows = []
                for ticker, pos in positions.items():
                    entry_price = float(pos.get("avg_price", pos.get("entry_price", 0)))
                    current_price = float(pos.get("current_price", entry_price))
                    qty = int(pos.get("qty", 0))
                    name = pos.get("name", ticker)
                    pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                    profit = (current_price - entry_price) * qty
                    rows.append((ticker, name, entry_price, current_price, pct, qty, profit))
                self._positions_rows = rows
                QTimer.singleShot(0, self._update_positions_table)
            except Exception as e:
                logger.warning("[Positions] 갱신 오류: %s", e)
        threading.Thread(target=_load, daemon=True).start()

    def _update_positions_table(self):
        """보유종목 테이블 업데이트."""
        try:
            rows = self._positions_rows
            self.positions_table.setRowCount(0)
            total_profit = 0.0
            total_invested = 0.0
            total_eval = 0.0
            for ticker, name, entry_price, current_price, pct, qty, profit in rows:
                row = self.positions_table.rowCount()
                self.positions_table.insertRow(row)
                eval_amount = current_price * qty
                color = "#e74c3c" if pct > 0 else "#3498db" if pct < 0 else "#ffffff"

                # 체크박스
                chk_w = QWidget()
                chk_l = QHBoxLayout(chk_w)
                chk_l.setContentsMargins(4, 0, 4, 0)
                chk_l.setAlignment(Qt.AlignCenter)
                chk = QCheckBox()
                chk.setProperty("code", ticker)
                chk_l.addWidget(chk)
                self.positions_table.setCellWidget(row, 0, chk_w)

                vals = [
                    ticker, name,
                    f"{entry_price:.2f}", f"{current_price:.2f}",
                    f"{pct:+.2f}%", str(qty),
                    f"{eval_amount:.2f}", f"{profit:+.2f}", "",
                ]
                for col, val in enumerate(vals):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignCenter)
                    if col in [4, 7]:
                        item.setForeground(QColor(color))
                    self.positions_table.setItem(row, col + 1, item)

                total_profit += profit
                total_invested += entry_price * qty
                total_eval += eval_amount

            cnt = len(rows)
            self.lbl_pos_count.setText(f"보유종목: {cnt}개")
            self.lbl_pos_eval.setText(f"전체평가: ${total_eval:.2f}")
            profit_color = "color:#3498db;" if total_profit < 0 else "color:#e74c3c;"
            self.lbl_pos_profit.setText(f"평가손익: ${total_profit:+.2f}")
            self.lbl_pos_profit.setStyleSheet(f"font-size:13px; font-weight:bold; padding:4px 16px; {profit_color}")
            avg_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            self.lbl_pos_pct.setText(f"수익률: {avg_pct:+.2f}%")
            self.lbl_pos_pct.setStyleSheet(
                f"font-size:13px; font-weight:bold; padding:4px 16px; "
                f"{'color:#3498db;' if avg_pct < 0 else 'color:#e74c3c;'}"
            )
            # LCD 업데이트
            self.lcd_total.setText(f"${total_eval:.2f}")
            self.lcd_positions.setText(f"{cnt}개")
        except Exception as e:
            logger.warning("[Positions] 테이블 업데이트 오류: %s", e)

    def _force_sell(self):
        """선택 종목 강제매도."""
        from PyQt5.QtWidgets import QCheckBox
        checked = []
        for row in range(self.positions_table.rowCount()):
            w = self.positions_table.cellWidget(row, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and chk.isChecked():
                    ti = self.positions_table.item(row, 1)
                    ni = self.positions_table.item(row, 2)
                    qi = self.positions_table.item(row, 6)
                    if ti and qi:
                        checked.append((ti.text(), ni.text() if ni else ti.text(), int(qi.text())))
        if not checked:
            QMessageBox.warning(self, "강제매도", "체크한 종목이 없습니다.")
            return

        names = ", ".join([x[1] for x in checked])
        r = QMessageBox.question(
            self, "강제매도", f"{len(checked)}종목 매도? {names}",
            QMessageBox.Yes | QMessageBox.No
        )
        if r != QMessageBox.Yes:
            return

        for ticker, name, qty in checked:
            try:
                if self._broker:
                    self._broker.sell(ticker, qty)
                if self._trader_thread and hasattr(self._trader_thread, "_positions"):
                    self._trader_thread._positions.pop(ticker, None)
                self._append_log(f"[강제매도] {name}({ticker}) x{qty}")
            except Exception as e:
                QMessageBox.warning(self, "실패", f"{name}: {e}")
        self._refresh_positions()

    def _force_sell_all(self):
        """전체 종목 강제매도."""
        rows = getattr(self, "_positions_rows", [])
        if not rows:
            QMessageBox.warning(self, "전체매도", "보유 종목이 없습니다.")
            return
        names = ", ".join([x[1] for x in rows])
        r = QMessageBox.question(
            self, "전체매도", f"전체 {len(rows)}종목 매도? {names}",
            QMessageBox.Yes | QMessageBox.No
        )
        if r != QMessageBox.Yes:
            return
        for x in rows:
            ticker, name, entry_p, cur_p, pct, qty = x[0], x[1], x[2], x[3], x[4], x[5]
            try:
                if self._broker:
                    self._broker.sell(ticker, int(qty))
                if self._trader_thread and hasattr(self._trader_thread, "_positions"):
                    self._trader_thread._positions.pop(ticker, None)
                self._append_log(f"[전체매도] {name}({ticker}) x{qty} @ ${cur_p:.2f}")
            except Exception as e:
                self._append_log(f"[전체매도 실패] {name}: {e}")
        self._refresh_positions()

    def _add_to_watchlist(self):
        """관심종목 추가."""
        text = self.watchlist_input.toPlainText().strip().upper()
        if not text:
            return
        tickers = [t.strip() for t in text.replace(",", " ").split() if t.strip()]
        for ticker in tickers:
            try:
                self._watchlist_add_ticker(ticker)
            except Exception:
                pass
        self.watchlist_input.clear()
        self._refresh_watchlist()

    def _watchlist_add_ticker(self, ticker: str):
        """관심종목 1개 추가."""
        from markets.us.us_universe import USUniverse
        USUniverse().add_to_watchlist(ticker)

    def _refresh_watchlist(self):
        """관심종목 테이블 갱신."""
        from markets.us.us_universe import USUniverse
        universe = USUniverse()
        watchlist = universe.get_watchlist()
        self.watchlist_table.setRowCount(0)
        for ticker in watchlist:
            row = self.watchlist_table.rowCount()
            self.watchlist_table.insertRow(row)
            sector = universe.get_sector(ticker)
            item_ticker = QTableWidgetItem(ticker)
            self.watchlist_table.setItem(row, 0, item_ticker)
            item_sector = QTableWidgetItem(sector)
            self.watchlist_table.setItem(row, 3, item_sector)
            # 현재가 (비동기)
            if self._broker:
                try:
                    price_info = self._broker.get_price(ticker)
                    if price_info:
                        self.watchlist_table.setItem(row, 1, QTableWidgetItem(f"${price_info.price:.2f}"))
                        self.watchlist_table.setItem(row, 2, QTableWidgetItem(f"{price_info.change_pct:+.2f}%"))
                        self.watchlist_table.setItem(row, 4, QTableWidgetItem(str(price_info.volume)))
                except Exception:
                    pass
            # 제거 버튼
            btn_del = QPushButton("삭제")
            btn_del.setFixedWidth(50)
            btn_del.clicked.connect(lambda _, t=ticker: self._remove_from_watchlist(t))
            self.watchlist_table.setCellWidget(row, 5, btn_del)

    def _remove_from_watchlist(self, ticker: str):
        """관심종목 제거."""
        from markets.us.us_universe import USUniverse
        USUniverse().remove_from_watchlist(ticker)
        self._refresh_watchlist()

    def _open_settings(self):
        """설정 다이얼로그."""
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._config, self)
        if dlg.exec_() == SettingsDialog.Accepted:
            self._config = dlg.get_config()
            self._save_config()
            self._append_log("[Main] 설정 저장 완료")

    def _save_config(self):
        """config.json 저장."""
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("[Main] config.json 저장 실패: %s", e)

    def _reset_daily_stats(self):
        """일일 통계 리셋."""
        r = QMessageBox.question(
            self, "일일 통계 리셋", "오늘의 매매 통계를 리셋하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No
        )
        if r == QMessageBox.Yes:
            from core.risk_manager import RiskManager
            rm = RiskManager()
            rm.reset_daily()
            self._append_log("[Main] 일일 통계 리셋 완료")

    # ── 다크 테마 ────────────────────────────────────
    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow           { background-color:#0f0f1a; }
            QWidget               { background-color:#0f0f1a; color:#e0e0e0; }
            QFrame                { background-color:#1a1a2e; border:1px solid #3d3d6b; border-radius:4px; }
            QPushButton           { background-color:#2c2c54; color:#e0e0e0;
                                     border:1px solid #3d3d6b; border-radius:4px; padding:6px 14px; }
            QPushButton:hover     { background-color:#3d3d6b; }
            QPushButton:checked   { background-color:#2ecc71; color:#fff; }
            QPushButton:disabled  { background-color:#1a1a2e; color:#555; }
            QGroupBox              { background-color:#1a1a2e; border:1px solid #3d3d6b;
                                     border-radius:4px; margin-top:14px; font-weight:bold; }
            QGroupBox::title       { subcontrol-origin:margin; left:8px; padding:0 4px; color:#aaa; }
            QSlider::groove:horizontal { background:#3d3d6b; height:6px; border-radius:3px; }
            QSlider::handle:horizontal { background:#2ecc71; width:16px; border-radius:8px; margin:-5px 0; }
            QTextEdit             { background-color:#0a0a15; color:#e0e0e0;
                                     border:1px solid #3d3d6b; border-radius:4px; font-family:Consolas; }
            QTableWidget          { background-color:#0f0f1a; color:#e0e0e0;
                                     border:1px solid #3d3d6b; gridline-color:#1a1a2e; }
            QHeaderView::section  { background-color:#2c3e50; color:white; padding:4px; border:none; }
            QLabel                { color:#e0e0e0; }
            QScrollBar:vertical   { background:#0f0f1a; width:10px; }
            QScrollBar::handle:vertical { background:#3d3d6b; border-radius:5px; min-height:20px; }
        """)
