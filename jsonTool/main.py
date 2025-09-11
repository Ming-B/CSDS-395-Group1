"""
程序入口
负责启动 QApplication，加载主窗口 MainWindow
Responsible for launching QApplication and loading the main window MainWindow
"""

import sys
from PySide6.QtWidgets import QApplication
from ui.mainwindow import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
