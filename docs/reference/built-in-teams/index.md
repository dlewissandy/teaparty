# Built-in Teams

Default workgroup definitions for the management catalog. Available to any project;
not added to a project's active team unless explicitly opted in.

## Teams

| Team | Lead | Description |
|------|------|-------------|
| [research](research.md) | research-lead | Web, academic literature, patents, and video |
| [writing](writing.md) | writing-lead | Content production across formats and registers |
| [editorial](editorial.md) | editorial-lead | Prose quality, accuracy, style, and voice |
| [quality-control](quality-control.md) | quality-control-lead | Functional correctness, test coverage, AI detection |
| [art](art.md) | art-lead | Diagrams, vector graphics, and generative imagery |
| [analytics](analytics.md) | analytics-lead | Data analysis and visualization |
| [planning](planning.md) | planning-lead | Strategy, risk, and roadmap design |
| [intake](intake.md) | intake-lead | Requirements gathering and intent alignment |
| [coding](coding.md) | coding-lead | Implementation, testing, and code review *(existing)* |
| [configuration](configuration.md) | configuration-lead | Agent, workgroup, and skills configuration *(existing)* |

## Standard workgroup-lead tools

Every workgroup lead has the same function — decompose a task, delegate to
members, consolidate the results, reconcile conflicts, relay between
members and external callers, and decide when the work is done. The
specialization is in the lead's description and team scope, not in its
tool set. All leads carry the following allowlist:

| Category | Tools |
|----------|-------|
| Inspection | `Read`, `Glob`, `Grep` |
| Authoring  | `Write`, `Edit` |
| External   | `WebSearch`, `WebFetch` |
| Dispatch   | `mcp__teaparty-config__Send`, `mcp__teaparty-config__Reply` (implicit), `mcp__teaparty-config__AskQuestion`, `mcp__teaparty-config__CloseConversation` |
| Discovery  | `mcp__teaparty-config__GetAgent`, `mcp__teaparty-config__ListAgents`, `mcp__teaparty-config__GetWorkgroup`, `mcp__teaparty-config__ListWorkgroups` |

Each lead's design-doc entry below refers back to this allowlist rather
than restating it.

## Skills

Skills carried by all team members.

| Skill | Description |
|-------|-------------|
| [digest](digest.md) | Write findings to team scratch; hierarchical, 200-line limit per file |

## Tool gaps

Tools required by agents that do not yet exist.

| Document | Description |
|----------|-------------|
| [missing-tools.md](missing-tools.md) | Image generation, YouTube transcripts, academic databases, patent search, browser automation |

## Candidate future teams

Identified as gaps; not yet defined.

| Team | Lead | Members | Notes |
|------|------|---------|-------|
| **security** | security-lead | threat-modeler, vulnerability-analyst, compliance-checker | Any software project |
| **devops** | devops-lead | infrastructure-engineer, deployment-specialist, monitoring-analyst | CI/CD, deployment, observability |
| **ux** | ux-lead | wireframe-designer, usability-tester, accessibility-reviewer | Projects with user-facing interfaces |
| **communications** | comms-lead | social-media-writer, pr-writer, newsletter-writer | External-facing voice and marketing |
| **data-engineering** | data-lead | schema-designer, pipeline-engineer, migration-specialist | Distinct from analytics — moves and transforms data |
| **legal** | legal-lead | ip-analyst, license-auditor, compliance-reviewer | IP strategy, licensing, regulatory compliance |
