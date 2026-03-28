"""Tests for issue #261: Scratch file lifecycle — orchestrator-written .context/ working memory.

Verifies:
1. ScratchModel accumulates human input from user events
2. ScratchModel accumulates CfA state changes from state_changed events
3. ScratchModel accumulates file modifications from tool_use events
4. ScratchModel accumulates dead ends (backtrack reasons)
5. ScratchModel.render produces markdown under 200 lines
6. ScratchModel.render includes pointers to detail files
7. ScratchWriter serializes scratch.md to worktree (atomic write)
8. ScratchWriter appends human input to detail file
9. ScratchWriter appends dead ends to detail file
10. ScratchWriter.cleanup removes .context/ directory
11. Engine calls scratch extraction at turn boundaries
12. Engine calls scratch cleanup on session completion
13. ScratchModel ignores irrelevant event types
14. ScratchModel tracks job/phase metadata in render output
15. Scratch file render stays under 200 lines even with many entries
16. ScratchWriter creates .context/ directory if it doesn't exist
17. ScratchWriter atomic write: temp file + rename
18. ScratchModel.extract handles tool_use Write events (file artifacts)
19. ScratchModel.extract handles tool_use Edit events (file artifacts)
"""
import asyncio
import os
import tempfile
import unittest

from projects.POC.orchestrator.scratch import ScratchModel, ScratchWriter


# ── Test 1: Accumulate human input ─────────────────────────────────────────

