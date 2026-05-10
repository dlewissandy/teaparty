# quality-assurance

Dispatch here to verify that the produced work matches what was asked for and meets the gates between phases. The team checks intent fidelity, acceptance criteria, and definition-of-done — the *did we build the right thing?* question. Distinct from [quality-control](quality-control.md), which checks the artifact's behavior under tests. Dispatch after QC.

---

## quality-assurance-lead

The quality-assurance-lead receives a diff and the source-of-truth (issue, design doc, acceptance criteria), dispatches the audit and acceptance work to its members, consolidates findings into a single verdict (clean, advisory, or blocking), and reports back. It requests clarification when intent is genuinely ambiguous — guessing would defeat the audit's purpose.

**Tools:** [standard workgroup-lead tools](index.md#standard-workgroup-lead-tools)
**Skills:** digest

---

## auditor

Dispatch when a diff needs an intent-fidelity audit against an issue, design doc, or proposal. Reads the source-of-truth and the diff side by side and reports findings — what the source asks for, what the diff delivers, where they diverge. Read-only; does not modify code.

**Tools:** Read, Write, Grep, Glob, Bash
**Skills:** digest

---

## qa-reviewer

Dispatch when completed work needs to be checked against its stated acceptance criteria. Reads requirements and the implementation side by side and reports where they agree or diverge. Not a tester — a verifier of intent vs. outcome.

**Tools:** Read, Write, Glob, Grep
**Skills:** digest

---

## acceptance-tester

Dispatch when user stories or requirements need to be validated against the implemented behavior. Works from the user's perspective, not the implementation's. Not for technical correctness — for behavioral completeness against stated requirements.

**Tools:** Read, Write, Bash
**Skills:** digest
