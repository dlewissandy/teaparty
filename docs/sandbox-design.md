# Repositories, Sandboxes, and Code Execution

> **Future Phase (Phases 4–5):** This document describes planned sandbox infrastructure. The sandbox/Docker system is not currently implemented. The workspace system (git repos + worktrees) is partially implemented in the POC; Docker containers and Claude Code CLI delegation are future work.

How TeaParty workgroups get real filesystems, git version control, containerized execution, and Claude Code CLI -- without duplicating what Claude Code already does well.

## Problem

TeaParty stores workgroup files as JSON blobs in a SQLite column (`Workgroup.files`). This works for collaborative documents, workflows, and configuration, but it cannot support real software engineering:

- No git history, no branches, no merges, no diffs
- No filesystem, so no `npm install`, no test runners, no build tools
- The existing `claude_code` tool is a homegrown multi-turn LLM loop that reimplements file CRUD against virtual files — it cannot run commands, install dependencies, or use any of the real Claude Code CLI's capabilities
- No process isolation — a misbehaving tool call runs in the same Python process as the server
- No way to work on multiple jobs concurrently in the same codebase (no worktrees or branches)

## Design Principles

1. **Don't reimplement Claude Code.** Claude Code is a battle-tested coding agent with Bash execution, git operations, file editing, test running, and planning. TeaParty should orchestrate it, not duplicate it.
2. **Git is the source of truth for code.** Workgroup files (JSON blobs) remain for documents, workflows, and config (see [file-layout.md](file-layout.md)). Code lives in git repos on disk.
3. **Jobs map to branches.** Each job works on an isolated branch via git worktrees, enabling concurrent tasks without interference.
4. **Containers are the sandbox boundary.** Claude Code runs inside containers with the job's files mounted. The container enforces resource limits and isolation. The host never executes untrusted commands.
5. **TeaParty is the collaboration layer.** It manages who can access what, coordinates multi-agent workflows, tracks history and decisions, and presents a unified UI. The actual coding happens inside the sandbox.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   TeaParty Server                    │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ Agent Runtime│  │ Repo Manager │  │ Sandbox   │  │
│  │ (orchestrate)│──│ (git, sync)  │──│ Pool      │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                │                 │        │
│  ┌──────┴──────┐  ┌──────┴───────┐  ┌─────┴─────┐  │
│  │ Existing    │  │ Bare Repo +  │  │ Container │  │
│  │ Virtual     │  │ Worktrees    │  │ Lifecycle │  │
│  │ Files (JSON)│  │ (on disk)    │  │ (Docker)  │  │
│  └─────────────┘  └──────────────┘  └───────────┘  │
│                                                     │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
   ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐
   │ Sandbox  │  │ Sandbox  │  │ Sandbox  │
   │ (job-1)  │  │ (job-2)  │  │ (idle)   │
   │          │  │          │  │          │
   │ worktree │  │ worktree │  │          │
   │ mounted  │  │ mounted  │  │          │
   │          │  │          │  │          │
   │ claude   │  │ claude   │  │          │
   │ code CLI │  │ code CLI │  │          │
   └──────────┘  └──────────┘  └──────────┘
