from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("卫星云图自主读取")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.resize(1380, 880)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
