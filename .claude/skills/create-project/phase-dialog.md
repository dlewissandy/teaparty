# Phase: Dialog

Collect all information needed to create a new project before proceeding. Do not call `CreateProject` until every required field is confirmed.

1. Ask the human where to create the project. Navigate the filesystem to help pick a parent directory if needed (list candidates such as `~/git/`, `~/projects/`).
2. Collect the following fields. Read `schema.md` for the full field reference.

   Required:
   - `path` — where the new project directory will be created (must not exist yet)
   - `name` — display name, must be unique in the registry
   - `description` — one-line description
   - `lead` — agent name for project lead
   - `decider` — human name with final approval authority

3. Confirm the collected values with the human before proceeding.
4. If the human withdraws or says they do not want to proceed, call `WithdrawSession` and stop.

**Next:** Read `phase-scaffold.md` in this skill directory.
