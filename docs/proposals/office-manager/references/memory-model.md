# Memory Model

The office manager uses the same ACT-R memory infrastructure as the proxy. Same `MemoryChunk` dataclass, same activation dynamics, same SQLite storage. Different chunk types.

## Chunk Types

| Type | What it captures | Example |
|------|-----------------|---------|
| `inquiry` | What a human asked about | "Asked about POC project status" |
| `steering` | Priority or preference directive | "Decider wants security focus across all sessions" |
| `action_request` | What a human asked the office manager to do | "Requested commit and push for all projects" |
| `context_injection` | Domain knowledge a human volunteered | "Advisor: switching to Postgres next quarter" |

Chunks are attributed to the human who produced them. The decider's steering chunks are prediction targets for the proxy; an advisor's context injections are informational.

## Shared Memory Pool

The office manager and the proxy serve the same decider. Both read and write to the same `.proxy-memory.db`. Chunk type discriminates reads: the proxy queries for `gate_outcome` chunks, the office manager queries for `inquiry` and `steering` chunks. Either can query across types when the structural filters match. The proxy retrieving a `steering` chunk ("decider said focus on security") while reviewing a security plan is the right behavior.

SQLite in WAL mode handles concurrent access. The FIFO queue serializes proxy invocations (see [participation-model](../../references/participation-model.md)), so only one proxy instance writes at a time. Write contention is negligible.

## Recording Chunks from Conversation

The office manager itself decides what to record. At conversation end, a final prompt turn asks the office manager to summarize what the humans cared about and produce memory chunks. This is consistent with how agents work in this system: they are autonomous, not scripted. The recording is an agent judgment, not a mechanical extraction.

## Scaling Considerations

After months of use across multiple projects, the memory pool could contain thousands of chunks. The fan effect (retrieval quality degrades as more chunks share features) is a known ACT-R limitation. The retrieval threshold and decay parameter will need tuning during implementation. A consolidation strategy for low-activation chunks should be evaluated once chunk volumes are observable.
