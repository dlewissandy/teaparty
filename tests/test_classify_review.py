#!/usr/bin/env python3
"""Tests for classify_review.py."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import scripts.classify_review as mod


class TestStateActions(unittest.TestCase):
    """STATE_ACTIONS covers all documented CfA review states."""

    def test_all_assert_states_present(self):
        for state in ["INTENT_ASSERT", "PLAN_ASSERT", "TASK_ASSERT", "WORK_ASSERT"]:
            self.assertIn(state, mod.STATE_ACTIONS)

    def test_all_escalate_states_present(self):
        for state in ["INTENT_ESCALATE", "PLANNING_ESCALATE", "TASK_ESCALATE"]:
            self.assertIn(state, mod.STATE_ACTIONS)

    def test_intent_assert_actions(self):
        self.assertEqual(
            mod.STATE_ACTIONS["INTENT_ASSERT"],
            ["dialog", "approve", "correct", "withdraw"])

    def test_plan_assert_has_refine_intent(self):
        actions = mod.STATE_ACTIONS["PLAN_ASSERT"]
        self.assertIn("refine-intent", actions)
        self.assertNotIn("revise-plan", actions)

    def test_dialog_in_all_gate_states(self):
        """dialog is present in all ASSERT and ESCALATE states (review gates)."""
        for state in mod.STATE_ACTIONS:
            if state.endswith('_ASSERT') or state.endswith('_ESCALATE'):
                self.assertIn("dialog", mod.STATE_ACTIONS[state],
                              f"dialog missing from {state}")

    def test_work_assert_has_all_actions(self):
        actions = mod.STATE_ACTIONS["WORK_ASSERT"]
        self.assertIn("dialog", actions)
        self.assertIn("approve", actions)
        self.assertIn("correct", actions)
        self.assertIn("revise-plan", actions)
        self.assertIn("refine-intent", actions)
        self.assertIn("withdraw", actions)

    def test_task_assert_has_reject_and_backtrack(self):
        actions = mod.STATE_ACTIONS["TASK_ASSERT"]
        self.assertIn("dialog", actions)
        self.assertIn("approve", actions)
        self.assertIn("correct", actions)
        self.assertIn("reject", actions)
        self.assertIn("revise-plan", actions)
        self.assertIn("refine-intent", actions)
        self.assertIn("withdraw", actions)

    def test_escalate_states_no_approve(self):
        """ESCALATE states use 'complete' not 'approve' — approve has no state machine edge."""
        for state in ["INTENT_ESCALATE", "PLANNING_ESCALATE", "TASK_ESCALATE"]:
            self.assertNotIn("approve", mod.STATE_ACTIONS[state],
                             f"approve should not be in {state}")

    def test_state_actions_derived_from_state_machine(self):
        """STATE_ACTIONS should be derived, not hardcoded — verify key invariant."""
        # Every action in STATE_ACTIONS (except dialog) must be a valid
        # state machine edge for that state
        import json
        machine_path = os.path.join(
            os.path.dirname(__file__), '..', 'cfa-state-machine.json')
        with open(machine_path) as f:
            machine = json.load(f)
        for state, actions in mod.STATE_ACTIONS.items():
            if state == 'FAILURE':
                continue  # synthetic state, not in state machine
            sm_actions = {e['action'] for e in machine['transitions'].get(state, [])}
            for action in actions:
                if action == 'dialog':
                    continue  # gate-internal, not a state machine edge
                self.assertIn(action, sm_actions,
                              f"{action} in STATE_ACTIONS[{state}] but not in state machine")

    def test_escalate_states_have_dialog_clarify_complete_withdraw(self):
        for state in ["INTENT_ESCALATE", "PLANNING_ESCALATE", "TASK_ESCALATE"]:
            self.assertEqual(
                mod.STATE_ACTIONS[state],
                ["dialog", "clarify", "complete", "withdraw"])


class TestParseOutput(unittest.TestCase):

    def test_valid_approve(self):
        action, feedback = mod.parse_output("approve\t", {"approve", "correct", "withdraw"})
        self.assertEqual(action, "approve")
        self.assertEqual(feedback, "")

    def test_valid_correct_with_feedback(self):
        action, feedback = mod.parse_output(
            "correct\tChange section 1 to use foos/minute",
            {"approve", "correct", "withdraw"})
        self.assertEqual(action, "correct")
        self.assertEqual(feedback, "Change section 1 to use foos/minute")

    def test_invalid_action_returns_fallback(self):
        action, feedback = mod.parse_output(
            "explode\teverything",
            {"approve", "correct", "withdraw"})
        self.assertEqual(action, "__fallback__")

    def test_empty_string_returns_fallback(self):
        action, _ = mod.parse_output("", {"approve"})
        self.assertEqual(action, "__fallback__")

    def test_whitespace_only_returns_fallback(self):
        action, _ = mod.parse_output("   \n  ", {"approve"})
        self.assertEqual(action, "__fallback__")

    def test_multiline_takes_first_line(self):
        action, feedback = mod.parse_output(
            "approve\t\nsome extra stuff\nmore lines",
            {"approve", "correct"})
        self.assertEqual(action, "approve")
        self.assertEqual(feedback, "")

    def test_action_lowercased(self):
        action, _ = mod.parse_output("APPROVE\t", {"approve"})
        self.assertEqual(action, "approve")

    def test_no_tab_action_only(self):
        action, feedback = mod.parse_output("approve", {"approve"})
        self.assertEqual(action, "approve")
        self.assertEqual(feedback, "")

    def test_revise_plan_valid_at_work_assert(self):
        valid = set(mod.STATE_ACTIONS["WORK_ASSERT"])
        action, feedback = mod.parse_output(
            "revise-plan\tThe architecture is wrong",
            valid)
        self.assertEqual(action, "revise-plan")
        self.assertEqual(feedback, "The architecture is wrong")

    def test_revise_plan_invalid_at_plan_assert(self):
        valid = set(mod.STATE_ACTIONS["PLAN_ASSERT"])
        action, _ = mod.parse_output("revise-plan\tblah", valid)
        self.assertEqual(action, "__fallback__")

    def test_refine_intent_valid_at_plan_assert(self):
        valid = set(mod.STATE_ACTIONS["PLAN_ASSERT"])
        action, feedback = mod.parse_output(
            "refine-intent\tChange objective to research paper",
            valid)
        self.assertEqual(action, "refine-intent")

    def test_clarify_valid_at_escalate(self):
        valid = set(mod.STATE_ACTIONS["INTENT_ESCALATE"])
        action, feedback = mod.parse_output(
            "clarify\tUse PostgreSQL for the database",
            valid)
        self.assertEqual(action, "clarify")
        self.assertEqual(feedback, "Use PostgreSQL for the database")


class TestBuildContextBlock(unittest.TestCase):

    def test_both_summaries(self):
        block = mod.build_context_block("intent text", "plan text")
        self.assertIn("Intent summary:", block)
        self.assertIn("Plan summary:", block)

    def test_intent_only(self):
        block = mod.build_context_block("intent text", "")
        self.assertIn("Intent summary:", block)
        self.assertNotIn("Plan summary:", block)

    def test_no_summaries(self):
        block = mod.build_context_block("", "")
        self.assertIn("no document context", block)

    def test_truncation(self):
        long_text = "x" * 1000
        block = mod.build_context_block(long_text, "")
        self.assertLessEqual(len(block), mod.MAX_SUMMARY_CHARS + 50)


class TestBuildPrompt(unittest.TestCase):

    def test_assert_state_uses_assert_prompt(self):
        prompt = mod.build_prompt("PLAN_ASSERT", "looks good", "intent", "plan")
        self.assertIn("PLAN_ASSERT", prompt)
        self.assertIn("looks good", prompt)
        self.assertIn("refine-intent", prompt)  # valid action listed

    def test_escalate_state_uses_escalate_prompt(self):
        prompt = mod.build_prompt("INTENT_ESCALATE", "use postgres")
        self.assertIn("INTENT_ESCALATE", prompt)
        self.assertIn("use postgres", prompt)
        self.assertIn("WITHDRAW", prompt.upper())

    def test_unknown_state_uses_generic_assert(self):
        prompt = mod.build_prompt("UNKNOWN_STATE", "test")
        self.assertIn("approve", prompt)
        self.assertIn("correct", prompt)

    def test_context_included(self):
        prompt = mod.build_prompt("PLAN_ASSERT", "ok",
                                  "Build a widget", "Step 1: setup")
        self.assertIn("Build a widget", prompt)
        self.assertIn("Step 1: setup", prompt)


class TestClassify(unittest.TestCase):

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_approve_classification(self):
        with patch('subprocess.run', return_value=self._mock_llm("approve\t")):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertEqual(result, "approve\t")

    def test_correct_with_feedback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("correct\tFix section 1")):
            result = mod.classify("PLAN_ASSERT", "change section 1")
        self.assertEqual(result, "correct\tFix section 1")

    def test_refine_intent(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "refine-intent\tBuild research paper instead")):
            result = mod.classify("PLAN_ASSERT",
                                  "actually, let's build the research paper first")
        self.assertTrue(result.startswith("refine-intent\t"))

    def test_withdraw(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("withdraw\t")):
            result = mod.classify("INTENT_ASSERT", "let's call this whole thing off")
        self.assertEqual(result, "withdraw\t")

    def test_escalate_clarify(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("clarify\tUse PostgreSQL")):
            result = mod.classify("INTENT_ESCALATE", "Use PostgreSQL")
        self.assertTrue(result.startswith("clarify\t"))

    def test_escalate_withdraw(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("withdraw\t")):
            result = mod.classify("PLANNING_ESCALATE", "forget it, cancel")
        self.assertEqual(result, "withdraw\t")

    def test_empty_response_returns_fallback(self):
        result = mod.classify("PLAN_ASSERT", "")
        self.assertTrue(result.startswith("__fallback__"))

    def test_whitespace_response_returns_fallback(self):
        result = mod.classify("PLAN_ASSERT", "   ")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_timeout_returns_fallback(self):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_not_found_returns_fallback(self):
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_nonzero_exit_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("", 1)):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_empty_output_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("  ")):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_invalid_action_returns_fallback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("explode\teverything")):
            result = mod.classify("PLAN_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_summaries_passed_to_prompt(self):
        """Verify summaries reach the prompt (inspect the subprocess call)."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("approve\t")) as mock_run:
            mod.classify("PLAN_ASSERT", "ok",
                         intent_summary="Build widget",
                         plan_summary="Step 1 setup")
        call_args = mock_run.call_args
        prompt_input = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("Build widget", prompt_input)
        self.assertIn("Step 1 setup", prompt_input)

    def test_revise_plan_only_valid_at_work_assert(self):
        """revise-plan from LLM at PLAN_ASSERT should fallback."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("revise-plan\tblah")):
            result = mod.classify("PLAN_ASSERT", "the approach is wrong")
        self.assertTrue(result.startswith("__fallback__"))

    def test_unknown_state_uses_defaults(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("approve\t")):
            result = mod.classify("WEIRD_STATE", "looks good")
        self.assertEqual(result, "approve\t")


class TestDialogAction(unittest.TestCase):
    """Tests for the dialog action and dialog history support."""

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_parse_output_accepts_dialog(self):
        valid = set(mod.STATE_ACTIONS["WORK_ASSERT"])
        action, feedback = mod.parse_output(
            "dialog\tHave you tested it?", valid)
        self.assertEqual(action, "dialog")
        self.assertEqual(feedback, "Have you tested it?")

    def test_parse_output_dialog_at_escalate(self):
        valid = set(mod.STATE_ACTIONS["TASK_ESCALATE"])
        action, feedback = mod.parse_output(
            "dialog\tWhat do you mean by that?", valid)
        self.assertEqual(action, "dialog")

    def test_classify_dialog(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "dialog\tHave you tested it?")):
            result = mod.classify("WORK_ASSERT", "Have you tested it?")
        self.assertTrue(result.startswith("dialog\t"))

    def test_classify_dialog_at_escalate(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "dialog\tCan you give me an example?")):
            result = mod.classify("PLANNING_ESCALATE",
                                  "Can you give me an example?")
        self.assertTrue(result.startswith("dialog\t"))

    def test_dialog_history_in_prompt_when_provided(self):
        prompt = mod.build_prompt(
            "WORK_ASSERT", "No it sounds fine",
            dialog_history="HUMAN: Have you tested it?\nAGENT: Yes.")
        self.assertIn("DIALOG HISTORY", prompt)
        self.assertIn("Have you tested it?", prompt)

    def test_dialog_history_omitted_when_empty(self):
        prompt = mod.build_prompt("WORK_ASSERT", "looks good",
                                  dialog_history="")
        self.assertNotIn("DIALOG HISTORY", prompt)

    def test_dialog_history_omitted_when_whitespace(self):
        prompt = mod.build_prompt("WORK_ASSERT", "looks good",
                                  dialog_history="   ")
        self.assertNotIn("DIALOG HISTORY", prompt)

    def test_dialog_history_in_escalate_prompt(self):
        prompt = mod.build_prompt(
            "INTENT_ESCALATE", "I already told you",
            dialog_history="HUMAN: What do you mean?\nAGENT: I mean X.")
        self.assertIn("DIALOG HISTORY", prompt)
        self.assertIn("What do you mean?", prompt)

    def test_dialog_history_passed_through_classify(self):
        """Verify dialog_history reaches subprocess via prompt input."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("approve\t")) as mock_run:
            mod.classify("WORK_ASSERT", "No it sounds fine",
                         dialog_history="HUMAN: Tested?\nAGENT: Yes.")
        call_args = mock_run.call_args
        prompt_input = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("Tested?", prompt_input)

    def test_build_dialog_history_block_empty(self):
        self.assertEqual(mod.build_dialog_history_block(""), "")
        self.assertEqual(mod.build_dialog_history_block(None), "")

    def test_build_dialog_history_block_with_content(self):
        block = mod.build_dialog_history_block("HUMAN: hi\nAGENT: hello")
        self.assertIn("DIALOG HISTORY", block)
        self.assertIn("HUMAN: hi", block)