```

## Key Concepts

### Workgroup Repository

Every workgroup has a **git repository** on the host filesystem. The repo is the workgroup's codebase — it holds source code, configuration, and any artifacts that benefit from version history. The repo is created automatically when the workgroup is created with workspace enabled.

```
Workgroup (DB)          Repository (disk)
├── files (JSON)        ├── bare repo:  /data/repos/<workgroup-id>/repo.git
├── agents              ├── main worktree: /data/repos/<workgroup-id>/main
├── jobs ───────────────├── job worktrees:
│   ├── job-1  ──────── │   ├── /data/repos/<workgroup-id>/jobs/job-1  (branch: job/job-1)
│   └── job-2  ──────── │   └── /data/repos/<workgroup-id>/jobs/job-2  (branch: job/job-2)
└── conversations       └── .teaparty/  (metadata, ignored by git)
```

The JSON file store (`Workgroup.files`) and the git repo coexist. The JSON store holds documents, workflows, and config — things that agents read as prompt context. The git repo holds code — things that get built, tested, and executed. The main branch is synced to `Workgroup.files` so the file browser shows the current codebase state.

### Branch-per-Job

Each job gets its own git worktree branching from `main`. This is the natural mapping:

| TeaParty concept | Git concept | Why |
|---|---|---|
| Workgroup | Repository | One codebase per workgroup |
| Job | Branch + Worktree | Parallel tasks without interference |
| Message history | Commit log | "Save progress" creates commits |
| Job merge | PR / merge to main | Completed work flows back |
| Direct message | (no mapping) | DMs don't touch code |

Worktree lifecycle:
1. **Job created** → `git worktree add` with new branch `job/<job-id>` from `main`
2. **Work happens** → Claude Code operates inside the job's sandbox container
3. **Agent commits** → Commits accumulate on the job branch
4. **Job resolved** → User (or agent with permission) merges branch to `main`, worktree removed
5. **Job abandoned** → Worktree and branch cleaned up

### Sandbox

Each active job gets a **sandbox** — a Docker container that provides an isolated execution environment. The sandbox:
- Has the job's worktree bind-mounted at `/workspace`
- Has Claude Code CLI pre-installed
- Has language runtimes and common tools (configurable per workgroup via a `Dockerfile` or image reference in workgroup config)
- Runs with resource limits (CPU, memory, disk, network)
- Has no access to the host network or other jobs (network-isolated by default)
- Exposes a gRPC or HTTP sidecar for TeaParty to send commands and receive results

Sandboxes are **not** long-lived VMs. They are pooled and recycled:
- **Warm pool**: A small number of pre-built containers sit idle, ready to accept a worktree mount
- **On-demand**: If the pool is empty, a container is created (slower, ~2-5 seconds)
- **Idle timeout**: Containers with no activity for N minutes are stopped (worktree persists on disk)
- **Resume**: Re-entering a job re-mounts the worktree into a fresh or existing container

## Data Model Changes

### New fields on `Workgroup`

```python
class Workgroup(SQLModel, table=True):
    # ... existing fields ...

    # Repository (host-side paths)
    repo_path: str = ""              # /data/repos/<workgroup-id>/repo.git (bare)
    repo_main_path: str = ""         # /data/repos/<workgroup-id>/main (worktree)

    # Sandbox configuration
    sandbox_image: str = "teaparty/sandbox:default"  # Docker image for job containers
    sandbox_preset: str = "standard"                  # standard | large | gpu | connected

    # State
    repo_status: str = "none"        # none | active | error
    repo_last_sync_at: str = ""      # ISO timestamp of last file sync
