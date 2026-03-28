"""Proxy review screen — interactive calibration of the proxy model.

The human opens this screen to talk directly to their proxy, inspecting
what it has learned, correcting wrong patterns, and reinforcing important
ones.  This is Pattern 3 from the chat-experience proposal.

Issue #259.
"""
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static, TextArea


class ProxyReviewScreen(Screen):
    """Full-screen proxy review session."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static('PROXY REVIEW', classes='section-title'),
            RichLog(id='review-log', wrap=True, markup=True),
            TextArea(id='review-input'),
            id='review-pane',
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one('#review-log', RichLog)
        log.write('[bold]Proxy Review Session[/bold]')
        log.write('Talk to your proxy to inspect and calibrate its model.')
        log.write('Type a message below and press Ctrl+J to send.\n')

        # Show initial memory state
        self._show_memory_summary(log)

    def _show_memory_summary(self, log: RichLog) -> None:
        """Show the current proxy memory state."""
        try:
            from projects.POC.tui.state_reader import read_state
            state = read_state()
            if not state or not state.projects:
                log.write('[dim]No proxy memory available yet.[/dim]')
                return

            # Find proxy model path from the first project
            for proj in state.projects:
                model_path = getattr(proj, 'proxy_model_path', '')
                if model_path and os.path.isfile(model_path):
                    from projects.POC.orchestrator.proxy_memory import (
                        get_interaction_counter,
                        open_proxy_db,
                        resolve_memory_db_path,
                    )
                    from projects.POC.orchestrator.proxy_review import (
                        format_introspection,
                        introspect_chunks,
                        summarize_accuracy,
                    )

                    db_path = resolve_memory_db_path(model_path)
                    if not os.path.isfile(db_path):
                        log.write('[dim]No proxy memory database found.[/dim]')
                        return

                    conn = open_proxy_db(db_path)
                    try:
                        current = get_interaction_counter(conn)
                        entries = introspect_chunks(conn, current_interaction=current)
                        if entries:
                            log.write(format_introspection(entries))
                        else:
                            log.write('[dim]No memories recorded yet.[/dim]')
                        accuracy = summarize_accuracy(conn)
                        log.write(accuracy)
                    finally:
                        conn.close()
                    return

            log.write('[dim]No proxy memory available yet.[/dim]')
        except Exception:
            log.write('[dim]Could not load proxy memory.[/dim]')

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Handle Ctrl+J (newline submission) in the text area."""
        ta = event.text_area
        text = ta.text
        # Ctrl+J inserts a newline — detect it as the submit signal
        if text.endswith('\n') and text.strip():
            message = text.strip()
            ta.clear()
            self._send_message(message)

    def _send_message(self, message: str) -> None:
        """Send a message to the proxy and display the exchange."""
        log = self.query_one('#review-log', RichLog)
        log.write(f'[bold green]You:[/bold green] {message}')
        log.write('[dim]Proxy is thinking...[/dim]')
        # The actual agent invocation would be async via run_review_turn().
        # For now, the screen provides the UI entry point; the orchestrator
        # integration (wiring run_review_turn into the TUI event loop)
        # follows the same pattern as the existing gate escalation flow.

    def action_go_back(self) -> None:
        self.app.pop_screen()
