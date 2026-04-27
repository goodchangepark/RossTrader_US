"""
main.py — RossTrader_US (미국 주식 매매 프로그램)

GUI 진입점.
기존 RossTrader gui/main_window.py 참고.
"""

from __future__ import annotations

import logging
import os
import sys

# ── 프로젝트 루트를 sys.path에 추가 ──
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QFont, QPixmap, QColor
from PyQt5.QtCore import Qt

from config.constants import APP_NAME, VERSION
from gui.main_window import MainWindow


def setup_logging() -> None:
    """로깅 설정."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
        ],
    )
    # 불필요한 로거 레벨 조정
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main() -> None:
    """애플리케이션 진입점."""
    setup_logging()
    logger = logging.getLogger(__name__)

    # ── PyQt5 Application ──
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)

    # 폰트 설정
    font = QFont("맑은 고딕", 9)
    app.setFont(font)

    # ── 스플래시 스크린 ──
    splash = QSplashScreen()
    splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setFixedSize(400, 200)
    splash.show()
    splash.showMessage(
        f"{APP_NAME} v{VERSION} 로딩 중...",
        Qt.AlignCenter | Qt.AlignBottom,
        QColor("#2ecc71"),
    )
    app.processEvents()

    logger.info("=" * 60)
    logger.info("  %s v%s 시작", APP_NAME, VERSION)
    logger.info("=" * 60)

    # ── 메인 윈도우 ──
    window = MainWindow()
    window.show()

    splash.close()

    # ── 이벤트 루프 ──
    exit_code = app.exec_()
    logger.info("[Main] %s 종료 (code=%d)", APP_NAME, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
