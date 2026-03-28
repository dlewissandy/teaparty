"""ContentCard widget — titled dashboard card with clickable list items and optional "+ New" action."""
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.events import Click
from textual.message import Message
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
    """Dashboard content card: title, clickable item list, and optional '+ New' action.

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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._card_name = card_name
        self._items = items or []
        self._show_new_button = show_new_button
        self._item_widgets: list[Static] = []

    def compose(self) -> ComposeResult:
        header_text = self._title
        if self._show_new_button:
            header_text += '  [@click=new_item()]\\[+ New][/]'
        yield Static(header_text, classes='card-title')
        self._item_widgets = []
        for i, item in enumerate(self._items):
            w = self._make_item_widget(item)
            self._item_widgets.append(w)
            yield w

    def _make_item_widget(self, item: CardItem) -> Static:
        icon = f'{item.icon} ' if item.icon else '  '
        detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
        return Static(
            f'{icon}{item.label}{detail}',
            classes='card-item card-item-clickable',
        )

    def on_click(self, event: Click) -> None:
        """Handle clicks — check if a card item was clicked."""
        widget = self.app.get_widget_at(event.screen_x, event.screen_y)[0]
        if widget in self._item_widgets:
            index = self._item_widgets.index(widget)
            if 0 <= index < len(self._items):
                event.stop()
                self.post_message(self.ItemSelected(self._card_name, self._items[index]))

    def update_items(self, items: list[CardItem]) -> None:
        """Replace card items and re-render the item list.

        Skips rebuild if items haven't changed (avoids mount/unmount flashing).
        """
        new_fp = [(it.icon, it.label, it.detail) for it in items]
        old_fp = [(it.icon, it.label, it.detail) for it in self._items]
        if new_fp == old_fp:
            self._items = items
            return

        self._items = items

        for child in list(self.children):
            if child.has_class('card-item'):
                child.remove()

        self._item_widgets = []
        for item in items:
            w = self._make_item_widget(item)
            self._item_widgets.append(w)
            self.mount(w)

    def action_new_item(self) -> None:
        self.post_message(self.NewRequested(self._card_name))