class TestEscalateCompleteAction(unittest.TestCase):
    """complete action is present in escalate states and classified correctly."""

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    # ── STATE_ACTIONS ──────────────────────────────────────────────────────────

    def test_complete_in_task_escalate_actions(self):
        self.assertIn("complete", mod.STATE_ACTIONS["TASK_ESCALATE"])

    def test_complete_in_intent_escalate_actions(self):
        self.assertIn("complete", mod.STATE_ACTIONS["INTENT_ESCALATE"])

    def test_complete_in_planning_escalate_actions(self):
        self.assertIn("complete", mod.STATE_ACTIONS["PLANNING_ESCALATE"])

    def test_escalate_states_now_have_four_actions(self):
        for state in ("INTENT_ESCALATE", "PLANNING_ESCALATE", "TASK_ESCALATE"):
            with self.subTest(state=state):
                actions = mod.STATE_ACTIONS[state]
                self.assertIn("dialog", actions)
                self.assertIn("clarify", actions)
                self.assertIn("complete", actions)
                self.assertIn("withdraw", actions)

    # ── parse_output ───────────────────────────────────────────────────────────

    def test_parse_complete_valid_at_task_escalate(self):
        valid = set(mod.STATE_ACTIONS["TASK_ESCALATE"])
        action, feedback = mod.parse_output("complete\t", valid)
        self.assertEqual(action, "complete")
        self.assertEqual(feedback, "")

    def test_parse_complete_valid_at_intent_escalate(self):
        valid = set(mod.STATE_ACTIONS["INTENT_ESCALATE"])
        action, feedback = mod.parse_output("complete\t", valid)
        self.assertEqual(action, "complete")

    def test_parse_complete_invalid_at_assert_states(self):
        """complete is not a valid action at ASSERT states — should fallback."""
        for state in ("INTENT_ASSERT", "PLAN_ASSERT", "WORK_ASSERT"):
            with self.subTest(state=state):
                valid = set(mod.STATE_ACTIONS[state])
                action, _ = mod.parse_output("complete\t", valid)
                self.assertEqual(action, "__fallback__")

    # ── classify ───────────────────────────────────────────────────────────────

    def test_classify_complete_at_task_escalate(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("complete\t")):
            result = mod.classify("TASK_ESCALATE", "the work is complete")
        self.assertEqual(result, "complete\t")

    def test_classify_complete_at_intent_escalate(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("complete\t")):
            result = mod.classify("INTENT_ESCALATE", "done, let's move on")
        self.assertEqual(result, "complete\t")

    def test_classify_complete_at_planning_escalate(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("complete\t")):
            result = mod.classify("PLANNING_ESCALATE", "looks good, proceed")
        self.assertEqual(result, "complete\t")

    def test_classify_clarify_still_works_at_task_escalate(self):
        """Existing clarify path must not be broken."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("clarify\tUse PostgreSQL")):
            result = mod.classify("TASK_ESCALATE", "Use PostgreSQL")
        self.assertTrue(result.startswith("clarify\t"))

    # ── build_prompt ───────────────────────────────────────────────────────────

    def test_escalate_prompt_mentions_complete(self):
        prompt = mod.build_prompt("TASK_ESCALATE", "the work is complete")
        self.assertIn("complete", prompt.lower())

    def test_escalate_prompt_has_complete_signals(self):
        prompt = mod.build_prompt("TASK_ESCALATE", "done")
        self.assertIn("work is complete", prompt.lower())

    def test_escalate_prompt_distinguishes_complete_from_clarify(self):
        """The prompt should explain the COMPLETE vs CLARIFY distinction."""
        prompt = mod.build_prompt("TASK_ESCALATE", "done")
        self.assertIn("CLARIFY", prompt.upper())
        self.assertIn("COMPLETE", prompt.upper())


class TestFailureStateDefinition(unittest.TestCase):
    """FAILURE state is present in STATE_ACTIONS with correct decision actions."""

    def test_failure_state_present(self):
        self.assertIn("FAILURE", mod.STATE_ACTIONS)

    def test_failure_state_actions_exact(self):
        self.assertEqual(
            mod.STATE_ACTIONS["FAILURE"],
            ["retry", "escalate", "backtrack", "withdraw"])

    def test_failure_state_has_no_dialog(self):
        """FAILURE is a decision state — dialog is intentionally absent."""
        self.assertNotIn("dialog", mod.STATE_ACTIONS["FAILURE"])

    def test_failure_state_has_retry(self):
        self.assertIn("retry", mod.STATE_ACTIONS["FAILURE"])

    def test_failure_state_has_backtrack(self):
        self.assertIn("backtrack", mod.STATE_ACTIONS["FAILURE"])


class TestParseOutputFailureState(unittest.TestCase):
    """parse_output correctly accepts/rejects actions at FAILURE state."""

    def _valid(self):
        return set(mod.STATE_ACTIONS["FAILURE"])

    def test_retry_valid_at_failure(self):
        action, feedback = mod.parse_output("retry\t", self._valid())
        self.assertEqual(action, "retry")
        self.assertEqual(feedback, "")

    def test_escalate_with_feedback_valid_at_failure(self):
        action, feedback = mod.parse_output(
            "escalate\tI need to check the file permissions", self._valid())
        self.assertEqual(action, "escalate")
        self.assertEqual(feedback, "I need to check the file permissions")

    def test_backtrack_with_feedback_valid_at_failure(self):
        action, feedback = mod.parse_output(
            "backtrack\tThe plan assumed network access but this machine is offline",
            self._valid())
        self.assertEqual(action, "backtrack")
        self.assertEqual(feedback, "The plan assumed network access but this machine is offline")

    def test_withdraw_valid_at_failure(self):
        action, feedback = mod.parse_output("withdraw\t", self._valid())
        self.assertEqual(action, "withdraw")
        self.assertEqual(feedback, "")

    def test_dialog_invalid_at_failure(self):
        """dialog is not a valid action at FAILURE — should fallback."""
        action, _ = mod.parse_output("dialog\tWhat went wrong?", self._valid())
        self.assertEqual(action, "__fallback__")

    def test_approve_invalid_at_failure(self):
        action, _ = mod.parse_output("approve\t", self._valid())
        self.assertEqual(action, "__fallback__")

    def test_clarify_invalid_at_failure(self):
        action, _ = mod.parse_output("clarify\tsomething", self._valid())
        self.assertEqual(action, "__fallback__")


class TestBuildPromptFailureState(unittest.TestCase):
    """build_prompt routes FAILURE to FAILURE_PROMPT, not ASSERT_PROMPT/ESCALATE_PROMPT."""

    def test_failure_uses_failure_prompt_not_assert(self):
        prompt = mod.build_prompt("FAILURE", "try again")
        # FAILURE_PROMPT contains retry/escalate/backtrack classification rules
        self.assertIn("RETRY", prompt)
        self.assertIn("BACKTRACK", prompt)
        self.assertIn("ESCALATE", prompt.upper())

    def test_failure_prompt_includes_response(self):
        prompt = mod.build_prompt("FAILURE", "try again please")
        self.assertIn("try again please", prompt)

    def test_failure_prompt_includes_valid_actions(self):
        prompt = mod.build_prompt("FAILURE", "let me look")
        # Valid actions are listed in the prompt
        self.assertIn("retry", prompt)
        self.assertIn("escalate", prompt)
        self.assertIn("backtrack", prompt)
        self.assertIn("withdraw", prompt)

    def test_failure_prompt_does_not_use_assert_prompt(self):
        """FAILURE should NOT get the assert-state prompt language."""
        prompt = mod.build_prompt("FAILURE", "try again")
        # ASSERT_PROMPT starts with "You are a CfA (Conversation for Action) review classifier."
        # and has "APPROVE:" and "CORRECT:" rules — these should NOT appear
        self.assertNotIn("APPROVE:", prompt)
        self.assertNotIn("CORRECT:", prompt)

    def test_failure_prompt_does_not_use_escalate_prompt(self):
        """FAILURE should NOT get the escalate-state prompt language."""
        prompt = mod.build_prompt("FAILURE", "try again")
        # ESCALATE_PROMPT has "CLARIFY:" rule — should not appear in FAILURE prompt
        self.assertNotIn("CLARIFY:", prompt)

    def test_failure_prompt_describes_failure_context(self):
        """FAILURE_PROMPT should explain that a process failed."""
        prompt = mod.build_prompt("FAILURE", "retry please")
        # The FAILURE_PROMPT says "A process has failed"
        self.assertIn("failed", prompt.lower())


class TestClassifyFailureState(unittest.TestCase):
    """classify() correctly handles the FAILURE state end-to-end."""

    def _mock_llm(self, stdout, returncode=0):
        mock = MagicMock()
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_failure_retry(self):
        with patch('subprocess.run', return_value=self._mock_llm("retry\t")):
            result = mod.classify("FAILURE", "try again")
        self.assertEqual(result, "retry\t")

    def test_failure_escalate_with_feedback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("escalate\tI need to check the logs")):
            result = mod.classify("FAILURE", "let me look at the logs")
        self.assertTrue(result.startswith("escalate\t"))
        self.assertIn("logs", result)

    def test_failure_backtrack(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "backtrack\tThe plan assumed network access")):
            result = mod.classify("FAILURE", "wrong approach, rethink it")
        self.assertTrue(result.startswith("backtrack\t"))

    def test_failure_withdraw(self):
        with patch('subprocess.run', return_value=self._mock_llm("withdraw\t")):
            result = mod.classify("FAILURE", "forget it, cancel everything")
        self.assertEqual(result, "withdraw\t")

    def test_failure_llm_returns_dialog_gives_fallback(self):
        """If LLM hallucinates 'dialog' at FAILURE, it should fallback."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("dialog\tWhat went wrong?")):
            result = mod.classify("FAILURE", "what happened?")
        self.assertTrue(result.startswith("__fallback__"))

    def test_failure_empty_response_returns_fallback(self):
        result = mod.classify("FAILURE", "")
        self.assertTrue(result.startswith("__fallback__"))

    def test_failure_llm_timeout_returns_fallback(self):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mod.classify("FAILURE", "retry please")
        self.assertTrue(result.startswith("__fallback__"))

    def test_failure_llm_invalid_action_returns_fallback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("approve\tsomething")):
            result = mod.classify("FAILURE", "looks good to retry")
        self.assertTrue(result.startswith("__fallback__"))


if __name__ == "__main__":
    unittest.main()
