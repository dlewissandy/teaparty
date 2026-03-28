"""ContentCard widget — titled dashboard card with clickable list items and optional "+ New" action."""
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


@dataclass
class CardItem:
    """A single row in a content card."""
    icon: str = ''
    label: str = ''
    detail: str = ''
    data: object = None  # arbitrary payload for click handling


class _CardItemStatic(Static):
    """Static that routes clicks to screen.action_card_click."""

    def __init__(self, content: str, card_name: str, index: int, **kwargs):
        super().__init__(content, **kwargs)
        self._card_name = card_name
        self._index = index

    def on_click(self) -> None:
        self.screen.action_card_click(self._card_name, self._index)


class ContentCard(Widget):
    """Dashboard content card: title + clickable item list.

    Each item is a _CardItemStatic that calls screen.action_card_click
    on click. Text is rendered as plain Rich markup (no [@click] tags)
    so color tags work correctly.
    """

    def __init__(
        self,
        title: str,
        card_name: str,
        items: list[CardItem] | None = None,
        show_new_button: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._card_name = card_name
        self._items = items or []
        self._show_new_button = show_new_button

    def compose(self) -> ComposeResult:
        header_text = self._title
        if self._show_new_button:
            header_text += f"  [@click=screen.card_new('{self._card_name}')]\\[+ New][/]"
        yield Static(header_text, classes='card-title')
        for i, item in enumerate(self._items):
            yield self._make_item_static(i, item)

    def _make_item_static(self, index: int, item: CardItem) -> _CardItemStatic:
        icon = f'{item.icon} ' if item.icon else '  '
        detail = f'  {item.detail}' if item.detail else ''
        return _CardItemStatic(
            f'{icon}{item.label}{detail}',
            card_name=self._card_name,
            index=index,
            classes='card-item card-item-clickable',
        )

    def update_items(self, items: list[CardItem]) -> None:
        """Replace card items. Skips rebuild if unchanged."""
        new_fp = [(it.icon, it.label, it.detail) for it in items]
        old_fp = [(it.icon, it.label, it.detail) for it in self._items]
        if new_fp == old_fp:
            self._items = items
            return

        self._items = items

        for child in list(self.children):
            if child.has_class('card-item'):
                child.remove()

        for i, item in enumerate(items):
            self.mount(self._make_item_static(i, item))
