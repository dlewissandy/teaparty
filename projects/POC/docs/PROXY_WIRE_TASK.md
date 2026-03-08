# Proxy Wire Task: Context-Aware Human Proxy Wiring

Wire context-aware human proxy into shell orchestration and add test coverage.

WORKTREE: /Users/darrell/git/teaparty/poc/projects/POC/.worktrees/session-20260307-193509
All file edits must be made INSIDE the worktree. Prepend the worktree path to get absolute paths.

FILES TO EDIT (3 total, all inside worktree):
1. intent.sh
2. plan-execute.sh
3. scripts/tests/test_human_proxy.py
DO NOT MODIFY scripts/human_proxy.py (read-only reference only).

BACKGROUND: scripts/human_proxy.py already has complete Phase 1 and 2 Python implementations. All CLI flags (--artifact, --questions, --reason, --artifact-length) are already implemented. should_escalate() already accepts artifact_path. record_outcome() already accepts artifact_length and question_patterns.

The gap: intent.sh and plan-execute.sh define local proxy_decide() and proxy_record() shell functions that do not pass artifact paths or dialog data. This wires the existing Python code into the shell orchestration and adds test coverage.

## CHANGE 1: proxy_decide() function (update in BOTH intent.sh AND plan-execute.sh)

Locate the proxy_decide() function in each script. Replace it with:

```bash
proxy_decide() {
  local state="$1"
  local artifact_path="${2:-}"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "$PROXY_MODEL" && -f "$PROXY_MODEL" ]]; then
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --decide --state "$state" --task-type "$task_type" \
      --artifact "${artifact_path:-}" \
      --model "$PROXY_MODEL" 2>/dev/null || echo "escalate"
  else
    echo "escalate"
  fi
}
```

## CHANGE 2: proxy_record() function (update in BOTH intent.sh AND plan-execute.sh)

Locate proxy_record() in each script. Replace with:

```bash
proxy_record() {
  local state="$1" outcome="$2"
  local diff_summary="${3:-}"
  local questions="${4:-}"
  local reason="${5:-}"
  local artifact_len="${6:-0}"
  local task_type="${POC_PROJECT:-default}"
  if [[ -n "$PROXY_MODEL" ]]; then
    local extra_args=()
    [[ -n "$diff_summary" ]]    && extra_args+=(--diff "$diff_summary")
    [[ -n "$questions" ]]       && extra_args+=(--questions "$questions")
    [[ -n "$reason" ]]          && extra_args+=(--reason "$reason")
    [[ "$artifact_len" -gt 0 ]] && extra_args+=(--artifact-length "$artifact_len")
    python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
      --record --state "$state" --task-type "$task_type" \
      --outcome "$outcome" ${extra_args[@]+"${extra_args[@]}"} \
      --model "$PROXY_MODEL" 2>/dev/null || true
  fi
}
```

## CHANGE 3: intent.sh call sites

### 3a. review_intent() function

Add artifact_len computation at the top of review_intent() (right after `local intent_path="$1"`):

```bash
  local intent_artifact_len
  intent_artifact_len=$(wc -c < "$intent_path" 2>/dev/null || echo 0)
```

Update proxy_decide call (currently `proxy_decide "INTENT_ASSERT"`) to:
```bash
  PROXY_ACTION=$(proxy_decide "INTENT_ASSERT" "$intent_path")
```

Update every proxy_record call inside review_intent():
- Proxy auto-approve path: `proxy_record "INTENT_ASSERT" "approve" "" "" "" "$intent_artifact_len"`
- Human approve path: `proxy_record "INTENT_ASSERT" "approve" "" "" "" "$intent_artifact_len"`
- Withdraw path: `proxy_record "INTENT_ASSERT" "withdraw" "" "" "" "$intent_artifact_len"`
- Correct path: `proxy_record "INTENT_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$intent_artifact_len"`
- Correct fallback at bottom of review_intent(): `proxy_record "INTENT_ASSERT" "correct" "$CFA_RESPONSE" "$CFA_RESPONSE" "$CFA_RESPONSE" "$intent_artifact_len"`

### 3b. INTENT_ESCALATE section (the `if [[ -f "$ESCALATION_FILE" ]]; then` block in the main loop)