```

### New: `JobSandbox` table

```python
class JobSandbox(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    workgroup_id: str = Field(foreign_key="workgroups.id", index=True)
    conversation_id: str = Field(foreign_key="conversations.id", unique=True, index=True)

    # Git state
    branch_name: str             # job/<conversation-id>
    worktree_path: str           # /data/repos/<workgroup-id>/jobs/<conversation-id>
    base_commit: str = ""        # SHA of the commit this branch started from
    head_commit: str = ""        # current HEAD SHA

    # Container state
    container_id: str = ""       # Docker container ID (empty if no container running)
    container_status: str = "none"  # none | starting | running | stopping | stopped

    # Lifecycle
    status: str = "active"       # active | merged | abandoned | error
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    merged_at: str = ""
```

### Modified: `Agent` table

No model changes. Agents gain access to sandbox tools through their existing `tool_names` list. New tool names: `sandbox_exec`, `sandbox_shell`, `git_status`, `git_commit`, `git_diff`, `git_log`, `merge_to_main`, `list_repo_files`.

## New Services

### 1. `teaparty_app/services/repo_manager.py`

Manages the lifecycle of workgroup repositories and job worktrees on the host filesystem. This service never touches containers — it only manages git repos and worktrees.

**Key functions:**

```python
async def init_repo(session: Session, workgroup: Workgroup) -> None:
    """Initialize a bare repo + main worktree for a workgroup.

    Steps:
    1. Create directory structure: /data/repos/<workgroup-id>/
    2. git init --bare repo.git
    3. Create initial commit on main (with any existing workgroup files synced to disk)
    4. git worktree add main (checked out to main branch)
    5. Update workgroup.repo_path, workgroup.repo_main_path, workgroup.repo_status
    """

async def create_job_worktree(
    session: Session, workgroup: Workgroup, conversation: Conversation,
) -> JobSandbox:
    """Create a git worktree for a job.

    Steps:
    1. git worktree add jobs/<conversation-id> -b job/<conversation-id>
    2. Create and persist JobSandbox record
    """

async def remove_job_worktree(session: Session, job_sandbox: JobSandbox) -> None:
    """Remove a worktree and optionally its branch.

    Steps:
    1. Stop any running container (via sandbox_pool)
    2. git worktree remove jobs/<conversation-id>
    3. git branch -d job/<conversation-id> (if merged) or -D (if abandoned)
    4. Update JobSandbox status
    """

async def merge_job(
    session: Session, job_sandbox: JobSandbox, workgroup: Workgroup, user_id: str,
) -> MergeResult:
    """Merge a job branch into main.

    Steps:
    1. Validate user has editor+ role
    2. git checkout main (in main worktree)
    3. git merge job/<conversation-id> --no-ff
    4. Handle conflicts (return conflict info if any — user resolves via UI or agent)
    5. Update job_sandbox status to 'merged'
    6. Sync main worktree back to workgroup.files (for the file browser UI)
    """

async def sync_main_to_files(session: Session, workgroup: Workgroup) -> None:
    """Sync the main worktree's tracked files into workgroup.files JSON.

    This keeps the TeaParty file browser working for coding workgroups.
    Only syncs text files under a size threshold. Binary files get
    a placeholder entry with path and size metadata.
    """

async def sync_files_to_main(session: Session, workgroup: Workgroup) -> None:
    """Sync workgroup.files JSON changes back to the main worktree.

    Used when files are edited via the TeaParty UI file browser.
    Creates a commit: 'sync: updated via TeaParty UI'
    """

async def destroy_repo(session: Session, workgroup: Workgroup) -> None:
    """Remove all worktrees, the bare repo, and reset the workgroup's repo fields.

    Requires owner role. This is destructive and irreversible.
    """
```

**Git operations** are executed via `asyncio.create_subprocess_exec` calling the `git` binary directly. No Python git library — the git CLI is the most reliable and well-tested interface. All git commands run with `GIT_DIR` and `GIT_WORK_TREE` environment variables set explicitly to prevent any confusion about which repo is being operated on.

**File sync strategy:**
- **Main → JSON**: After each merge to main, scan tracked files and update `workgroup.files`. Skip binary files (detected by `git diff --numstat` null markers or file extension heuristics). Cap synced file content at the existing 200KB limit. Store a summary entry for files that exceed the limit: `{"path": "large-file.bin", "content": "(binary, 4.2 MB)", "meta": {"binary": true, "size": 4404019}}`.
- **JSON → Main**: When a user edits a file via the TeaParty file browser, write the change to the main worktree and auto-commit. This path is intentionally simple — the UI is a convenience, not the primary editing interface.
- **Job worktree files are NOT synced to JSON during active work.** The job's worktree is the source of truth while the job is active. The TeaParty UI shows job files by reading the filesystem directly (via the sandbox or a read-only mount), not through the JSON column.

### 2. `teaparty_app/services/sandbox_pool.py`

Manages Docker containers for sandboxed code execution.

**Key functions:**

```python
async def ensure_sandbox(
    session: Session, job_sandbox: JobSandbox, workgroup: Workgroup,
) -> ContainerInfo:
    """Ensure a running container exists for this job.

    1. If job_sandbox.container_id is set and container is running, return it
    2. If a warm pool container is available, assign it
    3. Otherwise, create a new container
    4. Bind-mount the worktree path at /workspace
    5. Start the container
    6. Update job_sandbox.container_id and container_status

    Returns ContainerInfo with container_id, exec endpoint, and status.
    """

async def exec_in_sandbox(
    container_id: str, command: list[str],
    timeout: int = 120, workdir: str = "/workspace",
) -> ExecResult:
    """Execute a command inside a sandbox container.

    Returns ExecResult with stdout, stderr, exit_code, timed_out.
    Uses Docker exec API. Streams output for long-running commands.
    """

async def invoke_claude_code(
    container_id: str, prompt: str,
    allowed_tools: list[str] | None = None,
    max_turns: int = 25,
) -> ClaudeCodeResult:
    """Run Claude Code CLI inside a sandbox.

    Invokes: claude --print --output-format json \
             --max-turns <max_turns> \
             --allowedTools <tools> \
             "<prompt>"

    The container has ANTHROPIC_API_KEY set as an env var.
    Claude Code runs with full filesystem access inside /workspace
    (which is the job's worktree). It can read, write, execute, use git,
    run tests — everything it normally does.

    Returns structured output: response text, files changed,
    tool calls made, tokens used.
    """

async def stop_sandbox(job_sandbox: JobSandbox) -> None:
    """Stop and remove a container. Worktree persists on disk."""

async def cleanup_idle_sandboxes(max_idle_minutes: int = 30) -> int:
    """Stop containers that have been idle beyond the threshold.
    Called periodically by a background task.
    Returns count of containers stopped.
    """
```

**Container specification:**

```dockerfile
# teaparty/sandbox:default
FROM ubuntu:24.04

# Core tools
RUN apt-get update && apt-get install -y \
    git curl wget jq tree \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Node.js (LTS)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs

# Python
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Working directory
WORKDIR /workspace

# Non-root user for execution
RUN useradd -m -s /bin/bash sandbox
USER sandbox
```

Workgroup owners can specify a custom `sandbox_image` in workgroup config to get different language stacks (Rust, Go, Java, etc.) or pre-installed project dependencies.

**Resource limits** (applied via Docker container create):

| Preset | CPU | Memory | Disk | Network |
|---|---|---|---|---|
| `standard` | 2 cores | 2 GB | 10 GB | isolated (no external) |
| `large` | 4 cores | 8 GB | 20 GB | isolated |
| `gpu` | 4 cores + GPU | 16 GB | 40 GB | isolated |
| `connected` | 2 cores | 2 GB | 10 GB | host network (for API calls, package installs) |

The `connected` preset allows outbound network access for `npm install`, `pip install`, etc. This is required for most real projects but trades isolation for utility. The default during active development should be `connected`; switch to `standard` for untrusted or automated execution.

### 3. `teaparty_app/services/sandbox_tools.py`

Agent tools for interacting with the workgroup's repository and job sandboxes. These replace the homegrown `claude_code` tool.

```python
SANDBOX_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "sandbox_exec",
        "description": (
            "Execute a task in the job's sandbox using Claude Code. "
            "Describe what you want done — Claude Code will plan and execute it "
            "with full access to the codebase, terminal, and git. "
            "Use this for: writing code, running tests, installing dependencies, "
            "debugging, refactoring, and any task that requires filesystem or shell access."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What to accomplish. Be specific about files, behavior, and acceptance criteria.",
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Max agentic turns for Claude Code (default 25).",
                    "default": 25,
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "sandbox_shell",
        "description": (
            "Run a single shell command in the job's sandbox container. "
            "Use for quick checks: test output, file listings, build status, git log. "
            "For multi-step tasks, prefer sandbox_exec."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60, max 300).",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "git_status",
        "description": "Show the current git status of the job: branch, changed files, ahead/behind main.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": "Show the diff of uncommitted changes, or between the job branch and main.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What to diff against: 'staged', 'unstaged' (default), or 'main'.",
                    "default": "unstaged",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage all changes and create a commit on the job branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The commit message.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_log",
        "description": "Show recent commit history for the job branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of commits to show (default 10).",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
    {
        "name": "merge_to_main",
        "description": (
            "Merge the job branch into main. "
            "This completes the code work for this job. "
            "Requires editor or owner role."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "'merge' (default) or 'squash'.",
                    "default": "merge",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_repo_files",
        "description": (
            "List files in the job's worktree, optionally filtered by glob pattern. "
            "Shows the actual filesystem state, including untracked and gitignored files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter (e.g. 'src/**/*.py'). Default: all tracked files.",
                },
                "include_untracked": {
                    "type": "boolean",
                    "description": "Include untracked files (default false).",
                    "default": False,
                },
            },
            "required": [],
        },
    },
]
```

**Tool dispatch** works the same as existing tools — `dispatch_agent_tool()` in `agent_tools.py` gets extended to handle these new names. Each tool call:
1. Looks up the `JobSandbox` for the current conversation
2. Calls `sandbox_pool.ensure_sandbox()` to get or create a container
3. Executes the operation
4. Returns the result text

The key tool is `sandbox_exec`. Its implementation:

```python
async def _tool_sandbox_exec(
    session: Session,
    job_sandbox: JobSandbox,
    workgroup: Workgroup,
    agent: Agent,
    task: str,
    max_turns: int = 25,
) -> str:
    """Delegate a coding task to Claude Code CLI running in the sandbox."""
    container = await sandbox_pool.ensure_sandbox(session, job_sandbox, workgroup)

    result = await sandbox_pool.invoke_claude_code(
        container_id=container.container_id,
        prompt=task,
        max_turns=min(max_turns, 50),  # hard cap
    )

    # Update head commit after Claude Code may have committed
    new_head = await _get_head_sha(job_sandbox.worktree_path)
    if new_head != job_sandbox.head_commit:
        job_sandbox.head_commit = new_head
        session.add(job_sandbox)

    return result.response_text
