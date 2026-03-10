---
id: 9fc44777-5e78-43c9-914c-94eb43e39e15
type: procedural
domain: task
importance: 0.5
phase: unknown
status: active
reinforcement_count: 0
last_reinforced: '2026-03-10'
created_at: '2026-03-10'
---
## [2026-03-10] Multi-Team Dispatch Output Handoff Protocol

**Convention:** When one team's output feeds another team's input (sequential dispatch dependencies), dispatch task definitions must specify: (1) exact output file path; (2) a completion signal mechanism (file existence check, async message, or status registry); (3) documented handoff procedure. The producing team should explicitly notify the consuming team when ready, rather than relying on implicit discovery.

**Applies to:** All multi-stage dispatch workflows where one team's output feeds downstream work (e.g., research → writing, analysis → implementation). Prevents output discovery friction and ensures dependent teams can start work without extensive path searching.