Add artifact_len computation right after `intent_cfa_set "INTENT_ESCALATE"` (or right before the first proxy_record call):

```bash
    local escal_artifact_len
    escal_artifact_len=$(wc -c < "$ESCALATION_FILE" 2>/dev/null || echo 0)
```

Update the two proxy_record calls:
- Withdraw: `proxy_record "INTENT_ESCALATE" "withdraw" "" "" "" "$escal_artifact_len"`
- Clarify: `proxy_record "INTENT_ESCALATE" "clarify" "$CFA_RESPONSE" "$CFA_RESPONSE" "" "$escal_artifact_len"`

## CHANGE 4: plan-execute.sh call sites

Read the file carefully before editing. There are two flows (new flow and legacy flow). Apply changes to both.

### TASK_ESCALATE new flow (~line 451 sets TASK_ESCALATION)

Right before `cfa_review_loop "TASK_ESCALATE" ...` (new flow), add:
```bash
    task_escal_len=$(wc -c < "$TASK_ESCALATION" 2>/dev/null || echo 0)
```

Update the two proxy_record calls that follow:
- withdraw: `proxy_record "TASK_ESCALATE" "withdraw" "" "" "" "$task_escal_len"`
- clarify: `proxy_record "TASK_ESCALATE" "clarify" "$CFA_RESPONSE" "$CFA_RESPONSE" "" "$task_escal_len"`

### WORK_ASSERT new flow (~line 521)

Update proxy_decide call:
```bash
PROXY_ACTION=$(proxy_decide "WORK_ASSERT" "$STREAM_TARGET/.work-summary.md")
```

Add immediately after:
```bash
work_artifact_len=$(wc -c < "$STREAM_TARGET/.work-summary.md" 2>/dev/null || echo 0)
```

Update all proxy_record "WORK_ASSERT" calls in this block:
- approve (proxy auto): `proxy_record "WORK_ASSERT" "approve" "" "" "" "$work_artifact_len"`
- approve (human): `proxy_record "WORK_ASSERT" "approve" "" "" "" "$work_artifact_len"`
- correct: `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$work_artifact_len"`
- correct (revise-plan): `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$work_artifact_len"`
- correct (refine-intent): `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$work_artifact_len"`
- withdraw: `proxy_record "WORK_ASSERT" "withdraw" "" "" "" "$work_artifact_len"`
- correct (fallback): `proxy_record "WORK_ASSERT" "correct" "$CFA_RESPONSE" "$CFA_RESPONSE" "$CFA_RESPONSE" "$work_artifact_len"`

### PLANNING_ESCALATE new flow (~line 679, inside `while [[ -f "$STREAM_TARGET/.plan-escalation.md" ]]; do`)

PLAN_ESCALATION is set to "$STREAM_TARGET/.plan-escalation.md" inside the loop. Add right after that assignment:
```bash
    plan_escal_len=$(wc -c < "$PLAN_ESCALATION" 2>/dev/null || echo 0)
```

Update the two proxy_record calls:
- withdraw: `proxy_record "PLANNING_ESCALATE" "withdraw" "" "" "" "$plan_escal_len"`
- clarify: `proxy_record "PLANNING_ESCALATE" "clarify" "$CFA_RESPONSE" "$CFA_RESPONSE" "" "$plan_escal_len"`

### PLAN_ASSERT new flow (~line 769, after PLAN_FILE="$STREAM_TARGET/plan.md")

Add artifact_len computation right after PLAN_FILE=...:
```bash
plan_artifact_len=$(wc -c < "$PLAN_FILE" 2>/dev/null || echo 0)
```

Update proxy_decide call:
```bash
PROXY_ACTION=$(proxy_decide "PLAN_ASSERT" "$PLAN_FILE")
```

Update all proxy_record calls in the PLAN_ASSERT block:
- pre-approved (AUTO_APPROVE_PLAN): `proxy_record "PLAN_ASSERT" "approve" "" "" "" "$plan_artifact_len"`
- proxy auto-approve: `proxy_record "PLAN_ASSERT" "approve" "" "" "" "$plan_artifact_len"`
- human approve: `proxy_record "PLAN_ASSERT" "approve" "" "" "" "$plan_artifact_len"`
- correct: `proxy_record "PLAN_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$plan_artifact_len"`
- correct (refine-intent): `proxy_record "PLAN_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$plan_artifact_len"`
- withdraw: `proxy_record "PLAN_ASSERT" "withdraw" "" "" "" "$plan_artifact_len"`
- correct (fallback): `proxy_record "PLAN_ASSERT" "correct" "$CFA_RESPONSE" "$CFA_RESPONSE" "$CFA_RESPONSE" "$plan_artifact_len"`

