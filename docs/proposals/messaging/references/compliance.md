# Compliance & Deployment

Anthropic's terms draw a hard line between consumer subscription use (OAuth, Free/Pro/Max plans) and API key use (Console, Bedrock, Vertex). This affects the messaging system directly.

## What the Terms Say

- OAuth tokens from Free/Pro/Max accounts are for Claude Code and Claude.ai only. Using them in any other product, tool, or service is a violation of the Consumer Terms.
- "Automated or non-human means, whether through a bot, script, or otherwise" are prohibited except when accessed via API key.
- Developers building products or services must use API key authentication through Claude Console or a supported cloud provider.
- Pro and Max plan usage limits "assume ordinary, individual usage."

## What This Means for TeaParty

The POC running locally for single-user development is ordinary individual usage. The current `claude -p` invocations under a subscription plan are fine for personal research and development.

The moment TeaParty routes messages through Slack, Teams, or any external adapter, it becomes a product or service built on Claude. A Slack bot that invokes `claude -p` on behalf of a user is automated non-human access. This requires API key authentication under the Commercial Terms, not subscription OAuth.

The multi-session orchestrator (concurrent `claude -p` for subteams, dispatch parallelism) may also exceed "ordinary, individual usage" at scale. API keys are the safe path for any deployment beyond single-user local development.

## Deployment Constraints

| Deployment | Auth Required | Terms |
|---|---|---|
| Local POC (single user, TUI) | OAuth or API key | Consumer Terms |
| Multi-project orchestration at scale | API key recommended | Commercial Terms |
| Slack/Teams/external adapter | API key required | Commercial Terms |
| Mobile access via external app | API key required | Commercial Terms |

The adapter interface is auth-agnostic — it doesn't care how `claude -p` authenticates. But the deployment documentation must specify that any non-local adapter requires API key authentication. The POC adapter (local SQLite + Textual) works under either auth method. External adapters require Commercial Terms.

This is not a design constraint — the architecture doesn't change. It is a deployment constraint that must be documented and enforced at the configuration level, not the code level.

## Cross-Machine Agent Communication Is Out of Scope

Any feature that requires invoking `claude -p` on another user's machine — using their account credentials — is prohibited under current licensing terms. This rules out:

- **Liaison mode** ([proxy-review](../../proxy/proposal.md)) — querying another human's proxy, which runs under their `claude -p` session on their machine
- **Cross-machine message bus** — routing messages to agents running under different users' accounts
- **Federated proxy queries** — reading another user's `.proxy-memory.db` via their agent

These features would require migrating from `claude -p` (subscription OAuth) to API key authentication under Commercial Terms, and likely an agent backend that can serve requests on behalf of multiple users. This is a platform-level change, not a TeaParty design decision.

All Milestone 3 proposals are designed for single-machine, single-user operation. Multi-user features are explicitly deferred and marked as "Future" in their respective proposals.

## References

- [Anthropic Legal and Compliance](https://code.claude.com/docs/en/legal-and-compliance)
- [Anthropic Terms of Service](https://www.anthropic.com/terms)
- [Anthropic Usage Policy](https://www.anthropic.com/news/usage-policy-update)
