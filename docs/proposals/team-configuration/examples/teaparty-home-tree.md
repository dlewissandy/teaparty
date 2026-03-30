# TeaParty and Project Directory Structure

This shows the directory layout for TeaParty's management level and example projects.

```
~/.teaparty/                                   <- TeaParty home (management level)
├── teaparty.yaml                              <- management team config (includes teams: with paths)
├── .claude/
│   └── skills/                               <- org-level skill installations (discovered by bridge)
│       ├── sprint-plan/
│       │   └── SKILL.md
│       └── audit/
│           └── SKILL.md
├── workgroups/                                <- org-level shared workgroups
│   ├── configuration.yaml
│   ├── coding.yaml
│   └── research.yaml
├── stats/                                     <- management-level stats
└── sessions/                                  <- office manager chat sessions

~/git/my-backend/                              <- a project (anywhere on disk)
├── .git/
├── .claude/                                   <- Claude Code native artifacts
│   ├── agents/
│   ├── skills/
│   └── settings.json
├── .teaparty/                                 <- TeaParty project config
│   ├── project.yaml
│   └── workgroups/
│       └── coding.yaml                        <- project override (trumps org-level)
└── src/                                       <- project's own structure (untouched)

~/work/joke-book/                              <- another project (different location)
├── .git/
├── .claude/
├── .teaparty/
│   ├── project.yaml
│   └── workgroups/
│       └── writing.yaml
└── ...
```

**Key points:**
- TeaParty home is always `~/.teaparty/`. It's singleton — one per installation.
- Projects can live anywhere on disk. Their paths are listed under `teams:` in `teaparty.yaml`.
- Each project has its own `.git/`, `.claude/`, and `.teaparty/` directories.
- Org-level shared workgroups live in `~/.teaparty/workgroups/`. Project-level overrides live in `{project}/.teaparty/workgroups/`.