### TASK_ESCALATE legacy flow (~line 995 sets LEGACY_TASK_ESCALATION)

Add right before the legacy `cfa_review_loop "TASK_ESCALATE"` call:
```bash
  legacy_task_escal_len=$(wc -c < "$LEGACY_TASK_ESCALATION" 2>/dev/null || echo 0)
```

Update the two proxy_record calls:
- withdraw: `proxy_record "TASK_ESCALATE" "withdraw" "" "" "" "$legacy_task_escal_len"`
- clarify: `proxy_record "TASK_ESCALATE" "clarify" "$CFA_RESPONSE" "$CFA_RESPONSE" "" "$legacy_task_escal_len"`

### WORK_ASSERT legacy flow (~line 1066)

Update proxy_decide call:
```bash
  PROXY_ACTION=$(proxy_decide "WORK_ASSERT" "$STREAM_TARGET/.work-summary.md")
```

Add immediately after:
```bash
  legacy_work_len=$(wc -c < "$STREAM_TARGET/.work-summary.md" 2>/dev/null || echo 0)
```

Update all proxy_record "WORK_ASSERT" calls in the legacy block:
- approve (proxy auto): `proxy_record "WORK_ASSERT" "approve" "" "" "" "$legacy_work_len"`
- approve (human): `proxy_record "WORK_ASSERT" "approve" "" "" "" "$legacy_work_len"`
- correct: `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$legacy_work_len"`
- correct (revise-plan): `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$legacy_work_len"`
- correct (refine-intent): `proxy_record "WORK_ASSERT" "correct" "$REVIEW_FEEDBACK" "${REVIEW_DIALOG_HISTORY:-}" "$REVIEW_FEEDBACK" "$legacy_work_len"`
- withdraw: `proxy_record "WORK_ASSERT" "withdraw" "" "" "" "$legacy_work_len"`
- correct (fallback): `proxy_record "WORK_ASSERT" "correct" "$CFA_RESPONSE" "$CFA_RESPONSE" "$CFA_RESPONSE" "$legacy_work_len"`

## CHANGE 5: scripts/tests/test_human_proxy.py

Add the following to the existing `from human_proxy import (...)` block at the top:
```python
    _check_content,
    _extract_question_patterns,
    ARTIFACT_LENGTH_RATIO_LOW,
    ARTIFACT_LENGTH_RATIO_HIGH,
    QUESTION_PATTERN_MIN_OCCURRENCES,
    PRINCIPLE_VIOLATION_THRESHOLD,
```

Append two new test classes at the end of the file:

### Class 1: TestContentAwareness(DeterministicProxyTestCase)
Docstring: "Phase 1 and Phase 2a/2b content-awareness checks in should_escalate()."

Helper method `_make_trained_entry(self, approve_count=10, differentials=None, question_patterns=None)`:
- entry = _make_entry(approve_count=approve_count, total_count=approve_count, ema_approval_rate=0.9)
- if differentials is not None: entry.differentials = differentials
- if question_patterns is not None: entry.question_patterns = question_patterns
- return entry

Tests to implement:

**test_length_anomaly_short_triggers_escalation**:
- entry = self._make_trained_entry()
- entry.artifact_lengths = [1000] * 5
- Write 200 'a' chars to tempfile
- model = _model_with_entry(entry)
- decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
- assertEqual(decision.action, 'escalate')
- assertIn('short', decision.reasoning.lower())

**test_length_anomaly_long_triggers_escalation**:
- entry.artifact_lengths = [500] * 5
- Write 1200 'a' chars to tempfile
- Assert 'escalate' and 'long' in reasoning.lower()

**test_novelty_detection_correction_keywords_trigger_escalation**:
- diff = {'outcome':'correct','summary':'error handling missing in export function','reasoning':'','timestamp':'2026-01-01'}
- entry = self._make_trained_entry(differentials=[diff])
- artifact_text = 'The export function processes data. Error handling has not been addressed.'
- Assert 'escalate' and 'correction' in reasoning.lower()

