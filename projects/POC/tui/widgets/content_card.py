"""ContentCard widget — titled dashboard card with list items and optional "+ New" action."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static


@dataclass
class CardItem:
    """A single row in a content card."""
    icon: str = ''
    label: str = ''
    detail: str = ''
    data: object = None  # arbitrary payload for click handling


class ContentCard(Widget):
    """Dashboard content card: title, item list, and optional '+ New' action.

    Posts ItemSelected when a row is clicked, and NewRequested when '+ New' is clicked.
    """

    class ItemSelected(Message):
        """Posted when the user selects an item in the card."""
        def __init__(self, card_name: str, item: CardItem) -> None:
            super().__init__()
            self.card_name = card_name
            self.item = item

    class NewRequested(Message):
        """Posted when the user clicks '+ New' on the card."""
        def __init__(self, card_name: str) -> None:
            super().__init__()
            self.card_name = card_name

    def __init__(
        self,
        title: str,
        card_name: str,
        items: list[CardItem] | None = None,
        show_new_button: bool = False,
        empty_text: str = '(none)',
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._card_name = card_name
        self._items = items or []
        self._show_new_button = show_new_button
        self._empty_text = empty_text

    def compose(self) -> ComposeResult:
        header_text = self._title
        if self._show_new_button:
            header_text += '  [@click=new_item()]\\[+ New][/]'
        yield Static(header_text, classes='card-title')
        yield Static(self._render_items(), id=f'card-{self._card_name}-items')

    def _render_items(self) -> str:
        if not self._items:
            return f'  [dim]{self._empty_text}[/dim]'
        lines = []
        for item in self._items:
            icon = f'{item.icon} ' if item.icon else '  '
            detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
            lines.append(f'{icon}{item.label}{detail}')
        return '\n'.join(lines)

    def update_items(self, items: list[CardItem]) -> None:
        """Replace card items and re-render."""
        self._items = items
        try:
            panel = self.query_one(f'#card-{self._card_name}-items', Static)
            panel.update(self._render_items())
        except Exception:
            pass

    def action_new_item(self) -> None:
        self.post_message(self.NewRequested(self._card_name))
