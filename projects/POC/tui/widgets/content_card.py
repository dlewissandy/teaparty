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


class ContentCard(Widget):
    """Dashboard content card: title + clickable item list.

    Items use [@click=screen.card_click('card_name', index)] so clicks
    go directly to the Screen's action_card_click method — no message
    bubbling required.
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

    def _make_item_static(self, index: int, item: CardItem) -> Static:
        icon = f'{item.icon} ' if item.icon else '  '
        detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
        # Escape single quotes in label for the action string
        safe_name = self._card_name.replace("'", "\\'")
        return Static(
            f"[@click=screen.card_click('{safe_name}', {index})]{icon}{item.label}{detail}[/]",
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
