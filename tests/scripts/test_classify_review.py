#!/usr/bin/env python3
"""Tests for classify_review.py."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import teaparty.scripts.classify_review as mod


class TestStateActions(unittest.TestCase):
    """STATE_ACTIONS covers all documented CfA review states."""

    def test_all_assert_states_present(self):
        for state in ["WORK_ASSERT", "WORK_ASSERT"]:
            self.assertIn(state, mod.STATE_ACTIONS)

    def test_all_escalate_states_present(self):
        self.assertIn("WORK_ASSERT", mod.STATE_ACTIONS)

    def test_task_level_states_absent(self):
        """Task-level states are no longer in the state machine."""
        for state in ["TASK_ASSERT", "TASK_ESCALATE", "TASK_IN_PROGRESS"]:
            self.assertNotIn(state, mod.STATE_ACTIONS,
                             f"{state} must not appear in STATE_ACTIONS")

    def test_plan_level_states_absent(self):
        """PLAN_ASSERT / PLANNING_* collapsed into the planning skill's internal flow."""
        for state in ["PLAN_ASSERT", "PLANNING_QUESTION", "PLANNING_RESPONSE", "PLANNING_ESCALATE"]:
            self.assertNotIn(state, mod.STATE_ACTIONS,
                             f"{state} must not appear in STATE_ACTIONS")

    def test_work_assert_actions(self):
        actions = mod.STATE_ACTIONS["WORK_ASSERT"]
        for required in ("dialog", "approve", "correct", "withdraw"):
            self.assertIn(required, actions)

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


    def test_state_actions_derived_from_state_machine(self):
        """STATE_ACTIONS should be derived, not hardcoded — verify key invariant."""
        # Every action in STATE_ACTIONS (except dialog) must be a valid
        # state machine edge for that state
        import json
        machine_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'teaparty', 'cfa', 'statemachine', 'cfa-state-machine.json')
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


    def test_refine_intent_valid_at_work_assert(self):
        valid = set(mod.STATE_ACTIONS["WORK_ASSERT"])
        action, feedback = mod.parse_output(
            "refine-intent\tChange objective to research paper",
            valid)
        self.assertEqual(action, "refine-intent")



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
        prompt = mod.build_prompt("WORK_ASSERT", "looks good", "intent", "plan")
        self.assertIn("WORK_ASSERT", prompt)
        self.assertIn("looks good", prompt)
        self.assertIn("refine-intent", prompt)  # valid action listed

    def test_escalate_state_uses_escalate_prompt(self):
        prompt = mod.build_prompt("WORK_ASSERT", "use postgres")
        self.assertIn("WORK_ASSERT", prompt)
        self.assertIn("use postgres", prompt)
        self.assertIn("WITHDRAW", prompt.upper())

    def test_unknown_state_uses_generic_assert(self):
        prompt = mod.build_prompt("UNKNOWN_STATE", "test")
        self.assertIn("approve", prompt)
        self.assertIn("correct", prompt)

    def test_context_included(self):
        prompt = mod.build_prompt("WORK_ASSERT", "ok",
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
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertEqual(result, "approve\t")

    def test_correct_with_feedback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("correct\tFix section 1")):
            result = mod.classify("WORK_ASSERT", "change section 1")
        self.assertEqual(result, "correct\tFix section 1")

    def test_refine_intent(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm(
                       "refine-intent\tBuild research paper instead")):
            result = mod.classify("WORK_ASSERT",
                                  "actually, let's build the research paper first")
        self.assertTrue(result.startswith("refine-intent\t"))

    def test_withdraw(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("withdraw\t")):
            result = mod.classify("WORK_ASSERT", "let's call this whole thing off")
        self.assertEqual(result, "withdraw\t")

    def test_escalate_withdraw(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("withdraw\t")):
            result = mod.classify("WORK_ASSERT", "forget it, cancel")
        self.assertEqual(result, "withdraw\t")

    def test_empty_response_returns_fallback(self):
        result = mod.classify("WORK_ASSERT", "")
        self.assertTrue(result.startswith("__fallback__"))

    def test_whitespace_response_returns_fallback(self):
        result = mod.classify("WORK_ASSERT", "   ")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_timeout_returns_fallback(self):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("claude", 30)):
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_not_found_returns_fallback(self):
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_nonzero_exit_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("", 1)):
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_empty_output_returns_fallback(self):
        with patch('subprocess.run', return_value=self._mock_llm("  ")):
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_llm_invalid_action_returns_fallback(self):
        with patch('subprocess.run',
                   return_value=self._mock_llm("explode\teverything")):
            result = mod.classify("WORK_ASSERT", "looks good")
        self.assertTrue(result.startswith("__fallback__"))

    def test_summaries_passed_to_prompt(self):
        """Verify summaries reach the prompt (inspect the subprocess call)."""
        with patch('subprocess.run',
                   return_value=self._mock_llm("approve\t")) as mock_run:
            mod.classify("WORK_ASSERT", "ok",
                         intent_summary="Build widget",
                         plan_summary="Step 1 setup")
        call_args = mock_run.call_args
        prompt_input = call_args.kwargs.get('input', call_args[1].get('input', ''))
        self.assertIn("Build widget", prompt_input)
        self.assertIn("Step 1 setup", prompt_input)


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
        valid = set(mod.STATE_ACTIONS["WORK_ASSERT"])
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
            result = mod.classify("WORK_ASSERT",
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
            "WORK_ASSERT", "I already told you",
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
