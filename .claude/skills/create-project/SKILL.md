---
name: create-project
description: Create a new project directory with full scaffolding and register it in TeaParty. Dialogs with the human to collect path, name, and frontmatter before calling CreateProject.
argument-hint: <project-name> [--path <path>]
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Create Project

Create a new TeaParty project from scratch. Do not call `CreateProject` until you have collected all required information from the human.

Read `phase-dialog.md` in this skill directory and begin.
