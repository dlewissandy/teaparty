"""ContentCard widget — titled dashboard card with clickable list items and optional "+ New" action."""
from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
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


class _ClickableItem(Static):
    """A Static that posts CardItemClicked when clicked."""

    class Clicked(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, content: str, index: int, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._index = index

    def on_click(self) -> None:
        self.post_message(self.Clicked(self._index))


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

    def compose(self) -> ComposeResult:
        header_text = self._title
        if self._show_new_button:
            header_text += '  [@click=new_item()]\\[+ New][/]'
        yield Static(header_text, classes='card-title')
        yield from self._compose_items()

    def _compose_items(self):
        for i, item in enumerate(self._items):
            yield self._make_item_widget(i, item)

    def _make_item_widget(self, index: int, item: CardItem) -> _ClickableItem:
        icon = f'{item.icon} ' if item.icon else '  '
        detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
        return _ClickableItem(
            f'{icon}{item.label}{detail}',
            index=index,
            classes='card-item card-item-clickable',
        )

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

        for i, item in enumerate(items):
            self.mount(self._make_item_widget(i, item))

    def on__clickable_item_clicked(self, event: _ClickableItem.Clicked) -> None:
        """Bubble the click as an ItemSelected message."""
        if 0 <= event.index < len(self._items):
            self.post_message(self.ItemSelected(self._card_name, self._items[event.index]))

    def action_new_item(self) -> None:
        self.post_message(self.NewRequested(self._card_name))
