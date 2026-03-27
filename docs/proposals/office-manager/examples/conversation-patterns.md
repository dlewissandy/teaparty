# Conversation Patterns

## Inquiry

> "What's going on with the POC project?"

The office manager reads session state files, git logs, dispatch results, CfA state JSONs. It synthesizes a narrative: what's running, what's blocked, what completed recently, what looks unusual.

> "Why did the planning phase backtrack?"

It reads the CfA state history and the backtrack feedback, explains the chain of events.

## Steering

> "Focus on security aspects first for all active sessions."

The office manager records this as a priority directive in shared memory. When the proxy next retrieves memories at a gate, this high-activation chunk surfaces and influences the review. Steering propagates through memory, not by modifying prompts in active sessions.

The human needs to know whether their steering took effect. On the next conversation, the office manager can inspect recent proxy gate decisions and their retrieval context to report whether the steering chunk was retrieved and influential.

> "That approach to the database migration won't work because we're switching to Postgres next quarter."

Context that exists only in the human's head. The office manager records it as a memory chunk. When agents next work on database-related tasks, this context is retrievable.

## Action

> "Can you make sure all my projects are committed and pushed?"

The office manager uses its tools to check git status across all project worktrees, commits and pushes where needed, reports what it did.

> "Withdraw the current session on the POC project."

The office manager exercises its team-lead authority over the dispatch, setting the CfA state to WITHDRAWN.

> "Hold the presses — stop all active dispatches."

The office manager pauses all active dispatches. No new phases launch; work already in progress completes.
