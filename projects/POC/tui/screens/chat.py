"""Chat screen — persistent conversation view for human-agent communication.

Replaces the modal input widget with a full conversation UI. The human
can see all active conversations, switch between them, and respond to
gate questions inline.

Layout: conversation list (left) | message stream + input (right).

Issue #206.
"""
from __future__ import annotations

import os
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from projects.POC.orchestrator.messaging import ConversationType
from projects.POC.tui.chat_model import ChatModel
from projects.POC.tui.stream_filter import StreamCategory, StreamFilter


_FILTER_LABELS: list[tuple[StreamCategory, str]] = [
    (StreamCategory.AGENT, 'agt'),
    (StreamCategory.HUMAN, 'hum'),
    (StreamCategory.THINKING, 'thk'),
    (StreamCategory.TOOLS, 'tls'),
    (StreamCategory.RESULTS, 'res'),
    (StreamCategory.SYSTEM, 'sys'),
    (StreamCategory.STATE, 'sta'),
    (StreamCategory.COST, 'cst'),
    (StreamCategory.LOG, 'log'),
]


_TYPE_LABELS = {
    ConversationType.OFFICE_MANAGER: 'Office Manager',
    ConversationType.PROJECT_SESSION: 'Session',
    ConversationType.SUBTEAM: 'Subteam',
    ConversationType.JOB: 'Job',
    ConversationType.TASK: 'Task',
    ConversationType.PROXY_REVIEW: 'Proxy Review',
    ConversationType.LIAISON: 'Liaison',
}


def _conv_label(conv, model: ChatModel) -> str:
    """Build a display label for a conversation list entry."""
    type_label = _TYPE_LABELS.get(conv.type, conv.type.value)
    # Extract qualifier from ID (after the prefix:)
    qualifier = conv.id.split(':', 1)[1] if ':' in conv.id else conv.id
    unread = model.unread_tracker.unread_count(model._bus_for(conv.id), conv.id)
    attention = model.needs_attention(conv.id)
    badge = ''
    if attention:
        badge = ' \u23f3'  # hourglass — needs response
    elif unread > 0:
        badge = f' ({unread})'
    return f'{type_label}: {qualifier}{badge}'


