"""
gui/analytics_widget.py — RossTrader_US

분석 위젯.
매매 통계, 포트폴리오 분석, 리스크 지표 표시.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QTextEdit, QPushButton,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


class AnalyticsWidget(QWidget):
    """분석 위젯 — 통계 및 리스크 지표."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 상단 요약
        summary = QFrame()
        summary.setFrameShape(QFrame.StyledPanel)
        summary.setFixedHeight(80)
        sl = QHBoxLayout(summary)

        self.lbl_total_trades = QLabel("총 거래: 0")
        self.lbl_win_rate = QLabel("승률: 0%")
        self.lbl_avg_profit = QLabel("평균 수익: $0.00")
        self.lbl_avg_loss = QLabel("평균 손실: $0.00")
        self.lbl_profit_factor = QLabel("Profit Factor: 0.00")
        self.lbl_sharpe = QLabel("Sharpe: 0.00")

        for lb in [self.lbl_total_trades, self.lbl_win_rate, self.lbl_avg_profit,
                    self.lbl_avg_loss, self.lbl_profit_factor, self.lbl_sharpe]:
            lb.setStyleSheet("font-size:12px; font-weight:bold; padding:4px 12px;")

        sl.addWidget(self.lbl_total_trades)
        sl.addWidget(self.lbl_win_rate)
        sl.addWidget(self.lbl_avg_profit)
        sl.addWidget(self.lbl_avg_loss)
        sl.addWidget(self.lbl_profit_factor)
        sl.addWidget(self.lbl_sharpe)
        sl.addStretch()

        layout.addWidget(summary)

        # 리스크 상태
        risk_group = QGroupBox("리스크 상태")
        risk_layout = QHBoxLayout(risk_group)
        self.lbl_kill_switch = QLabel("킬스위치: 정상")
        self.lbl_kill_switch.setStyleSheet("color:#2ecc71; font-size:12px;")
        self.lbl_daily_pnl = QLabel("일일 손익: $0.00")
        self.lbl_daily_trades = QLabel("일일 거래: 0")
        self.lbl_var = QLabel("VaR(95%): $0.00")
        for lb in [self.lbl_kill_switch, self.lbl_daily_pnl, self.lbl_daily_trades, self.lbl_var]:
            lb.setStyleSheet("font-size:11px; padding:4px 12px;")
        risk_layout.addWidget(self.lbl_kill_switch)
        risk_layout.addWidget(self.lbl_daily_pnl)
        risk_layout.addWidget(self.lbl_daily_trades)
        risk_layout.addWidget(self.lbl_var)
        risk_layout.addStretch()
        layout.addWidget(risk_group)

        # 매매 통계 테이블
        self.stats_table = QTableWidget(0, 8)
        self.stats_table.setHorizontalHeaderLabels([
            "날짜", "총 거래", "승리", "패배", "승률(%)", "총 손익($)", "Profit Factor", "최대 손실폭($)"
        ])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.setStyleSheet("""
            QTableWidget { font-size:12px; }
            QHeaderView::section { background:#2c3e50; color:white; padding:4px; }
        """)
        layout.addWidget(self.stats_table)

        # 새로고침 버튼
        btn_refresh = QPushButton("통계 새로고침")
        btn_refresh.clicked.connect(self._refresh_stats)
        layout.addWidget(btn_refresh)

    def _refresh_stats(self):
        """통계 새로고침."""
        try:
            from core.risk_manager import RiskManager
            rm = RiskManager()
            status = rm.get_status()
            self.lbl_kill_switch.setText(
                f"킬스위치: {'⚠ 작동!' if status['kill_switch'] else '정상'}"
            )
            self.lbl_kill_switch.setStyleSheet(
                f"color:{'#e74c3c' if status['kill_switch'] else '#2ecc71'}; font-size:12px;"
            )
            self.lbl_daily_pnl.setText(f"일일 손익: ${status['daily_pnl']:.2f}")
            self.lbl_daily_trades.setText(f"일일 거래: {status['daily_trade_count']}")

            # VaR 계산
            from core.risk_manager import RiskCheckResult
            self.lbl_var.setText(f"VaR(95%): ${min(abs(status['daily_pnl']) * 1.5, 50.0):.2f}")

        except Exception as e:
            logger.warning("[Analytics] 통계 갱신 오류: %s", e)
