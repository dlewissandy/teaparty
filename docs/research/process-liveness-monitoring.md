# Process Liveness Monitoring — Python Libraries and Patterns

This file catalogs Python libraries and patterns for process heartbeat, liveness detection, and process registries, with emphasis on approaches that work without a central server, survive crashes, and handle concurrent access safely.

**Research context:** TeaParty's hierarchical team architecture runs each level as an independent OS process. Parent teams need to know when child teams are alive, stuck, or dead without requiring a broker, without false positives from clean shutdowns, and without leaving zombie state if the parent itself dies. This motivates investigating the available primitive landscape before building anything bespoke.

---

## Summary Verdict

No single PyPI library cleanly covers all five constraints (liveness, crash-resilience, concurrent safety, no central server, hierarchical). The space splits into three tiers:

1. **Usable as-is:** `psutil` for PID-based liveness queries; `filelock` (tox-dev) for safe concurrent state writes; `python-prctl` for parent-death signal propagation on Linux.
2. **Usable as primitives:** `pid` library for PID file management; `watchdog` for reactive file-system observation; Celery's file-touch pattern (extractable as a standalone idiom).
3. **Wrong fit:** `pyheartbeat`, `health-ping`, `openmetrics-liveness-probe` — all require an HTTP server or external monitoring endpoint. `circus`, `supervisor` — full process supervisors, not extractable primitives. `single-beat` requires Redis. `multiprocessing.managers` requires the manager process to stay alive (defeats crash-resilience for the monitor itself).

The practical answer for TeaParty is a composed primitive: **mtime-stamp files + `filelock` for safe writes + `psutil.pid_exists()` for cross-validation + `python-prctl` (Linux) or polling for cross-process death signaling.**

---

## Library Catalog

### psutil (giampaolo, v6.x)
- **URL:** https://pypi.org/project/psutil/ / https://github.com/giampaolo/psutil
- **Maturity:** Production-grade. Cross-platform (Linux, macOS, Windows). 10M+ weekly downloads.
- **Key findings:**
  - `psutil.pid_exists(pid)` checks OS-level process existence without attaching to the process.
  - `Process.is_running()` additionally validates that the PID has not been recycled (compares `create_time`).
  - `Process.status()` returns detailed status: `running`, `sleeping`, `zombie`, `stopped` — useful for detecting hangs.
  - `psutil.wait_procs(procs_list, timeout=N, callback=on_terminate)` blocks until a list of processes terminate, with per-process callbacks. Returns `(gone, alive)`.
  - `NoSuchProcess` exception is the canonical signal that a process died between your check and your operation — must be caught in any polling loop.
  - No built-in heartbeat, no file-based state, no crash-resilient registry. It is a query library, not a monitoring framework.
- **Implications for TeaParty:** `psutil.pid_exists()` + `Process.is_running()` is the correct liveness cross-check after reading a PID from a file. `wait_procs()` is the right primitive for a parent that wants to block-until-all-children-done with a timeout. The `create_time` check in `is_running()` guards against PID recycling — important in long-running sessions.

---

### filelock / tox-dev (v3.x)
- **URL:** https://pypi.org/project/filelock/ / https://github.com/tox-dev/filelock
- **Maturity:** Production-grade. Used by pip, tox, huggingface/datasets, and many others.
- **Key findings:**
  - Platform-independent: uses `fcntl.flock` on POSIX, `msvcrt` on Windows.
  - Provides `FileLock` (blocking) and `SoftFileLock` (works on network filesystems where `fcntl` is unreliable).
  - Lock is released automatically if the process holding it dies — `fcntl` locks are process-scoped at the OS level.
  - Supports timeout; raises `Timeout` on contention.
  - Does NOT provide heartbeat semantics. It serializes writes but does not track liveness.
- **Implications for TeaParty:** The right tool for safe concurrent writes to a shared process registry file (e.g., a JSON file that multiple workers write their heartbeat timestamps into). The combination of filelock + mtime-stamp-file gives crash-resilient, concurrent-safe liveness without a broker.

---

### pid (v3.0.4)
- **URL:** https://pypi.org/project/pid/
- **Maturity:** Stable. Python 2.7 / 3.4+ compatible. Minimal maintenance activity.
- **Key findings:**
  - Provides `PidFile` context manager and `@pidfile()` decorator for creating and cleaning up PID files.
  - Detects stale PID files (checks if the PID is still alive via OS).
  - Uses `fcntl` locking to prevent concurrent acquisition.
  - Supports `chmod` and `chown` on the PID file.
  - Does NOT support heartbeat intervals, liveness timestamps, or registry patterns.
- **Implications for TeaParty:** Useful for ensuring only one instance of a worker process runs (mutual exclusion). Not sufficient alone for liveness monitoring — it only records that a process started, not that it is still functioning. Combine with mtime-stamp polling for the heartbeat layer.

---