class ChatScreen(Screen):
    """Full-screen chat with conversation list and message stream."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
    ]

    def __init__(self):
        super().__init__()
        self._model: ChatModel | None = None
        self._conv_ids: list[str] = []
        self._selected_conv: str = ''
        self._msg_count: int = 0
        self._filters: dict[str, StreamFilter] = {}  # conv_id → filter

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Static('CONVERSATIONS', classes='section-title'),
                OptionList(id='conv-list'),
                id='chat-left-pane',
            ),
            Vertical(
                Static('MESSAGES', classes='section-title', id='messages-title'),
                Horizontal(
                    *(
                        Static(
                            f'[{label}]',
                            id=f'filter-{cat.value}',
                            classes='filter-toggle filter-on' if StreamFilter().is_enabled(cat) else 'filter-toggle filter-off',
                        )
                        for cat, label in _FILTER_LABELS
                    ),
                    id='filter-bar',
                ),
                RichLog(id='message-log', highlight=True, markup=True),
                Vertical(
                    TextArea(id='chat-input'),
                    id='chat-input-area',
                ),
                id='chat-right-pane',
            ),
            id='chat-panes',
        )
        yield Footer()

    def on_mount(self) -> None:
        self._open_bus()
        self._rebuild_conv_list()
        # Auto-select first conversation with attention, or first overall
        if self._conv_ids:
            target = self._conv_ids[0]
            if self._model:
                for conv in self._model.attention_conversations():
                    if conv.id in self._conv_ids:
                        target = conv.id
                        break
            self._select_conversation(target)

    def on_unmount(self) -> None:
        if self._model:
            self._model.close()
            self._model = None

    def _open_bus(self) -> None:
        """Find and open message buses across all sessions.

        Scans in-process sessions and session infra dirs for messages.db
        files. Aggregates all found buses into a single ChatModel so
        conversations from different sessions appear in one view.
        """
        reader = self.app.state_reader
        reader.reload()
        bus_paths: list[str] = []
        seen: set[str] = set()

        # In-process sessions
        for sid, ip in getattr(self.app, '_in_process', {}).items():
            if ip.message_bus_path and os.path.exists(ip.message_bus_path):
                real = os.path.realpath(ip.message_bus_path)
                if real not in seen:
                    seen.add(real)
                    bus_paths.append(ip.message_bus_path)

        # Session infra dirs
        for session in reader.sessions:
            if session.infra_dir:
                candidate = os.path.join(session.infra_dir, 'messages.db')
                if os.path.exists(candidate):
                    real = os.path.realpath(candidate)
                    if real not in seen:
                        seen.add(real)
                        bus_paths.append(candidate)

        if bus_paths:
            self._model = ChatModel.from_bus_paths(bus_paths)
        else:
            self._model = None

    def _rebuild_conv_list(self) -> None:
        """Refresh the conversation list from the model."""
        ol = self.query_one('#conv-list', OptionList)
        ol.clear_options()
        self._conv_ids = []

        if not self._model:
            ol.add_option(Option('(no conversations)', disabled=True))
            return

        convos = self._model.conversations()
        if not convos:
            ol.add_option(Option('(no conversations)', disabled=True))
            return

        for conv in convos:
            label = _conv_label(conv, self._model)
            ol.add_option(Option(label))
            self._conv_ids.append(conv.id)

    def _filter_for(self, conv_id: str) -> StreamFilter:
        """Get or create the StreamFilter for a conversation."""
        if conv_id not in self._filters:
            self._filters[conv_id] = StreamFilter()
        return self._filters[conv_id]

    def _update_filter_bar(self) -> None:
        """Update filter toggle visuals to reflect current conversation's state."""
        if not self._selected_conv:
            return
        sf = self._filter_for(self._selected_conv)
        for cat, label in _FILTER_LABELS:
            try:
                widget = self.query_one(f'#filter-{cat.value}', Static)
            except Exception:
                continue
            on = sf.is_enabled(cat)
            widget.set_classes('filter-toggle filter-on' if on else 'filter-toggle filter-off')

    def on_click(self, event) -> None:
        """Handle clicks on filter toggle buttons."""
        widget = event.widget
        if not isinstance(widget, Static):
            return
        wid = widget.id or ''
        if not wid.startswith('filter-'):
            return
        cat_value = wid[len('filter-'):]
        try:
            cat = StreamCategory(cat_value)
        except ValueError:
            return
        if not self._selected_conv:
            return
        sf = self._filter_for(self._selected_conv)
        sf.toggle(cat)
        self._update_filter_bar()
        self._refresh_messages(full=True)

    def _select_conversation(self, conv_id: str) -> None:
        """Switch to a conversation and load its messages."""
        self._selected_conv = conv_id
        self._msg_count = 0
        if self._model:
            self._model.select_conversation(conv_id)

        # Update title
        title = self.query_one('#messages-title', Static)
        title.update(f'MESSAGES ({conv_id})')

        # Update filter bar for this conversation's state
        self._update_filter_bar()

        # Load messages
        self._refresh_messages(full=True)

    def _refresh_messages(self, full: bool = False) -> None:
        """Refresh the message log. If full, clear and reload all."""
        if not self._model or not self._selected_conv:
            return

        log = self.query_one('#message-log', RichLog)
        msgs = self._model.messages(self._selected_conv)

        if full:
            log.clear()
            self._msg_count = 0

        if len(msgs) <= self._msg_count:
            return

        from rich.text import Text
        for msg in msgs[self._msg_count:]:
            t = Text()
            dt = datetime.fromtimestamp(msg.timestamp)
            time_str = dt.strftime('%H:%M')

            if msg.sender == 'human':
                t.append(f'[{time_str}] ', style='dim')
                t.append('you', style='bold green')
                t.append(f'  {msg.content}')
            elif msg.sender == 'orchestrator':
                t.append(f'[{time_str}] ', style='dim')
                t.append('agent', style='bold cyan')
                t.append(f'  {msg.content}')
            else:
                t.append(f'[{time_str}] ', style='dim')
                t.append(msg.sender, style='bold')
                t.append(f'  {msg.content}')
            log.write(t)

        self._msg_count = len(msgs)
        log.scroll_end(animate=False)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle selecting a conversation from the list."""
        if event.option_list.id != 'conv-list':
            return
        idx = event.option_index
        if 0 <= idx < len(self._conv_ids):
            self._select_conversation(self._conv_ids[idx])
            self._rebuild_conv_list()  # Update unread badges

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Submit when Enter is pressed."""
        if event.text_area.id != 'chat-input':
            return
        if '\n' in event.text_area.text:
            text = event.text_area.text.replace('\n', '').strip()
            event.text_area.clear()
            if text and self._model and self._selected_conv:
                self._model.send_message(self._selected_conv, text)
                self._refresh_messages()

    def periodic_refresh(self) -> None:
        """Called by the app's periodic refresh."""
        if self._model and self._selected_conv:
            self._refresh_messages()
        self._rebuild_conv_list()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._rebuild_conv_list()
        if self._selected_conv:
            self._refresh_messages()
