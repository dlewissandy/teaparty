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
        """Send a message to the proxy via run_review_turn and display the exchange."""
        import asyncio

        log = self.query_one('#review-log', RichLog)
        log.write(f'[bold green]You:[/bold green] {message}')
        log.write('[dim]Proxy is thinking...[/dim]')

        async def _do_turn():
            try:
                from projects.POC.orchestrator.messaging import SqliteMessageBus
                from projects.POC.orchestrator.proxy_memory import open_proxy_db
                from projects.POC.orchestrator.proxy_review import (
                    build_dialog_history,
                    open_review_session,
                    run_review_turn,
                )
                from projects.POC.tui.chat_main import global_bus_path

                projects_dir = getattr(self.app, 'projects_dir', '')
                if not projects_dir:
                    log.write('[bold red]No projects directory configured.[/bold red]')
                    return

                bus = SqliteMessageBus(global_bus_path(projects_dir))
                memory_db_path = os.path.join(projects_dir, '.proxy-memory.db')
                conn = open_proxy_db(memory_db_path)

                try:
                    import getpass
                    human_name = getpass.getuser()
                    session = open_review_session(
                        bus, human_name=human_name, memory_db_path=memory_db_path,
                    )
                    dialog_history = build_dialog_history(bus, session.conversation_id)

                    response = await run_review_turn(
                        message,
                        conn=conn,
                        session=session,
                        bus=bus,
                        dialog_history=dialog_history,
                    )

                    log.write(f'[bold cyan]Proxy:[/bold cyan] {response}')
                finally:
                    conn.close()
            except Exception as e:
                log.write(f'[bold red]Error:[/bold red] {e}')

        asyncio.create_task(_do_turn())

    def action_go_back(self) -> None:
        self.app.pop_screen()