### watchdog (gorakhargosh, v6.0.0)
- **URL:** https://pypi.org/project/watchdog/ / https://github.com/gorakhargosh/watchdog
- **Maturity:** Production-grade. Python 3.9+. Cross-platform (inotify / FSEvents / kqueue / ReadDirectoryChangesW / polling fallback).
- **Key findings:**
  - Monitors filesystem events: `FileCreatedEvent`, `FileModifiedEvent`, `FileDeletedEvent`, `FileMovedEvent`.
  - `Observer` runs in a background thread; dispatches to `FileSystemEventHandler` subclass callbacks.
  - Internal `EventQueue` is thread-safe and deduplicates consecutive identical events.
  - Does NOT work across processes out of the box — the `Observer` object is per-process.
  - A parent process using watchdog CAN react to file modifications made by child processes — that cross-process observation works because the OS emits filesystem events regardless of which process touched the file.
  - No heartbeat semantics, no crash-resilience, no registry. Pure event detection.
- **Implications for TeaParty:** A parent team could use watchdog to observe a directory where child teams write heartbeat files, triggering a callback when a file's mtime stops updating. This is reactive (event-driven) rather than polling, which is more efficient. However, the fallback polling backend (used on some filesystems) has 1-second granularity. This is a clean architectural fit for parent-watches-children at the filesystem layer.

---