```

This is the critical design decision: **TeaParty agents don't write code. They delegate to Claude Code.** A TeaParty agent decides *what* needs to be done (using conversation context, workflow state, workgroup discussion), then hands the task to Claude Code which decides *how* to do it. This avoids duplicating Claude Code's planning, file editing, test running, and error recovery capabilities.

### 4. `teaparty_app/services/repo_sync.py`

Bidirectional sync between the filesystem and the virtual file view.

```python
async def worktree_to_file_view(
    job_sandbox: JobSandbox,
) -> list[FileViewEntry]:
    """Read the job's worktree files and return a virtual file list.

    Used by the UI to display job files without going through
    the workgroup.files JSON column. This reads the filesystem directly.

    Filters:
    - Only git-tracked files (not in .gitignore)
    - Text files only (skip binaries based on git attributes / null bytes)
    - Content capped at 200KB per file (truncated with marker)
    - Total cap: 500 files (sorted by path, excess files listed without content)
    """

async def export_main_to_files(
    session: Session, workgroup: Workgroup,
) -> None:
    """Snapshot the main branch into workgroup.files for the file browser.

    Called after:
    - merge_to_main completes
    - Manual sync triggered by owner
    - Repo creation (initial import)

    This is a one-way export. The JSON column becomes a read cache of main.
    """
