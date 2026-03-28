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
        yield from self._compose_items()

    def _compose_items(self):
        if not self._items:
            yield Static(
                f'  [dim]{self._empty_text}[/dim]',
                id=f'card-{self._card_name}-empty',
                classes='card-item',
            )
            return
        for i, item in enumerate(self._items):
            icon = f'{item.icon} ' if item.icon else '  '
            detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
            yield Static(
                f'[@click=select_item({i})]{icon}{item.label}{detail}[/]',
                classes='card-item card-item-clickable',
            )

    def update_items(self, items: list[CardItem]) -> None:
        """Replace card items and re-render the item list."""
        self._items = items

        # Remove old item widgets
        for child in list(self.children):
            if child.has_class('card-item'):
                child.remove()

        # Mount new items
        if not items:
            self.mount(Static(
                f'  [dim]{self._empty_text}[/dim]',
                id=f'card-{self._card_name}-empty',
                classes='card-item',
            ))
        else:
            for i, item in enumerate(items):
                icon = f'{item.icon} ' if item.icon else '  '
                detail = f'  [dim]{item.detail}[/dim]' if item.detail else ''
                self.mount(Static(
                    f'[@click=select_item({i})]{icon}{item.label}{detail}[/]',
                    classes='card-item card-item-clickable',
                ))

    def action_select_item(self, index: int) -> None:
        """Handle click on an item row."""
        if 0 <= index < len(self._items):
            self.post_message(self.ItemSelected(self._card_name, self._items[index]))

    def action_new_item(self) -> None:
        self.post_message(self.NewRequested(self._card_name))