### python-prctl (v1.6.1)
- **URL:** https://pythonhosted.org/python-prctl/ / https://pypi.org/project/python-prctl/
- **Maturity:** Stable but Linux-only. Wraps Linux `prctl(2)` syscall.
- **Key findings:**
  - `prctl.set_pdeathsig(signal.SIGTERM)` causes the kernel to send a signal to the calling process when its parent dies.
  - Must be called in the child process (typically in `subprocess.Popen`'s `preexec_fn`).
  - Setting is inherited across `exec()` calls.
  - Without this, killing a parent leaves children reparented to PID 1 (init) and running indefinitely — a major operational hazard for hierarchical process trees.
  - On macOS/Windows: no direct equivalent. Workaround is polling `os.getppid()` in a background thread and self-terminating when parent PID changes.
- **Implications for TeaParty:** `set_pdeathsig(SIGTERM)` is the correct mechanism for ensuring child teams exit when their parent team dies, on Linux. For macOS development, a polling thread checking `os.getppid()` is the fallback. This directly addresses the "crash-resilient" and "hierarchical" requirements — it is an OS-level guarantee rather than a software heartbeat.

---

### Celery file-touch heartbeat pattern (extractable idiom)
- **URL:** https://github.com/celery/celery/issues/3694 / https://celery.school/docker-health-check-for-celery-workers
- **Maturity:** Well-established operational pattern, not a standalone library.
- **Key findings:**
  - Celery's own health check approach for Kubernetes: create a file at worker startup; `touch` it (update mtime) at the end of each task loop iteration.
  - A parent or probe checks whether the file's mtime is recent (within N seconds). If stale, the worker is declared unhealthy.
  - This pattern requires no broker, no server, no shared memory — just a file and mtime comparison.
  - The file-touch approach is crash-resilient: if the process dies, it stops touching the file. The parent detects staleness by elapsed time, not by receiving an explicit death signal.
  - Concurrent safety concern: if multiple processes write to the same file, `filelock` is required around the touch.
- **Implications for TeaParty:** This is the core idiom for a file-based heartbeat primitive. Each worker process writes its own file (named by PID or role) in a shared directory. The parent polls mtimes or uses watchdog to react to modification events. The file contains enough metadata (PID, last_heartbeat ISO timestamp, status enum) for the parent to decide health. This is the most appropriate pattern given the no-broker, crash-resilient, hierarchical constraints.

---

### circus (Mozilla/circus-tent, v0.18)
- **URL:** https://pypi.org/project/circus/ / https://circus.readthedocs.io/
- **Maturity:** Stable but in maintenance mode. Requires ZeroMQ.
- **Key findings:**
  - Full process supervisor: spawns, monitors, restarts processes.
  - Built-in `watchdog` plugin: binds a UDP socket; processes send UDP heartbeat messages; if a process misses `max_count` heartbeats at `loop_rate`, circus kills it.
  - UDP heartbeat format: plaintext line containing at minimum the PID.
  - Requires the circus daemon to be running — it IS a central server.
  - The watchdog plugin is NOT extractable as a standalone library; it depends on the circus event bus.
- **Implications for TeaParty:** The heartbeat design (UDP + PID + periodic message) is instructive as a pattern, but circus itself is the wrong fit — it requires a running daemon and ZeroMQ infrastructure. The conceptual insight worth borrowing: heartbeat messages carry the PID, not just a ping, enabling the monitor to correlate with OS-level process state.

---

### multiprocessing.managers / SyncManager (stdlib)
- **URL:** https://docs.python.org/3/library/multiprocessing.html
- **Maturity:** Standard library. Well-tested.
- **Key findings:**
  - `multiprocessing.managers.SyncManager` hosts shared Python objects (dicts, lists, queues) accessible from multiple processes via proxy objects.
  - Proxies serialize all access through the manager process, ensuring thread/process safety.
  - The manager process itself is a single point of failure: if the manager dies, all proxy operations raise `ConnectionError` in worker processes.
  - `multiprocessing.Queue` is process-safe without a manager.
  - `multiprocessing.Value` + `Lock` provides shared numeric state (e.g., a heartbeat counter) with process safety, but requires the processes to be spawned from a common parent.
- **Implications for TeaParty:** SyncManager is inappropriate for crash-resilient liveness monitoring because the monitor (the manager) is itself a SPOF. A child process dying causes the manager no trouble, but the manager dying takes down all monitoring state. The correct use of stdlib here is `multiprocessing.Queue` for passing heartbeat events between related processes (e.g., within a single team's process group), not for cross-team monitoring.

---

### pyheartbeat (PyPI)
- **URL:** https://pypi.org/project/pyheartbeat/
- **Key findings:**
  - Sends heartbeat pulses to an HTTP endpoint via a background thread.
  - Supports APScheduler-based business-hours scheduling and API token auth.
  - Designed for external monitoring services (Healthchecks.io, Uptime Robot, etc.).
  - No local process-to-process semantics; no file-based operation.
- **Implications for TeaParty:** Wrong fit. Requires an HTTP endpoint and external service.

---

### single-beat (PyPI)
- **URL:** https://libraries.io/pypi/single-beat
- **Key findings:**
  - Ensures only one instance of a process runs at a time using Redis as the coordination store.
  - Updates a Redis key every `HEARTBEAT_INTERVAL` seconds with TTL of `LOCK_TIME` seconds.
  - In supervised mode, waits for a running instance to die before starting another.
  - Requires Redis — not broker-free.
- **Implications for TeaParty:** Wrong fit. Redis dependency violates the no-central-server constraint.

---

## Composed Primitive for TeaParty

Based on the survey, the right design is not a single library but a composition of three layers:

**Layer 1 — Heartbeat file (mtime-stamp)**
Each worker process maintains a heartbeat file (e.g., `~/.teaparty/workers/<pid>.heartbeat`). The file contains a JSON blob: `{pid, role, started_at, last_beat, status}`. The worker `touch`es it (rewrites or calls `os.utime`) at regular intervals. On clean shutdown the file is deleted; on crash it remains stale.

**Layer 2 — Concurrent-safe writes**
`filelock` wraps any write to the heartbeat file, serializing concurrent updates from multiple workers targeting a shared registry file (if preferred over per-PID files).

**Layer 3 — Parent observation**
Two options:
- *Polling:* Parent reads all `*.heartbeat` files in the directory every N seconds, checks `mtime` age against a threshold, and cross-validates live PIDs with `psutil.pid_exists()`.
- *Reactive:* Parent runs a `watchdog` `Observer` on the heartbeat directory; reacts to `FileModifiedEvent` / `FileDeletedEvent` to track liveness changes in near-real-time.

**Layer 4 — Hierarchical death propagation (Linux)**
`python-prctl` `set_pdeathsig(SIGTERM)` in child processes ensures they self-terminate when the parent exits, preventing orphaned subteams. On macOS, a polling thread checking `os.getppid()` is the fallback.

**What not to build:** A custom UDP heartbeat, a Redis/ZeroMQ broker, a shared-memory manager process, or any HTTP endpoint. The file + psutil + prctl stack covers all five stated requirements with no external dependencies.

---

## Sources

- [psutil on PyPI](https://pypi.org/project/psutil/)
- [psutil GitHub](https://github.com/giampaolo/psutil)
- [filelock on PyPI](https://pypi.org/project/filelock/)
- [filelock GitHub (tox-dev)](https://github.com/tox-dev/filelock)
- [pid on PyPI](https://pypi.org/project/pid/)
- [watchdog on PyPI](https://pypi.org/project/watchdog/)
- [watchdog GitHub](https://github.com/gorakhargosh/watchdog)
- [python-prctl docs](https://pythonhosted.org/python-prctl/)
- [PR_SET_PDEATHSIG Linux man page](https://man7.org/linux/man-pages/man2/pr_set_pdeathsig.2const.html)
- [SET_PDEATHSIG from Python (blog)](https://blog.raylu.net/2021/04/01/set_pdeathsig.html)
- [Celery file-touch healthcheck pattern](https://celery.school/docker-health-check-for-celery-workers)
- [Celery Kubernetes liveness probe issue](https://github.com/celery/celery/issues/4079)
- [circus watchdog plugin](https://circus.readthedocs.io/en/latest/for-ops/using-plugins/)
- [single-beat on libraries.io](https://libraries.io/pypi/single-beat)
- [pyheartbeat on PyPI](https://pypi.org/project/pyheartbeat/)
- [Python multiprocessing docs](https://docs.python.org/3/library/multiprocessing.html)
- [Ensuring subprocesses exit when parents die (gist)](https://gist.github.com/evansd/2346614)
