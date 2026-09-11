"""Application entry point: ``python main.py`` -> :func:`run`."""

from __future__ import annotations

import sys

from .config import REPO_ROOT, load_config
from .ui.main_window import MainWindow


def run() -> int:
    """Create the QApplication, show the main window, run the event loop."""
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass  # dotenv is optional; defaults in config.py apply

    config = load_config()

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Smart Workspace")
    app.setOrganizationName("AgenticAI")

    window = MainWindow(config)
    window.resize(1280, 820)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