```

## How It All Fits Together

### Scenario: "Build me a login page"

1. **User** posts "Build a login page with email/password authentication" in job `login-feature`
2. **Agent Runtime** selects the `Implementer` agent to respond
3. **Implementer** reads the job's [workflow](workflows.md) state, sees it's on "Step 1: Clarify Requirements"
4. **Implementer** posts a message asking clarifying questions and outlining the plan
5. **User** confirms the approach
6. **Implementer** calls `sandbox_exec` with task: "Create a login page component at src/pages/Login.tsx with email and password fields, form validation, and a submit handler that calls POST /api/auth/login. Use the existing Button and Input components from src/components/. Add a test file."
7. **TeaParty** ensures a sandbox container is running for this job
8. **Claude Code CLI** (inside the sandbox) plans the implementation, reads existing files to understand patterns, writes the component, writes tests, runs the tests, fixes any failures
9. **Claude Code** returns: "Created src/pages/Login.tsx with email/password form, validation, and API integration. Added src/pages/Login.test.tsx with 6 passing tests."
10. **Implementer** calls `git_commit` with message: "feat: add login page with form validation"
11. **Implementer** advances the workflow to the next step and posts a summary to the conversation
12. **Reviewer** agent is selected to respond, calls `git_diff` with target `main` to see all changes
13. **Reviewer** calls `sandbox_exec` with task: "Review the login page implementation. Check for XSS vulnerabilities in form handling, verify the test coverage, and check that error states are handled."
14. **Reviewer** posts review feedback
15. After iteration, **User** says "Looks good, merge it"
16. **Implementer** calls `merge_to_main`
17. **TeaParty** merges the branch, syncs main to `workgroup.files`, cleans up the worktree

### Scenario: Importing an existing repository

1. Owner creates a coding workgroup
2. In workgroup config, sets `git_remote: "https://github.com/org/repo.git"`
3. `repo_manager.init_repo()`:
   - `git clone --bare <remote> repo.git`
   - `git worktree add main` (checks out default branch)
   - Syncs main to `workgroup.files` for the file browser
4. Jobs now branch from the imported codebase

## Configuration

### Workgroup Config (`workgroup.json`)

Sandbox-related fields in workgroup configuration:

```json
{
  "name": "My Project",
  "service_description": "Backend API development",
  "sandbox": {
    "image": "teaparty/sandbox:default",
    "preset": "connected",
    "git_remote": "",
    "auto_commit": true,
    "auto_merge": false,
    "idle_timeout_minutes": 30,
    "max_file_sync_size_kb": 200,
    "env_vars": {
      "NODE_ENV": "development"
    }
  }
}
```

### Server Config (`config.py`)

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Repository and sandbox settings
    repo_root: str = "/data/repos"                     # Base directory for all workgroup repos
    sandbox_docker_socket: str = "/var/run/docker.sock"
    sandbox_default_image: str = "teaparty/sandbox:default"
    sandbox_warm_pool_size: int = 2                    # Pre-warmed containers
    sandbox_max_containers: int = 10                   # Hard limit on concurrent containers
    sandbox_idle_timeout_minutes: int = 30             # Auto-stop idle containers
    sandbox_max_jobs_per_workgroup: int = 20            # Limit concurrent job branches
```

