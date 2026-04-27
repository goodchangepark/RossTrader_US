"""
gui/backtest_widget.py — RossTrader_US

백테스팅 위젯.
과거 데이터 기반 전략 성능 테스트.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QDateEdit, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QTextEdit, QComboBox, QProgressBar,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


class BacktestWorker(QThread):
    """백테스트 워커 스레드 (비동기 실행)."""
    progress = pyqtSignal(int)
    result = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, ticker: str, start_date: str, end_date: str, budget: float):
        super().__init__()
        self._ticker = ticker
        self._start = start_date
        self._end = end_date
        self._budget = budget

    def run(self):
        try:
            self.log.emit(f"[Backtest] 시작: {self._ticker} ({self._start} ~ {self._end})")

            # 시뮬레이션 (실제 구현은 데이터 소스에 따라 다름)
            from core.entry_engine import EntryEngine
            from core.exit_manager import ExitManager, Position
            from datetime import datetime as dt

            engine = EntryEngine()
            exit_mgr = ExitManager(stop_loss_pct=2.0, take_profit_pct=3.5)

            # 결과
            total_trades = 0
            wins = 0
            losses = 0
            total_profit = 0.0
            max_drawdown = 0.0
            peak_value = self._budget
            trades = []

            for pct in range(5, 95, 5):
                self.progress.emit(pct)

            self.progress.emit(100)
            self.result.emit({
                "ticker": self._ticker,
                "start": self._start,
                "end": self._end,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": (wins / total_trades * 100) if total_trades > 0 else 0,
                "total_profit": total_profit,
                "profit_pct": (total_profit / self._budget * 100) if self._budget > 0 else 0,
                "max_drawdown": max_drawdown,
                "trades": trades,
            })
            self.log.emit(f"[Backtest] 완료: {self._ticker}")

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._running = False


class BacktestWidget(QWidget):
    """백테스팅 위젯."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 설정 영역
        config = QFrame()
        config.setFrameShape(QFrame.StyledPanel)
        config.setFixedHeight(100)
        cl = QHBoxLayout(config)

        # 티커
        cl.addWidget(QLabel("티커:"))
        self.cmb_ticker = QComboBox()
        self.cmb_ticker.setEditable(True)
        self.cmb_ticker.addItems(["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META"])
        self.cmb_ticker.setFixedWidth(120)
        cl.addWidget(self.cmb_ticker)

        # 시작일
        cl.addWidget(QLabel("시작:"))
        self.date_start = QDateEdit()
        self.date_start.setDate(QDate.currentDate().addMonths(-3))
        self.date_start.setCalendarPopup(True)
        self.date_start.setFixedWidth(120)
        cl.addWidget(self.date_start)

        # 종료일
        cl.addWidget(QLabel("종료:"))
        self.date_end = QDateEdit()
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        self.date_end.setFixedWidth(120)
        cl.addWidget(self.date_end)

        # 예산
        cl.addWidget(QLabel("예산($):"))
        self.spin_budget = QSpinBox()
        self.spin_budget.setRange(100, 100000)
        self.spin_budget.setValue(1000)
        self.spin_budget.setSingleStep(100)
        self.spin_budget.setFixedWidth(100)
        cl.addWidget(self.spin_budget)

        self.btn_start = QPushButton("백테스트 시작")
        self.btn_start.clicked.connect(self._start_backtest)
        self.btn_start.setStyleSheet("background:#2ecc71; color:white; font-weight:bold;")
        cl.addWidget(self.btn_start)

        self.btn_stop = QPushButton("중지")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_backtest)
        self.btn_stop.setStyleSheet("background:#e74c3c; color:white; font-weight:bold;")
        cl.addWidget(self.btn_stop)

        cl.addStretch()
        layout.addWidget(config)

        # 진행률
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 결과 요약
        result = QFrame()
        result.setFrameShape(QFrame.StyledPanel)
        result.setFixedHeight(70)
        rl = QHBoxLayout(result)
        self.lbl_bt_trades = QLabel("거래: 0")
        self.lbl_bt_winrate = QLabel("승률: 0%")
        self.lbl_bt_profit = QLabel("수익: $0.00")
        self.lbl_bt_profit_pct = QLabel("수익률: 0%")
        self.lbl_bt_mdd = QLabel("MDD: 0%")

        for lb in [self.lbl_bt_trades, self.lbl_bt_winrate, self.lbl_bt_profit,
                    self.lbl_bt_profit_pct, self.lbl_bt_mdd]:
            lb.setStyleSheet("font-size:12px; font-weight:bold; padding:4px 16px;")
        rl.addWidget(self.lbl_bt_trades)
        rl.addWidget(self.lbl_bt_winrate)
        rl.addWidget(self.lbl_bt_profit)
        rl.addWidget(self.lbl_bt_profit_pct)
        rl.addWidget(self.lbl_bt_mdd)
        rl.addStretch()
        layout.addWidget(result)

        # 로그
        self.bt_log = QTextEdit()
        self.bt_log.setReadOnly(True)
        self.bt_log.setStyleSheet(
            "background:#0a0a15; color:#e0e0e0; font-family:Consolas; font-size:11px;"
        )
        self.bt_log.setFixedHeight(100)
        layout.addWidget(self.bt_log)

        # 결과 테이블
        self.bt_table = QTableWidget(0, 7)
        self.bt_table.setHorizontalHeaderLabels([
            "번호", "진입일", "종료일", "구분", "수량", "손익($)", "수익률(%)"
        ])
        self.bt_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.bt_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bt_table.setStyleSheet("""
            QTableWidget { font-size:12px; }
            QHeaderView::section { background:#2c3e50; color:white; padding:4px; }
        """)
        layout.addWidget(self.bt_table, stretch=1)

    def _start_backtest(self):
        """백테스트 시작."""
        ticker = self.cmb_ticker.currentText().strip().upper()
        if not ticker:
            QMessageBox.warning(self, "오류", "티커를 입력하세요.")
            return

        start = self.date_start.date().toString("yyyy-MM-dd")
        end = self.date_end.date().toString("yyyy-MM-dd")
        budget = self.spin_budget.value()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.bt_log.clear()
        self.bt_table.setRowCount(0)

        self._worker = BacktestWorker(ticker, start, end, float(budget))
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.log.connect(self._on_bt_log)
        self._worker.start()

    def _stop_backtest(self):
        """백테스트 중지."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.bt_log.append("[Backtest] 사용자에 의해 중지됨")

    def _on_result(self, result: dict):
        """백테스트 결과 수신."""
        self.lbl_bt_trades.setText(f"거래: {result['total_trades']}")
        self.lbl_bt_winrate.setText(f"승률: {result['win_rate']:.1f}%")
        profit_color = "#e74c3c" if result['total_profit'] >= 0 else "#3498db"
        self.lbl_bt_profit.setText(f"수익: ${result['total_profit']:.2f}")
        self.lbl_bt_profit.setStyleSheet(f"font-size:12px; font-weight:bold; padding:4px 16px; color:{profit_color};")
        self.lbl_bt_profit_pct.setText(f"수익률: {result['profit_pct']:.2f}%")
        self.lbl_bt_mdd.setText(f"MDD: {result['max_drawdown']:.2f}%")

        # 결과 테이블
        for i, trade in enumerate(result.get("trades", [])):
            row = self.bt_table.rowCount()
            self.bt_table.insertRow(row)

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)

    def _on_error(self, msg: str):
        """백테스트 오류."""
        self.bt_log.append(f"[오류] {msg}")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)

    def _on_bt_log(self, msg: str):
        """백테스트 로그."""
        self.bt_log.append(msg)
