# Phase: Dialog

Read discoverable metadata from the project directory to infer frontmatter fields, then confirm with the human.

1. Read `pyproject.toml`, `README.md` (or `README`), and `.teaparty/project.yaml` if present. Infer `name`, `description`, `lead`, and `decider` from what you find.
2. Present what you inferred to the human. Confirm each field or ask for corrections. Collect any required fields that could not be inferred.

   Required fields (from `schema.md` in the create-project skill):
   - `name` — must be unique in the registry
   - `description` — one-line description
   - `lead` — agent name
   - `decider` — human name with final approval authority

3. If the human withdraws or says they do not want to proceed, call `WithdrawSession` and stop.

Do not proceed until all required fields are confirmed.

**Next:** Read `phase-register.md` in this skill directory.
