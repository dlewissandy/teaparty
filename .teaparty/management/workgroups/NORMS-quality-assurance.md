# Quality Assurance Workgroup Norms

## Scope

QA is the *did we build the right thing?* function. QC tests the artifact's behavior; QA verifies the artifact matches the asked-for intent.

- **Intent fidelity** — does the diff implement what the issue/spec/design doc asks for, neither more nor less?
- **Acceptance criteria** — are each issue's acceptance criteria explicitly satisfied by an observable property of the diff?
- **Definition-of-done** — are the gates between phases (coding → QC → QA → done) met before advancement?

## Members

- `auditor` — runs intent-fidelity audits against issue and design docs; produces findings text.
- `qa-reviewer` — reviews against acceptance criteria and quality bar.
- `acceptance-tester` — verifies user-visible acceptance scenarios.

## Boundary with QC

QC owns: test execution, regression coverage, performance, AI-smell. QA owns: intent fidelity, acceptance, process gates. The two are independent verifications — neither subsumes the other. Both must pass before software-development considers a hop done.

## Findings discipline

Findings are intent statements (what should be true and isn't), not bug reports. They name the gap, the source-of-truth (issue/spec/design doc), and the observable that would close the gap.
