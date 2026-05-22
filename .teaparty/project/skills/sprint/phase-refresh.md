# Phase 3: Refresh

Pull external GitHub changes into the local cache.

`Delegate(scrum-master, "Refresh the sprint board against GitHub.", skill='refresh-board')`. When the reply arrives, `CloseConversation` to merge the updated cache into your worktree.

The scrum-master will tell you what changed: new issues added to the cache and the board, externally-closed issues moved to Done, frontmatter brought back into agreement with GitHub. Read its reply before continuing — newly-added issues likely need triage decisions on the next pass.

If the scrum-master escalates (rate limits, auth failure, GitHub unreachable), halt and `AskQuestion` to the human with the failure detail.

---

**Next:** Read `phase-triage.md` in this skill directory.
