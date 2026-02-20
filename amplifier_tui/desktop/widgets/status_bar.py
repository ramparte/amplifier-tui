"""Status bar with session info, model, tokens, mode."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class AmplifierStatusBar(QWidget):
    """Custom status bar showing session info, model, tokens, and mode."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(16)

        self._session_label = QLabel("No session")
        self._model_label = QLabel("")
        self._token_label = QLabel("")
        self._mode_label = QLabel("")
        self._processing_label = QLabel("")

        for label in [
            self._session_label,
            self._model_label,
            self._token_label,
            self._mode_label,
            self._processing_label,
        ]:
            label.setStyleSheet("color: #888; font-size: 12px;")
            layout.addWidget(label)

        layout.addStretch()

    def set_session(self, session_id: str) -> None:
        short = session_id[:8] if session_id else "none"
        self._session_label.setText(f"Session: {short}")

    def set_model(self, model: str) -> None:
        self._model_label.setText(f"Model: {model}" if model else "")

    def set_tokens(
        self, input_tokens: int, output_tokens: int, context_window: int = 0
    ) -> None:
        inp = _format_tokens(input_tokens)
        out = _format_tokens(output_tokens)
        ctx = _format_tokens(context_window) if context_window else ""
        text = f"In: {inp} | Out: {out}"
        if ctx:
            text += f" / {ctx}"
        self._token_label.setText(text)

    def set_mode(self, mode: str | None) -> None:
        self._mode_label.setText(f"Mode: {mode}" if mode else "")

    def set_processing(self, label: str | None) -> None:
        if label:
            self._processing_label.setText(f"\u23f3 {label}")
            self._processing_label.setStyleSheet("color: #e9a560; font-size: 12px;")
        else:
            self._processing_label.setText("")
            self._processing_label.setStyleSheet("color: #888; font-size: 12px;")


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
