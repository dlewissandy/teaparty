# Team Hierarchy Structure

The organizational hierarchy demonstrates how the same team lead pattern repeats at every level.

```
Management Team
├── Office Manager (team lead)
├── Human (decider)
│
├── Project Team: POC
│   ├── Project Lead (team lead)
│   ├── Proxy (stands in for human)
│   │
│   ├── Workgroup: Coding
│   │   ├── Workgroup Lead (team lead)
│   │   └── Coding agents
│   │
│   └── Workgroup: Research
│       ├── Workgroup Lead (team lead)
│       └── Research agents
│
└── Project Team: Joke-book
    ├── Project Lead (team lead)
    ├── Proxy (stands in for human)
    └── ...
```

At each level, the structure is consistent: a team lead coordinates subteams using the same mechanisms (AskTeam, dispatches, shared memory). There is no architecturally special "top" — the hierarchy is extensible upward.
