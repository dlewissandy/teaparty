# Phase 4: Prioritize

Apply the tier decisions you made in triage to the board and the local cache.

`Delegate(scrum-master, "Apply these tier assignments.", skill='prioritize', args={tier_assignments: <map of issue_number → tier>})`.

`prioritize` is mechanical: Tier 1 → Approved, other tiers → Backlog, Won't-Do → Won't Do. It does not decide tiers — you do. It only applies what you hand it.

When the scrum-master replies, `CloseConversation` to merge the updated cache. Read the reply for any issues it could not place (e.g., a number that does not exist on the board); those need follow-up in the next triage pass.

---

**Next:** Read `phase-triage.md` in this skill directory.
