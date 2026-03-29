// ── Mock Data ──────────────────────────────────

const mockData = {

  // ── Config hierarchy ──────────────────────────
  config: {
    management: {
      name: "Management Team",
      description: "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor.",
      agents: [
        { name: "Office Manager", role: "Team Lead", model: "lorem-opus-4", status: "active" },
        { name: "Auditor", role: "Specialist", model: "lorem-opus-4", status: "idle" },
        { name: "Researcher", role: "Specialist", model: "lorem-opus-4", status: "idle" },
        { name: "Strategist", role: "Specialist", model: "lorem-opus-4", status: "idle" },
      ],
      skills: [
        { name: "sprint-plan", files: 3 },
        { name: "audit", files: 3 },
        { name: "close-milestone", files: 1 },
        { name: "fix-issue", files: 1 },
      ],
      hooks: [
        { event: "PreToolUse", matcher: "Bash", type: "command" },
        { event: "PostToolUse", matcher: "Edit|Write", type: "command" },
        { event: "Stop", matcher: "", type: "agent" },
      ],
      crons: [
        { name: "nightly-test-sweep", schedule: "0 2 * * *", status: "active" },
        { name: "weekly-digest", schedule: "0 9 * * 1", status: "active" },
      ],
      workgroups: [
        { name: "Configuration Team", lead: "Config Lead", agents: 3, description: "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris." },
        { name: "Operations", lead: "Ops Lead", agents: 2, description: "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum." },
      ],
      humans: [
        { name: "Darrell", role: "decider", self: true },
        { name: "Alice", role: "advisor" },
        { name: "Bob", role: "informed" },
      ],
    },
    projects: {
      poc: {
        name: "POC",
        description: "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt.",
        decider: "Darrell",
        lead: "POC Project Lead",
        agents: [
          { name: "POC Project Lead", role: "Team Lead", model: "claude-opus-4", status: "active", source: "generated" },
          { name: "QA Reviewer", role: "Specialist", model: "claude-sonnet-4", status: "idle", source: "local" },
          { name: "Auditor", role: "Specialist", model: "claude-opus-4", status: "idle", source: "shared" },
        ],
        workgroups: [
          { name: "Coding", lead: "Coding Lead", agents: 3, source: "local" },
          { name: "Research", lead: "Research Lead", agents: 2, source: "local" },
          { name: "Writing", lead: "Writing Lead", agents: 2, source: "local" },
          { name: "Configuration Team", lead: "Config Lead", agents: 3, source: "shared" },
        ],
        skills: [
          { name: "fix-issue", files: 1, source: "shared" },
          { name: "sprint-plan", files: 3, source: "shared" },
          { name: "poc-deploy", files: 2, source: "local" },
        ],
        hooks: [
          { event: "PreToolUse", matcher: "Bash", type: "command", source: "local" },
        ],
        crons: [
          { name: "poc-health-check", schedule: "*/30 * * * *", status: "active", source: "local" },
        ],
      },
      jokebook: {
        name: "Joke-book",
        description: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium.",
        decider: "Darrell",
        lead: "Joke-book Project Lead",
        agents: [
          { name: "Joke-book Project Lead", role: "Team Lead", model: "claude-opus-4", status: "idle", source: "generated" },
        ],
        workgroups: [
          { name: "Editorial", lead: "Editor", agents: 3, source: "shared" },
          { name: "Writing", lead: "Writing Lead", agents: 2, source: "shared", overrides: ["norms"] },
        ],
        skills: [],
        hooks: [],
        crons: [],
      },
    },
  },

  // ── Status / operational ──────────────────────
  status: {
    escalations: [
      { id: "e1", project: "POC", jobId: "j1", jobName: "Lorem ipsum dolor sit", phase: "WORK_ASSERT", summary: "Consectetur adipiscing elit — sed do eiusmod tempor incididunt", time: "12m", taskId: null },
      { id: "e1b", project: "POC", jobId: "j1", jobName: "Lorem ipsum dolor sit", phase: "WORK", summary: "Ipsum decay — neque porro quisquam est qui dolorem", time: "5m", taskId: "t2", source: "task" },
      { id: "e2", project: "POC", jobId: "j2", jobName: "Ut enim ad minim veniam", phase: "WORK_ASSERT", summary: "Duis aute irure dolor in reprehenderit in voluptate", time: "3m", taskId: null },
      { id: "e3", project: "Joke-book", jobId: "j4", jobName: "Consectetur adipiscing elit", phase: "WORK", summary: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur", time: "8m", taskId: "t8" },
    ],
    projects: {
      poc: {
        name: "POC",
        activeJobs: 3,
        escalations: 3,
        status: "active",
        jobs: [
          { id: "j1", name: "Lorem ipsum dolor sit", workgroup: "Coding", status: "reviewing",
            phase: "WORK_ASSERT", phases: ["INTENT","INTENT_ASSERT","PLAN","PLAN_ASSERT","WORK","WORK_ASSERT","DONE"], phaseIdx: 5,
            escalations: [
              { id: "e1", phase: "WORK_ASSERT", summary: "Consectetur adipiscing elit — sed do eiusmod tempor", time: "12m", taskId: null },
              { id: "e1b", phase: "WORK", summary: "Ipsum decay — neque porro quisquam est qui dolorem", time: "5m", taskId: "t2", source: "task" },
            ],
            tasks: [
              { id: "t1", name: "Lorem base function", status: "done", assignee: "Developer", heartbeat: "dead" },
              { id: "t2", name: "Ipsum decay calculation", status: "active", assignee: "Developer", heartbeat: "alive" },
              { id: "t3", name: "Dolor sit tests", status: "pending", assignee: "Developer", heartbeat: "dead" },
              { id: "t4", name: "Amet consult integration", status: "pending", assignee: "Architect", heartbeat: "dead" },
            ],
            stats: { tasksCompleted: 1, tasksTotal: 4, backtracks: 0, escalations: 2, tokensUsed: "84K", elapsed: "47m" },
          },
          { id: "j2", name: "Ut enim ad minim veniam", workgroup: "Research", status: "reviewing",
            phase: "WORK_ASSERT", phases: ["INTENT","INTENT_ASSERT","PLAN","PLAN_ASSERT","WORK","WORK_ASSERT","DONE"], phaseIdx: 5,
            escalations: [
              { id: "e2", phase: "WORK_ASSERT", summary: "Duis aute irure dolor in reprehenderit", time: "3m", taskId: null },
            ],
            tasks: [
              { id: "t5", name: "Excepteur literature review", status: "done", assignee: "Researcher", heartbeat: "dead" },
              { id: "t6", name: "Cupidatat protocol spec", status: "active", assignee: "Researcher", heartbeat: "alive" },
            ],
            stats: { tasksCompleted: 1, tasksTotal: 2, backtracks: 1, escalations: 1, tokensUsed: "62K", elapsed: "1h 12m" },
          },
          { id: "j3", name: "Quis nostrud exercitation", workgroup: "Writing", status: "planning",
            phase: "PLAN", phases: ["INTENT","INTENT_ASSERT","PLAN","PLAN_ASSERT","WORK","WORK_ASSERT","DONE"], phaseIdx: 2,
            escalations: [],
            tasks: [
              { id: "t7", name: "Voluptate velit chapters", status: "active", assignee: "Writer", heartbeat: "stale" },
            ],
            stats: { tasksCompleted: 0, tasksTotal: 1, backtracks: 0, escalations: 0, tokensUsed: "18K", elapsed: "22m" },
          },
        ],
        humans: [
          { name: "Darrell", role: "decider" },
          { name: "Alice", role: "advisor" },
        ],
      },
      jokebook: {
        name: "Joke-book",
        activeJobs: 2,
        escalations: 1,
        status: "active",
        jobs: [
          { id: "j4", name: "Consectetur adipiscing elit", workgroup: "Editorial", status: "working",
            phase: "WORK", phases: ["INTENT","INTENT_ASSERT","PLAN","PLAN_ASSERT","WORK","WORK_ASSERT","DONE"], phaseIdx: 4,
            escalations: [
              { id: "e3", phase: "WORK", summary: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur", time: "8m", taskId: "t8" },
            ],
            tasks: [
              { id: "t8", name: "Tempor incididunt chapter", status: "active", assignee: "Editor", heartbeat: "alive" },
              { id: "t9", name: "Labore et dolore review", status: "pending", assignee: "Proofreader", heartbeat: "dead" },
            ],
            stats: { tasksCompleted: 0, tasksTotal: 2, backtracks: 0, escalations: 1, tokensUsed: "34K", elapsed: "29m" },
          },
          { id: "j5", name: "Magna aliqua veniam", workgroup: "Writing", status: "reviewing",
            phase: "WORK_ASSERT", phases: ["INTENT","INTENT_ASSERT","PLAN","PLAN_ASSERT","WORK","WORK_ASSERT","DONE"], phaseIdx: 5,
            escalations: [],
            tasks: [
              { id: "t10", name: "Nostrud exercitation draft", status: "done", assignee: "Writer", heartbeat: "dead" },
              { id: "t11", name: "Ullamco laboris polish", status: "done", assignee: "Writer", heartbeat: "dead" },
            ],
            stats: { tasksCompleted: 2, tasksTotal: 2, backtracks: 0, escalations: 0, tokensUsed: "51K", elapsed: "38m" },
          },
        ],
        humans: [
          { name: "Darrell", role: "decider" },
        ],
      },
    },
  },

  // ── Stats ─────────────────────────────────────
  stats: {
    management: {
      jobsCompleted: 47, tasksCompleted: 183, activeJobs: 6,
      oneShots: 31, backtracks: 12, withdrawals: 3,
      escalations: 18, interventions: 4, proxyAccuracy: 78,
      tokensUsed: "4.2M", skillsLearned: 23, uptime: "14d 6h",
    },
    poc: {
      jobsCompleted: 34, tasksCompleted: 127, activeJobs: 3,
      oneShots: 22, backtracks: 8, withdrawals: 2,
      escalations: 11, interventions: 2, proxyAccuracy: 81,
      tokensUsed: "2.8M", skillsLearned: 15,
    },
    // Time series for charts
    daily: [
      { date: "Mar 22", jobs: 2, tasks: 8, tokens: 320, escalations: 1, proxyAcc: 75 },
      { date: "Mar 23", jobs: 3, tasks: 11, tokens: 410, escalations: 2, proxyAcc: 72 },
      { date: "Mar 24", jobs: 1, tasks: 5, tokens: 180, escalations: 0, proxyAcc: 80 },
      { date: "Mar 25", jobs: 4, tasks: 14, tokens: 520, escalations: 3, proxyAcc: 76 },
      { date: "Mar 26", jobs: 3, tasks: 9, tokens: 380, escalations: 1, proxyAcc: 82 },
      { date: "Mar 27", jobs: 2, tasks: 12, tokens: 440, escalations: 2, proxyAcc: 79 },
      { date: "Mar 28", jobs: 3, tasks: 10, tokens: 360, escalations: 1, proxyAcc: 84 },
    ],
    phaseEscalations: [
      { phase: "INTENT", count: 3 },
      { phase: "PLAN", count: 5 },
      { phase: "WORK", count: 7 },
      { phase: "WORK_ASSERT", count: 3 },
    ],
  },

  // ── Project artifacts / docs ───────────────────
  artifacts: {
    org: {
      name: "Organization",
      entryFile: "organization.md",
      index: {
        title: "Organization",
        description: "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
        sections: [
          { heading: "Institutional Learnings", items: [
            { name: "Norms & Conventions", path: ".teaparty/learnings/institutional.md", summary: "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip" },
            { name: "Cross-Project Patterns", path: ".teaparty/learnings/cross-project.md", summary: "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore" },
          ]},
          { heading: "Procedural Skills", items: [
            { name: "Sprint Planning", path: ".claude/skills/sprint-plan/SKILL.md", summary: "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia" },
            { name: "Issue Resolution", path: ".claude/skills/fix-issue/SKILL.md", summary: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium" },
            { name: "Code Audit", path: ".claude/skills/audit/SKILL.md", summary: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit" },
            { name: "Milestone Close", path: ".claude/skills/close-milestone/SKILL.md", summary: "Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet consectetur" },
          ]},
          { heading: "Proxy Knowledge", items: [
            { name: "Preferential Model", path: ".teaparty/learnings/proxy.md", summary: "At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis" },
            { name: "Behavioral Patterns", path: ".teaparty/learnings/proxy-behavioral.md", summary: "Nam libero tempore, cum soluta nobis est eligendi optio cumque nihil impedit" },
            { name: "Ritual Observations", path: ".teaparty/learnings/proxy-rituals.md", summary: "Temporibus autem quibusdam et aut officiis debitis aut rerum necessitatibus" },
          ]},
          { heading: "Strategic Decisions", items: [
            { name: "Architecture Decisions", path: ".teaparty/decisions/architecture.md", summary: "Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis" },
            { name: "Tool & Library Choices", path: ".teaparty/decisions/tools.md", summary: "Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse" },
          ]},
        ],
      },
    },
    poc: {
      name: "POC",
      index: {
        title: "POC Project",
        description: "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt.",
        sections: [
          { heading: "Architecture", items: [
            { name: "Lorem Ipsum Overview", path: "docs/lorem-overview.md", summary: "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor" },
            { name: "Dolor Sit Machine", path: "docs/conceptual-design/dolor-sit.md", summary: "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris" },
            { name: "Amet Consectetur", path: "docs/conceptual-design/amet-consectetur.md", summary: "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum" },
          ]},
          { heading: "Design Docs", items: [
            { name: "Adipiscing System", path: "docs/conceptual-design/adipiscing.md", summary: "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia" },
            { name: "Tempor Incididunt", path: "docs/conceptual-design/tempor.md", summary: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium" },
            { name: "Magna Aliqua", path: "docs/conceptual-design/magna-aliqua.md", summary: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit" },
          ]},
          { heading: "Implementation", items: [
            { name: "Detailed Ipsum", path: "docs/detailed-design/index.md", summary: "Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet" },
            { name: "Engine Lorem", path: "projects/POC/orchestrator/engine.py", summary: "Consectetur adipisci velit, sed quia non numquam eius modi tempora" },
            { name: "Session Dolor", path: "projects/POC/orchestrator/session.py", summary: "Incidunt ut labore et dolore magnam aliquam quaerat voluptatem" },
            { name: "Actors Amet", path: "projects/POC/orchestrator/actors.py", summary: "Ut enim ad minima veniam, quis nostrum exercitationem ullam corporis" },
          ]},
          { heading: "Active Job Artifacts", items: [
            { name: "Job Alpha — INTENT", path: ".sessions/j1/INTENT.md", summary: "Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse", job: "j1" },
            { name: "Job Alpha — PLAN", path: ".sessions/j1/PLAN.md", summary: "At vero eos et accusamus et iusto odio dignissimos ducimus qui", job: "j1" },
            { name: "Job Alpha — WORK_ASSERT", path: ".sessions/j1/WORK_ASSERT.md", summary: "Work summary with diffs, changed files, and test results for review", job: "j1", gateReview: true },
            { name: "Job Beta — INTENT", path: ".sessions/j2/INTENT.md", summary: "Nam libero tempore, cum soluta nobis est eligendi optio cumque", job: "j2" },
            { name: "Job Beta — PLAN", path: ".sessions/j2/PLAN.md", summary: "Temporibus autem quibusdam et aut officiis debitis aut rerum", job: "j2" },
          ]},
          { heading: "Learnings", items: [
            { name: "Institutional", path: ".teaparty/learnings/institutional.md", summary: "Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis voluptatibus maiores" },
            { name: "Task: Ipsum Design", path: ".teaparty/learnings/tasks/ipsum-design.md", summary: "Nisi ut aliquid ex ea commodi consequatur, quis autem vel eum iure" },
            { name: "Task: Dolor Testing", path: ".teaparty/learnings/tasks/dolor-testing.md", summary: "Similique sunt in culpa qui officia deserunt mollitia animi, id est laborum" },
            { name: "Proxy Patterns", path: ".teaparty/learnings/proxy.md", summary: "Et harum quidem rerum facilis est et expedita distinctio, nam libero tempore" },
          ]},
        ],
      },
    },
    jokebook: {
      name: "Joke-book",
      index: {
        title: "Joke-book Project",
        description: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium.",
        sections: [
          { heading: "Design", items: [
            { name: "Lorem Strategy", path: "docs/lorem-strategy.md", summary: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem" },
            { name: "Ipsum Architecture", path: "docs/ipsum-pipeline.md", summary: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit" },
          ]},
          { heading: "Learnings", items: [
            { name: "Institutional", path: ".teaparty/learnings/institutional.md", summary: "Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse quam nihil molestiae" },
          ]},
        ],
      },
    },
  },

  // ── Chat conversations ────────────────────────
  // Two types:
  //   "job" type: navigator shows task sub-conversations within a job
  //   "participant" type: navigator shows all conversations with that participant across scopes
  conversations: {
    // ── Participant chats (navigator = conversation history) ──
    "office-manager": {
      type: "participant",
      participant: "Office Manager",
      sessions: [
        { id: "om-s1", label: "Lorem ipsum discussion", date: "Mar 25", messages: [
          { sender: "human", text: "Lorem ipsum dolor sit amet, consectetur adipiscing elit?" },
          { sender: "Office Manager", text: "Sed do eiusmod tempor:\n\n- **Project Alpha**: 3 jobs active, 2 escalations\n- **Project Beta**: idle\n\nSee [status dashboard](status.html) for details." },
          { sender: "human", text: "Duis aute irure dolor in reprehenderit?" },
          { sender: "Office Manager", text: "Here's the breakdown:\n\n| Workgroup | Status | Tasks |\n|-----------|--------|-------|\n| Coding | active | 4 |\n| Research | reviewing | 2 |\n| Writing | planning | 1 |\n\n> Note: excepteur sint occaecat cupidatat non proident\n\nRecommendation: `sed do eiusmod` before proceeding with **magna aliqua**." },
        ]},
        { id: "om-s2", label: "Adipiscing follow-up", date: "Mar 22", messages: [
          { sender: "human", text: "Ut enim ad minima veniam, quis nostrum exercitationem?" },
          { sender: "Office Manager", text: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur. Neque porro quisquam est qui dolorem." },
        ]},
        { id: "om-s3", label: "New tempor project", date: "Mar 18", messages: [
          { sender: "human", text: "Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse." },
          { sender: "Office Manager", text: "At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis praesentium." },
          { sender: "human", text: "Nam libero tempore, cum soluta nobis est eligendi optio." },
          { sender: "Office Manager", text: "Temporibus autem quibusdam et aut officiis debitis. Itaque earum rerum hic tenetur." },
        ]},
      ],
    },
    "poc-manager": {
      type: "participant",
      participant: "Manager",
      sessions: [
        { id: "mgr-s1", label: "Lorem refactor", date: "Mar 28", messages: [
          { sender: "human", text: "Sed ut perspiciatis unde omnis iste natus error sit voluptatem." },
          { sender: "Manager", text: "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit. Consectetur or adipiscing?" },
          { sender: "human", text: "Adipiscing first, then consectetur." },
          { sender: "Manager", text: "Itaque earum rerum hic tenetur a sapiente delectus. Ut aut reiciendis voluptatibus." },
        ]},
        { id: "mgr-s2", label: "Withdraw stale dolor", date: "Mar 24", messages: [
          { sender: "human", text: "Similique sunt in culpa qui officia deserunt. Withdraw it." },
          { sender: "Manager", text: "Et harum quidem rerum facilis est et expedita distinctio. Nam libero tempore?" },
          { sender: "human", text: "Non. Totam rem aperiam first." },
        ]},
      ],
    },
    "poc-proxy": {
      type: "participant",
      participant: "Proxy",
      sessions: [
        { id: "px-s1", label: "Lorem learning review", date: "Mar 28", messages: [
          { sender: "human", text: "Quis autem vel eum iure reprehenderit?" },
          { sender: "Proxy", text: "Lorem ipsum patterns:\n\n1. Consectetur adipiscing before approving\n2. Sed do eiusmod requires explicit tempor\n3. Ut enim ad minim on dolor, strict on amet\n4. Escalating early — duis aute irure" },
        ]},
        { id: "px-s2", label: "Job Alpha instructions", date: "Mar 26", messages: [
          { sender: "human", text: "Excepteur sint occaecat cupidatat non proident. Escalate everything related to ipsum parameters." },
          { sender: "Proxy", text: "Sunt in culpa qui officia deserunt mollitia. Force-escalate regardless of confidence." },
        ]},
        { id: "px-s3", label: "Job Beta concerns", date: "Mar 25", messages: [
          { sender: "human", text: "At vero eos et accusamus — be extra cautious." },
          { sender: "Proxy", text: "Iusto odio dignissimos ducimus. Flag any changes without explicit rollback. Blanditiis praesentium?" },
          { sender: "human", text: "Yes. Good instinct." },
        ]},
      ],
    },

    // ── Job chats (navigator = task sub-conversations) ──
    "j1": {
      type: "job",
      participant: "Project Lead",
      scope: "Lorem > Job Alpha",
      messages: [
        { sender: "Project Lead", text: "Lorem ipsum dolor sit amet. Broken into four tasks across the team." },
        { sender: "human", text: "Consectetur adipiscing elit — make sure the threshold is configurable." },
        { sender: "Project Lead", text: "Sed do eiusmod tempor incididunt. Architect will add to interface." },
        { sender: "Developer", text: "Ut enim ad minim veniam. Structural and semantic filters working. Tests passing." },
        { sender: "Project Lead", text: "Quis nostrud exercitation. Moving Developer onto next task." },
        { sender: "Proxy", text: "Duis aute irure dolor in reprehenderit:\n\nCurrent threshold (0.3) works for same-level. Cross-level might need higher.\n\nDesign doc says 'calibrate during Phase 1' — no starting point. Your instinct?", type: "escalation" },
      ],
      tasks: {
        t1: [
          { sender: "Developer", text: "Excepteur sint occaecat cupidatat. Reading the design doc." },
          { sender: "Developer", text: "Sunt in culpa qui officia. All 6 tests passing." },
        ],
        t2: [
          { sender: "Developer", text: "Sed ut perspiciatis unde omnis. Reading the spec." },
          { sender: "Developer", text: "Nemo enim ipsam voluptatem. Now working on time-based decay." },
          { sender: "Developer", text: "Neque porro quisquam est, qui dolorem ipsum. Literature suggests d=0.5. Does that align?", type: "escalation" },
        ],
        t3: [],
        t4: [],
      },
    },
    "j4": {
      type: "job",
      participant: "Project Lead",
      scope: "Joke-book > Consectetur",
      messages: [
        { sender: "Project Lead", text: "At vero eos et accusamus et iusto odio dignissimos ducimus. Two tasks assigned." },
        { sender: "human", text: "Nam libero tempore, cum soluta nobis est eligendi optio." },
        { sender: "Editor", text: "Temporibus autem quibusdam et aut officiis debitis. Working on chapter." },
        { sender: "Proxy", text: "Itaque earum rerum hic tenetur a sapiente delectus:\n\nNemo enim ipsam voluptatem quia voluptas. Sed quia non numquam eius modi tempora.\n\nQuis autem vel eum iure?", type: "escalation" },
      ],
      tasks: {
        t8: [
          { sender: "Editor", text: "Similique sunt in culpa qui officia deserunt. Reading source material." },
          { sender: "Editor", text: "Et harum quidem rerum facilis est et expedita distinctio. Need guidance on tone.", type: "escalation" },
        ],
        t9: [],
      },
    },
    "j5": {
      type: "job",
      participant: "Project Lead",
      scope: "Joke-book > Magna aliqua",
      messages: [
        { sender: "Project Lead", text: "Quis autem vel eum iure reprehenderit. Both tasks completed." },
        { sender: "Writer", text: "Voluptatem sequi nesciunt. Draft complete and polished." },
        { sender: "Project Lead", text: "Neque porro quisquam est. Moving to review." },
      ],
      tasks: {
        t10: [
          { sender: "Writer", text: "Nisi ut aliquid ex ea commodi consequatur. First draft done." },
        ],
        t11: [
          { sender: "Writer", text: "Accusantium doloremque laudantium, totam rem aperiam. Polish pass complete." },
        ],
      },
    },
  },
};