## API Endpoints

### Repository management

```
POST   /api/workgroups/{workgroup_id}/repo              Initialize repo for workgroup
GET    /api/workgroups/{workgroup_id}/repo              Get repo status and info
DELETE /api/workgroups/{workgroup_id}/repo              Destroy repo (owner only)
POST   /api/workgroups/{workgroup_id}/repo/sync         Trigger manual file sync
```

### Job branch management

```
GET    /api/workgroups/{workgroup_id}/repo/jobs                   List all job branches
GET    /api/workgroups/{workgroup_id}/repo/jobs/{conv_id}         Get job branch status
POST   /api/workgroups/{workgroup_id}/repo/jobs/{conv_id}/merge   Merge job to main
DELETE /api/workgroups/{workgroup_id}/repo/jobs/{conv_id}         Remove job branch
```

### File access (repo-backed)

```
GET    /api/workgroups/{workgroup_id}/repo/files?ref={branch|commit}     List files
GET    /api/workgroups/{workgroup_id}/repo/files/{path}?ref={branch}     Read file
GET    /api/workgroups/{workgroup_id}/repo/diff?base=main&head={branch}  Get diff
```

These endpoints serve the UI's file browser when the workgroup has a repo. The frontend detects `repo_status == "active"` and switches from the JSON-based file browser to the repo-backed one.

### Sandbox status (for UI activity indicators)

```
GET    /api/workgroups/{workgroup_id}/sandboxes    List running sandbox containers with status
```

## Security Model

### Isolation boundaries

1. **Container isolation**: Each job's sandbox is isolated from others. No shared filesystem beyond the specific worktree mount. No access to the TeaParty database or other workgroups' repos.

2. **Git branch isolation**: Worktrees are git branches. One job cannot modify another job's files without going through a merge. `main` is only modified via merge operations.

3. **Permission model**: Existing TeaParty roles govern access:
   - **Owner**: Full control. Can init/destroy repo, configure sandbox images, merge to main, manage job branches.
   - **Editor**: Can use sandbox tools, commit to job branches, request merges.
   - **Member**: Read-only. Can view files and diffs but not execute commands or modify code.

