# quality-control

Dispatch here when completed work needs to be verified against its requirements before it is accepted. The team checks whether the work does what it was supposed to do — functional correctness, test coverage, regression, performance, and AI generation signals. Dispatch after implementation, not during it.

---

## quality-control-lead

The quality-control-lead reviews the work product against its acceptance criteria, dispatches appropriate reviewers, consolidates findings, and reports a pass/fail verdict with evidence. It requests clarification when acceptance criteria are missing or ambiguous — QC cannot run without a definition of done. It declares completion when all checks have been run and the verdict is clear, not only when everything passes.

**Tools:** Read, Write, Glob, Grep, Bash, mcp__teaparty-config__AskQuestion
**Skills:** digest

---

## qa-reviewer

Dispatch when completed work needs to be checked against its stated acceptance criteria. Reads requirements and the implementation side by side and reports where they agree or diverge. Not a tester — a verifier of intent vs. outcome.

**Tools:** Read, Write, Glob, Grep
**Skills:** digest

---

## test-reviewer

Dispatch when the test suite itself needs evaluation — coverage, quality, and whether the tests would actually catch the bugs they are supposed to catch. Not for running tests; for judging whether the tests are adequate.

**Tools:** Read, Glob, Grep, Bash
**Skills:** digest

---

## regression-tester

Dispatch when a change needs to be checked for unintended breakage in previously working behavior. Requires a baseline — either a passing test suite or documented prior behavior — to compare against.

**Tools:** Bash, Read, Glob, Grep
**Skills:** digest

---

## acceptance-tester

Dispatch when user stories or requirements need to be validated against the implemented behavior. Works from the user's perspective, not the implementation's. Not for technical correctness — for behavioral completeness against stated requirements.

**Tools:** Read, Write, Bash
**Skills:** digest
**Missing tools:** playwright (see [missing-tools.md](missing-tools.md))

---

## performance-analyst

Dispatch when the task requires measuring latency, throughput, resource consumption, or scalability under load. Runs benchmarks and profiles the system. Not for functional correctness — for characterizing performance against targets.

**Tools:** Bash, Read, Write, Glob, Grep
**Skills:** digest

---

## ai-smell

Dispatch when content needs to be checked for AI generation patterns — generic phrasing, robotic hedging, over-qualified sentences, or unnaturally balanced structure. Returns a verdict and specific flagged passages. Not for prose quality; for authenticity signal.

**Tools:** Read, Write
**Skills:** digest
