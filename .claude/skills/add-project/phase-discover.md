# Phase: Discover

Ask the human for the project directory path. Explain you need the absolute path to the existing project directory before proceeding.

1. If the human provides a path, verify it exists and contains a git repository (`.git/` directory). If it does not exist or is not a git repo, tell the human what you found and ask them to confirm or provide a different path.
2. If the human does not know the path or asks you to browse, list candidate directories (e.g., `~/git/`, `~/projects/`, `~/code/`) and let the human confirm which one.
3. If the human withdraws or says they do not want to proceed, call `WithdrawSession` and stop.

Do not proceed to the next phase until you have a confirmed, existing directory path.

**Next:** Read `phase-dialog.md` in this skill directory.