4. **API key isolation**: The `ANTHROPIC_API_KEY` is injected into sandbox containers as an environment variable. Each container gets the key associated with the organization owner. Token usage is tracked and attributed to the requesting agent/user.

5. **Network isolation**: Sandboxes default to no external network access. The `connected` preset enables outbound access for package managers. Inbound access is never allowed.

### What sandboxes CAN do
- Read and write files within `/workspace` (the job's worktree)
- Execute arbitrary commands (builds, tests, scripts)
- Use git within the worktree
- Make outbound HTTP requests (if `connected` preset)
- Use Claude Code CLI with the provided API key

### What sandboxes CANNOT do
- Access the host filesystem outside their mount
- Access other sandboxes or worktrees
- Access the TeaParty database
- Modify the bare repo directly (only via worktree git operations)
- Listen on network ports accessible from outside the container
- Exceed their resource limits

## Migration Path

### Phase 1: Repository Manager (no containers)

- Add `repo_*` fields to Workgroup and `JobSandbox` model
- Implement `repo_manager.py` with git operations
- Add repo API endpoints
- Hook into job creation/deletion lifecycle
- File sync between main worktree and `workgroup.files`
- **Agents operate via direct git/file commands on the host** (no container isolation yet)
- This phase is useful even without containers — it adds git history and branching

### Phase 2: Sandbox Containers

- Build the default sandbox Docker image
- Implement `sandbox_pool.py` with container lifecycle management
- Wire `sandbox_exec` to invoke Claude Code CLI inside containers
- Add sandbox status to the API and UI
- Move all code execution from host to containers

### Phase 3: Claude Code Integration

- Replace the homegrown `claude_code.py` tool with `sandbox_exec`
- Update the `coding` workgroup template to use sandbox tools
- Add `sandbox_exec`, `git_status`, `git_commit`, `git_diff` to agent tool sets
- Update agent system prompts to explain the repo + sandbox model

### Phase 4: UI Integration

- Repo-aware file browser (shows git status, branch indicator, diff view)
- Sandbox status indicators (running, idle, stopped) per job
- Merge UI (diff view, conflict resolution, merge button)
- Branch comparison view (job vs main)
- Commit history view per job

### Phase 5: Advanced Features

- Remote git push/pull (sync with GitHub, GitLab)
- Custom Dockerfiles per workgroup
- Persistent container volumes for `node_modules`, `.venv`, etc. (cache mounts)
- Container snapshots for reproducible environments
- Multi-file diff review workflow
- PR-style merge request workflow between jobs

## Open Questions

Open research questions for this area are collected in [Research Directions](research-directions.md).

## Dependencies

New Python packages:
- `docker` (Docker SDK for Python) — container management
- No git library needed — use `git` CLI via `asyncio.create_subprocess_exec`

Infrastructure requirements:
- Docker daemon running on the host (or accessible via socket)
- `git` CLI installed on the host
- Sufficient disk space for repos (`repo_root` directory)
- Claude Code CLI (`@anthropic-ai/claude-code`) installed in the sandbox Docker image

## Source File Layout

```
teaparty_app/
├── services/
│   ├── repo_manager.py        # Git repo + worktree lifecycle
│   ├── sandbox_pool.py        # Docker container pool management
│   ├── sandbox_tools.py       # Agent tool schemas + dispatch for sandbox ops
│   └── repo_sync.py           # Bidirectional file sync (filesystem ↔ JSON)
├── routers/
│   └── repo.py                # REST API endpoints for repo + sandbox management
├── models.py                  # + JobSandbox model, Workgroup repo fields
└── config.py                  # + repo_*, sandbox_* settings

docker/
├── Dockerfile.sandbox         # Default sandbox image
├── Dockerfile.sandbox-node    # Node.js-focused variant
└── Dockerfile.sandbox-python  # Python-focused variant

tests/
├── test_repo_manager.py
├── test_sandbox_pool.py
├── test_sandbox_tools.py
└── test_repo_sync.py
```