**test_missing_artifact_path_degrades_gracefully**:
- decision = should_escalate(model, entry.state, entry.task_type, artifact_path='')
- assertIn(decision.action, ('auto-approve', 'escalate'))

**test_unreadable_artifact_degrades_gracefully**:
- artifact_path='/nonexistent/path/that/will/never/exist-proxy-test.md'
- assertIn(decision.action, ('auto-approve', 'escalate'))

**test_cold_start_suppresses_content_checks**:
- entry = _make_entry(approve_count=2, total_count=2)  # below threshold of 5
- Add correction diff
- Write 'error handling is implemented here' to tempfile
- Assert action=='escalate' and 'cold' in reasoning.lower()

**test_content_check_fires_independently_of_high_confidence**:
- entry = _make_entry(approve_count=20, total_count=20, ema_approval_rate=0.95)
- Add correction diff: summary='error handling missing in export function'
- Write 'the export function processes errors' to tempfile
- Assert action=='escalate' and 'correction' in reasoning.lower()

### Class 2: TestQuestionPatternLearning(DeterministicProxyTestCase)
Docstring: "Phase 2b -- question pattern accumulation and triggering."

Tests to implement:

**test_question_pattern_recorded_after_record_outcome**:
- model = _make_model()
- updated = record_outcome(model, 'PLAN_ASSERT', 'test-project', 'correct',
    question_patterns=[{'question':'Did you handle errors?','concern':'error_handling',
      'reasoning':'because silent failures are worse than noisy ones',
      'disposition':'correct','timestamp':'2026-01-01'}])
- key = 'PLAN_ASSERT|test-project'
- raw = updated.entries[key]
- qps = raw.get('question_patterns', [])
- assertEqual(len(qps), 1)
- assertEqual(qps[0]['concern'], 'error_handling')

**test_phase_2b_fires_when_artifact_lacks_concern_keywords**:
- qp = {'question':'Did you handle errors?','concern':'error_handling','reasoning':'','disposition':'correct','timestamp':'2026-01-01'}
- entry = _make_entry(approve_count=10, total_count=10, ema_approval_rate=0.9)
- entry.question_patterns = [qp, qp]  # 2 occurrences
- Write 'The function processes the input and returns the result.' to tempfile
- Assert action=='escalate' and 'error_handling' in decision.reasoning

**test_phase_2b_includes_reasoning_in_escalation_message**:
- reasoning_text = 'silent failures are worse than noisy ones'
- qp has reasoning=reasoning_text
- entry.question_patterns = [qp, qp]
- Write 'The function processes the input and returns the result.' to tempfile
- Assert action=='escalate' and reasoning_text in decision.reasoning

**test_extract_question_patterns_captures_reasoning_from_because_clause**:
- dialog = 'Did you handle errors? because silent failures are worse than noisy ones'
- patterns = _extract_question_patterns(dialog, 'correct')
- assertTrue(len(patterns) > 0)
- error_patterns = [p for p in patterns if p.get('concern') == 'error_handling']
- assertTrue(len(error_patterns) > 0)
- assertTrue(len(error_patterns[0].get('reasoning', '')) > 0)

## VERIFICATION

After making all edits, run:
```bash
cd /Users/darrell/git/teaparty/poc/projects/POC/.worktrees/session-20260307-193509/poc/projects/POC
python3 -m pytest scripts/tests/test_human_proxy.py -v 2>&1 | tail -40
```

All existing tests must pass. TestContentAwareness and TestQuestionPatternLearning must also pass.

Also verify shell syntax:
```bash
bash -n intent.sh && echo "intent.sh syntax OK"
bash -n plan-execute.sh && echo "plan-execute.sh syntax OK"
```

## CONSTRAINTS
- Three files only (intent.sh, plan-execute.sh, scripts/tests/test_human_proxy.py) -- no other files touched.
- Do NOT modify scripts/human_proxy.py.
- All shell wiring must use ${REVIEW_DIALOG_HISTORY:-} (with default) to avoid unbound variable errors.
- Artifact length tracked at proxy_record time (via wc -c), not at proxy_decide time.
