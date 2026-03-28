"""StatsBar widget — horizontal bar of key-value stat pairs."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class StatsBar(Widget):
    """Horizontal summary stats bar: key=value pairs separated by pipes."""

    def __init__(self, stats: list[tuple[str, str]] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stats = stats or []

    def compose(self) -> ComposeResult:
        yield Static(self._format_text(), id='stats-bar-text')

    def _format_text(self) -> str:
        if not self._stats:
            return ''
        values = '  '.join(f'[bold]{v:>{max(len(k), len(v))}}[/bold]' for k, v in self._stats)
        labels = '  '.join(f'[dim]{k:>{max(len(k), len(v))}}[/dim]' for k, v in self._stats)
        return f'{values}\n{labels}'

    def update_stats(self, stats: list[tuple[str, str]]) -> None:
        """Update the displayed stats."""
        self._stats = stats
        try:
            self.query_one('#stats-bar-text', Static).update(self._format_text())
        except Exception:
            pass
