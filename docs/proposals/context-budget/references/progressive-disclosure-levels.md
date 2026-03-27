# Progressive Disclosure Hierarchy

Context budget management integrates with the progressive disclosure model used throughout the system. Information is loaded only when needed:

1. **Agent prompt** — always loaded, minimal (role, current task, phase)
2. **Scratch files** — loaded on demand after compaction, or when the agent needs to recall a decision
3. **Worktree artifacts** — loaded when the agent needs to read or modify work products
4. **Team configuration YAML** — loaded when the agent needs to understand team structure
5. **`.claude/` artifacts** — loaded when the agent needs skill content or agent definitions

Each level is loaded only when needed. The agent's prompt is lean. Everything else is a Read away. This hierarchy ensures that context budget is spent efficiently, with immediate working memory in scratch files and deeper details available through explicit Read operations.