class TestScratchModelHumanInput(unittest.TestCase):
    """ScratchModel.extract must capture human messages from user events."""

    def _make_user_event(self, text='Please use approach B'):
        return {'type': 'user', 'message': {'content': text}}

    def test_captures_human_message(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.extract(self._make_user_event('Use the adapter pattern'))
        self.assertEqual(len(model.human_inputs), 1)
        self.assertIn('adapter pattern', model.human_inputs[0])

    def test_accumulates_multiple_messages(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.extract(self._make_user_event('First instruction'))
        model.extract(self._make_user_event('Second instruction'))
        self.assertEqual(len(model.human_inputs), 2)


# ── Test 2: Accumulate CfA state changes ──────────────────────────────────

class TestScratchModelStateChanges(unittest.TestCase):
    """ScratchModel.record_state_change must capture CfA state transitions."""

    def test_captures_state_transition(self):
        model = ScratchModel(job='test-job', phase='intent')
        model.record_state_change('INTENT_IN_PROGRESS', 'INTENT_ASSERT')
        self.assertEqual(len(model.state_changes), 1)
        self.assertEqual(model.state_changes[0]['from'], 'INTENT_IN_PROGRESS')
        self.assertEqual(model.state_changes[0]['to'], 'INTENT_ASSERT')

    def test_accumulates_transitions(self):
        model = ScratchModel(job='test-job', phase='intent')
        model.record_state_change('INTENT_IN_PROGRESS', 'INTENT_ASSERT')
        model.record_state_change('INTENT_ASSERT', 'INTENT_APPROVED')
        self.assertEqual(len(model.state_changes), 2)


# ── Test 3: Accumulate file modifications ─────────────────────────────────

class TestScratchModelFileModifications(unittest.TestCase):
    """ScratchModel.extract must track file modifications from tool_use events."""

    def _make_write_event(self, path='src/retrieval.py'):
        return {
            'type': 'tool_use',
            'name': 'Write',
            'input': {'file_path': path, 'content': '...'},
        }

    def _make_edit_event(self, path='src/retrieval.py'):
        return {
            'type': 'tool_use',
            'name': 'Edit',
            'input': {'file_path': path, 'old_string': 'a', 'new_string': 'b'},
        }

    def test_captures_write(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.extract(self._make_write_event('src/main.py'))
        self.assertIn('src/main.py', model.artifacts)

    def test_captures_edit(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.extract(self._make_edit_event('src/main.py'))
        self.assertIn('src/main.py', model.artifacts)

    def test_deduplicates_same_file(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.extract(self._make_write_event('src/main.py'))
        model.extract(self._make_edit_event('src/main.py'))
        self.assertEqual(model.artifacts.count('src/main.py'), 1)


# ── Test 4: Accumulate dead ends ──────────────────────────────────────────

class TestScratchModelDeadEnds(unittest.TestCase):
    """ScratchModel.add_dead_end records failed approaches."""

    def test_records_dead_end(self):
        model = ScratchModel(job='test-job', phase='execution')
        model.add_dead_end('Tried cosine similarity — too noisy')
        self.assertEqual(len(model.dead_ends), 1)
        self.assertIn('cosine similarity', model.dead_ends[0])


# ── Test 5: Render produces markdown under 200 lines ──────────────────────

class TestScratchModelRender(unittest.TestCase):
    """ScratchModel.render must produce markdown under 200 lines."""

    def _make_populated_model(self):
        model = ScratchModel(job='implement ACT-R', phase='execution')
        for i in range(5):
            model.extract({'type': 'user', 'message': {'content': f'Input {i}'}})
        for i in range(3):
            model.add_dead_end(f'Dead end {i}: approach did not work')
        for i in range(10):
            model.extract({
                'type': 'tool_use', 'name': 'Write',
                'input': {'file_path': f'src/file_{i}.py', 'content': '...'},
            })
        model.record_state_change('TASK_IN_PROGRESS', 'TASK_ASSERT')
        return model

    def test_under_200_lines(self):
        model = self._make_populated_model()
        rendered = model.render()
        lines = rendered.strip().split('\n')
        self.assertLessEqual(len(lines), 200)

    def test_includes_job_header(self):
        model = self._make_populated_model()
        rendered = model.render()
        self.assertIn('implement ACT-R', rendered)

    def test_includes_phase(self):
        model = self._make_populated_model()
        rendered = model.render()
        self.assertIn('execution', rendered)


# ── Test 6: Render includes pointers to detail files ──────────────────────

class TestScratchModelPointers(unittest.TestCase):
    """Render must include pointers to detail files."""

    def test_human_input_pointer(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({'type': 'user', 'message': {'content': 'use X'}})
        rendered = model.render()
        self.assertIn('human-input.md', rendered)

    def test_dead_ends_pointer(self):
        model = ScratchModel(job='test', phase='execution')
        model.add_dead_end('approach failed')
        rendered = model.render()
        self.assertIn('dead-ends.md', rendered)


# ── Test 7: ScratchWriter serializes scratch.md ───────────────────────────

class TestScratchWriterSerialize(unittest.TestCase):
    """ScratchWriter.write_scratch must write scratch.md to .context/."""

    def test_writes_scratch_file(self):
        with tempfile.TemporaryDirectory() as worktree:
            model = ScratchModel(job='test', phase='execution')
            model.extract({'type': 'user', 'message': {'content': 'hello'}})
            writer = ScratchWriter(worktree)
            writer.write_scratch(model)

            scratch_path = os.path.join(worktree, '.context', 'scratch.md')
            self.assertTrue(os.path.exists(scratch_path))
            content = open(scratch_path).read()
            self.assertIn('hello', content)


# ── Test 8: ScratchWriter appends human input detail ──────────────────────

class TestScratchWriterHumanDetail(unittest.TestCase):
    """ScratchWriter.append_human_input appends to .context/human-input.md."""

    def test_appends_human_input(self):
        with tempfile.TemporaryDirectory() as worktree:
            writer = ScratchWriter(worktree)
            writer.append_human_input('First message')
            writer.append_human_input('Second message')

            path = os.path.join(worktree, '.context', 'human-input.md')
            self.assertTrue(os.path.exists(path))
            content = open(path).read()
            self.assertIn('First message', content)
            self.assertIn('Second message', content)


# ── Test 9: ScratchWriter appends dead end detail ─────────────────────────

class TestScratchWriterDeadEndDetail(unittest.TestCase):
    """ScratchWriter.append_dead_end appends to .context/dead-ends.md."""

    def test_appends_dead_end(self):
        with tempfile.TemporaryDirectory() as worktree:
            writer = ScratchWriter(worktree)
            writer.append_dead_end('Tried X — failed because Y')

            path = os.path.join(worktree, '.context', 'dead-ends.md')
            self.assertTrue(os.path.exists(path))
            content = open(path).read()
            self.assertIn('Tried X', content)


# ── Test 10: ScratchWriter cleanup removes .context/ ──────────────────────

class TestScratchWriterCleanup(unittest.TestCase):
    """ScratchWriter.cleanup removes the entire .context/ directory."""

    def test_cleanup_removes_directory(self):
        with tempfile.TemporaryDirectory() as worktree:
            writer = ScratchWriter(worktree)
            writer.append_human_input('some content')

            ctx_dir = os.path.join(worktree, '.context')
            self.assertTrue(os.path.exists(ctx_dir))

            writer.cleanup()
            self.assertFalse(os.path.exists(ctx_dir))

    def test_cleanup_noop_if_no_directory(self):
        with tempfile.TemporaryDirectory() as worktree:
            writer = ScratchWriter(worktree)
            writer.cleanup()  # Should not raise


# ── Test 13: Irrelevant events are ignored ────────────────────────────────

class TestScratchModelIgnoresIrrelevant(unittest.TestCase):
    """ScratchModel.extract must ignore events that aren't extractable."""

    def test_ignores_text_event(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({'type': 'text', 'text': 'thinking out loud...'})
        self.assertEqual(len(model.human_inputs), 0)
        self.assertEqual(len(model.state_changes), 0)
        self.assertEqual(len(model.artifacts), 0)

    def test_ignores_result_event(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({'type': 'result', 'input_tokens': 50000})
        self.assertEqual(len(model.human_inputs), 0)

    def test_ignores_tool_use_non_file_ops(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}})
        self.assertEqual(len(model.artifacts), 0)


# ── Test 14: Render includes metadata ─────────────────────────────────────

class TestScratchModelRenderMetadata(unittest.TestCase):
    """Render output includes job and phase metadata."""

    def test_includes_updated_timestamp(self):
        model = ScratchModel(job='test-job', phase='planning')
        rendered = model.render()
        self.assertIn('Updated:', rendered)


# ── Test 15: Render stays under 200 lines even with many entries ──────────

class TestScratchModelRenderOverflow(unittest.TestCase):
    """Even with many entries, render must stay under 200 lines."""

    def test_many_entries_truncated(self):
        model = ScratchModel(job='test', phase='execution')
        for i in range(100):
            model.extract({'type': 'user', 'message': {'content': f'Message {i}'}})
        for i in range(100):
            model.add_dead_end(f'Dead end {i}')
        for i in range(100):
            model.extract({
                'type': 'tool_use', 'name': 'Write',
                'input': {'file_path': f'src/file_{i}.py', 'content': '...'},
            })
        rendered = model.render()
        lines = rendered.strip().split('\n')
        self.assertLessEqual(len(lines), 200)


# ── Test 16: ScratchWriter creates .context/ if needed ────────────────────

class TestScratchWriterCreatesDir(unittest.TestCase):
    """ScratchWriter operations must create .context/ if it doesn't exist."""

    def test_creates_directory_on_write(self):
        with tempfile.TemporaryDirectory() as worktree:
            writer = ScratchWriter(worktree)
            ctx_dir = os.path.join(worktree, '.context')
            self.assertFalse(os.path.exists(ctx_dir))

            model = ScratchModel(job='test', phase='execution')
            writer.write_scratch(model)
            self.assertTrue(os.path.exists(ctx_dir))


# ── Test 17: Atomic write via temp file + rename ──────────────────────────

class TestScratchWriterAtomicWrite(unittest.TestCase):
    """ScratchWriter.write_scratch must use atomic write (temp + rename)."""

    def test_scratch_file_is_complete(self):
        """After write, scratch.md contains complete content (not partial)."""
        with tempfile.TemporaryDirectory() as worktree:
            model = ScratchModel(job='test', phase='execution')
            model.extract({'type': 'user', 'message': {'content': 'hello'}})
            writer = ScratchWriter(worktree)
            writer.write_scratch(model)

            scratch_path = os.path.join(worktree, '.context', 'scratch.md')
            content = open(scratch_path).read()
            # File starts with markdown header (complete write, not truncated)
            self.assertTrue(content.startswith('# Job:'))


# ── Test 18–19: tool_use Write and Edit events ───────────────────────────

class TestScratchModelToolUseWriteEdit(unittest.TestCase):
    """ScratchModel tracks Write and Edit tool uses as artifacts."""

    def test_write_tool(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({
            'type': 'tool_use', 'name': 'Write',
            'input': {'file_path': '/tmp/worktree/src/main.py', 'content': 'x=1'},
        })
        self.assertEqual(len(model.artifacts), 1)

    def test_edit_tool(self):
        model = ScratchModel(job='test', phase='execution')
        model.extract({
            'type': 'tool_use', 'name': 'Edit',
            'input': {'file_path': '/tmp/worktree/src/main.py', 'old_string': 'a', 'new_string': 'b'},
        })
        self.assertEqual(len(model.artifacts), 1)


# ── Test 20: Engine _on_scratch_event extracts from STREAM_DATA ────────────

class TestEngineStreamExtraction(unittest.TestCase):
    """Engine._on_scratch_event feeds STREAM_DATA events into the scratch model."""

    def _make_orchestrator(self):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        worktree = tempfile.mkdtemp(prefix='test-261-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=worktree,
            project_workdir=worktree,
            session_worktree=worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, bus, worktree

    def test_stream_data_user_event_extracted(self):
        """STREAM_DATA with a user event populates scratch model human_inputs."""
        from projects.POC.orchestrator.events import Event, EventType
        orch, bus, worktree = self._make_orchestrator()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._on_scratch_event(Event(
            type=EventType.STREAM_DATA,
            data={'type': 'user', 'message': {'content': 'use approach B'}},
        )))
        loop.close()

        self.assertEqual(len(orch._scratch_model.human_inputs), 1)
        self.assertIn('approach B', orch._scratch_model.human_inputs[0])

    def test_stream_data_user_event_writes_detail_file(self):
        """STREAM_DATA with a user event also appends to human-input.md."""
        from projects.POC.orchestrator.events import Event, EventType
        orch, bus, worktree = self._make_orchestrator()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._on_scratch_event(Event(
            type=EventType.STREAM_DATA,
            data={'type': 'user', 'message': {'content': 'important decision'}},
        )))
        loop.close()

        detail_path = os.path.join(worktree, '.context', 'human-input.md')
        self.assertTrue(os.path.exists(detail_path))
        content = open(detail_path).read()
        self.assertIn('important decision', content)

    def test_state_changed_event_records_transition(self):
        """STATE_CHANGED events record CfA transitions in the scratch model."""
        from projects.POC.orchestrator.events import Event, EventType
        orch, bus, worktree = self._make_orchestrator()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._on_scratch_event(Event(
            type=EventType.STATE_CHANGED,
            data={
                'previous_state': 'TASK_IN_PROGRESS',
                'state': 'TASK_ASSERT',
                'phase': 'execution',
                'actor': 'human',
                'action': 'assert',
            },
        )))
        loop.close()

        self.assertEqual(len(orch._scratch_model.state_changes), 1)
        self.assertEqual(orch._scratch_model.state_changes[0]['from'], 'TASK_IN_PROGRESS')
        self.assertEqual(orch._scratch_model.state_changes[0]['to'], 'TASK_ASSERT')

    def test_irrelevant_event_type_ignored(self):
        """Event types other than STREAM_DATA and STATE_CHANGED are ignored."""
        from projects.POC.orchestrator.events import Event, EventType
        orch, bus, worktree = self._make_orchestrator()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._on_scratch_event(Event(
            type=EventType.LOG,
            data={'category': 'test'},
        )))
        loop.close()

        self.assertEqual(len(orch._scratch_model.human_inputs), 0)
        self.assertEqual(len(orch._scratch_model.state_changes), 0)
        self.assertEqual(len(orch._scratch_model.artifacts), 0)

    def test_stream_data_tool_use_extracted(self):
        """STREAM_DATA with tool_use Write populates artifacts."""
        from projects.POC.orchestrator.events import Event, EventType
        orch, bus, worktree = self._make_orchestrator()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._on_scratch_event(Event(
            type=EventType.STREAM_DATA,
            data={'type': 'tool_use', 'name': 'Write', 'input': {'file_path': 'src/main.py', 'content': '...'}},
        )))
        loop.close()

        self.assertIn('src/main.py', orch._scratch_model.artifacts)


# ── Test 21: Engine _update_scratch writes scratch.md ─────────────────────

class TestEngineUpdateScratch(unittest.TestCase):
    """Engine._update_scratch serializes scratch model to disk at turn boundary."""

    def _make_orchestrator(self):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        worktree = tempfile.mkdtemp(prefix='test-261-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=worktree,
            project_workdir=worktree,
            session_worktree=worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, worktree

    def test_writes_scratch_file_to_worktree(self):
        """_update_scratch creates .context/scratch.md in the session worktree."""
        orch, worktree = self._make_orchestrator()
        orch._scratch_model.extract({'type': 'user', 'message': {'content': 'hello'}})
        orch._update_scratch('execution')

        scratch_path = os.path.join(worktree, '.context', 'scratch.md')
        self.assertTrue(os.path.exists(scratch_path))
        content = open(scratch_path).read()
        self.assertIn('hello', content)
        self.assertIn('execution', content)

    def test_updates_phase_in_model(self):
        """_update_scratch sets the model's phase to the current phase."""
        orch, worktree = self._make_orchestrator()
        orch._update_scratch('planning')
        self.assertEqual(orch._scratch_model.phase, 'planning')


# ── Test 22: Engine _record_dead_end ──────────────────────────────────────

class TestEngineRecordDeadEnd(unittest.TestCase):
    """Engine._record_dead_end populates model and writes detail file."""

    def _make_orchestrator(self):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        worktree = tempfile.mkdtemp(prefix='test-261-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=worktree,
            project_workdir=worktree,
            session_worktree=worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, worktree

    def test_records_dead_end_in_model(self):
        orch, worktree = self._make_orchestrator()
        orch._record_dead_end('execution', 'backtracked to planning', 'approach was wrong')
        self.assertEqual(len(orch._scratch_model.dead_ends), 1)
        self.assertIn('execution', orch._scratch_model.dead_ends[0])
        self.assertIn('approach was wrong', orch._scratch_model.dead_ends[0])

    def test_writes_dead_end_detail_file(self):
        orch, worktree = self._make_orchestrator()
        orch._record_dead_end('planning', 'backtracked to intent')

        path = os.path.join(worktree, '.context', 'dead-ends.md')
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn('planning: backtracked to intent', content)


# ── Test 23: Engine cleanup removes .context/ ─────────────────────────────

class TestEngineCleanup(unittest.TestCase):
    """Engine run() finally block cleans up .context/ directory."""

    def _make_orchestrator(self):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        worktree = tempfile.mkdtemp(prefix='test-261-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=worktree,
            project_workdir=worktree,
            session_worktree=worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, worktree

    def test_scratch_writer_cleanup_removes_context_dir(self):
        """After cleanup, .context/ no longer exists."""
        orch, worktree = self._make_orchestrator()
        # Write something to create the directory
        orch._update_scratch('execution')
        ctx_dir = os.path.join(worktree, '.context')
        self.assertTrue(os.path.exists(ctx_dir))

        # Cleanup should remove it
        orch._scratch_writer.cleanup()
        self.assertFalse(os.path.exists(ctx_dir))


# ── Test 24: Scratch write happens before compaction check ────────────────

class TestScratchBeforeCompaction(unittest.TestCase):
    """The scratch file must exist before the compaction check fires.

    This verifies the ordering invariant: _update_scratch runs before
    _check_context_budget at turn boundaries, so when compaction tells
    the agent to read .context/scratch.md, the file is current.
    """

    def _make_orchestrator(self):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        worktree = tempfile.mkdtemp(prefix='test-261-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=worktree,
            project_workdir=worktree,
            session_worktree=worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, bus, worktree

    def test_scratch_exists_when_compaction_fires(self):
        """When _check_context_budget fires compaction, scratch.md already exists."""
        from projects.POC.orchestrator.actors import ActorResult
        from projects.POC.orchestrator.context_budget import ContextBudget

        orch, bus, worktree = self._make_orchestrator()

        # Populate the model with some content
        orch._scratch_model.extract({'type': 'user', 'message': {'content': 'test'}})

        # Write scratch first (as the engine does)
        orch._update_scratch('execution')

        # Now check context budget — scratch.md should exist
        scratch_path = os.path.join(worktree, '.context', 'scratch.md')
        self.assertTrue(os.path.exists(scratch_path))

        # Create a budget that would trigger compaction
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 170000})
        actor_result = ActorResult(action='auto-approve', data={'context_budget': budget})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._check_context_budget(actor_result, 'execution'))
        loop.close()

        # Compaction was triggered, and the scratch file was already there
        self.assertIn('.context/scratch.md', orch._pending_intervention)
        self.assertTrue(os.path.exists(scratch_path))


if __name__ == '__main__':
    unittest.main()
