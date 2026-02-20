"""Amplifier Desktop -- PySide6 native frontend."""

import sys


def main() -> None:
    """Launch the Amplifier desktop application."""
    from PySide6.QtWidgets import QApplication

    from amplifier_tui.desktop.desktop_app import DesktopApp
    from amplifier_tui.desktop.theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app, "dark")
    window = DesktopApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
