# Federated Teams — Detailed Design

**Status:** Design · supersedes the architecture sketch
**Reading order:** §1 invariants → §2 data model → §3 negotiation protocol →
§4 membrane → §5 delegate-memory → §6 cost → §7 enforcement → §8 example.

This specifies the cross-human system to implementation grade on its spine: the
contract state machine, the mandate evaluation function, the membrane wire
protocol with its consistency model, the delegate-memory retrieval and update
rules, and the execution-owner enforcement. Where a value is a tunable, it is
named in `CONSTANTS` and given a default.

---

## 1. Invariants (the things code must guarantee)

- **EO (execution-owner):** every local agent dispatch `d` satisfies
  `d.execution_owner == node.principal_id`. No membrane message can reach a
  dispatch without a signed contract whose `supplier == self`. (§7)
- **CONSENT:** a contract reaches `ACCEPTED` only with **two** signatures on the
  **same** `version_hash`. No state transition imposes work on a supplier.
- **AUTH:** a membrane message is honored only if its GitHub commit author is the
  node registered (in repo config) for `msg.on_behalf_of`. Body claims are never
  trusted. (§4.4)
- **PRIVACY:** the delegate-memory store never serializes onto the membrane. Only
  `Decision` records (§2.1) cross. (§5)
- **NO-SILENT-STALL:** a non-agreement caused by a hard-term clash transitions to
  `DEADLOCKED`, which pages humans. It is never a timeout. (§3.4)

```
CONSTANTS (defaults)
  POLL_INTERVAL_S            = 5
  COUNTER_BUDGET            = 1        # counters allowed per side per contract
  BAND_PROMOTE_RATE        = 0.90
  BAND_PROMOTE_MIN_N       = 10
  BAND_WINDOW              = 20
  PRECEDENT_CONF_THRESHOLD = 0.75
  PRECEDENT_K              = 8
  COST_MIN_SAMPLES         = 8
  COST_EXPLORATORY_BUDGET  = 5_000    # tokens
  COST_OVERRUN_HARD_FACTOR = 1.5
```

---

## 2. Data model

All node-private tables live in one SQLite db per principal
(`~/.teaparty/<principal>/delegate.db`). Shared objects (standing agreements,
roster) live in the repo as reviewed YAML and are mirrored read-only into the
membrane branch.

### 2.1 Decision signature & episode (private)

The unit of memory and the retrieval key.

```sql
CREATE TABLE episodes (
  id            TEXT PRIMARY KEY,         -- sha256 of canonical signature
  ts            REAL NOT NULL,
  -- signature --------------------------------------------------------------
  domain        TEXT NOT NULL,            -- project taxonomy (roster-defined)
  decision_type TEXT NOT NULL,            -- enum below
  stakes        INTEGER NOT NULL,         -- 0..3 ordinal, derived (§2.2)
  reversibility TEXT NOT NULL,            -- REVERSIBLE|COSTLY|IRREVERSIBLE
  blast_radius  TEXT NOT NULL,            -- LOCAL|TEAM|PROJECT|EXTERNAL
  scope_ids     TEXT NOT NULL,            -- json array of affected scopes
  options       TEXT NOT NULL,            -- json array of option descriptors
  -- decision ---------------------------------------------------------------
  predicted     INTEGER,                  -- proxy's predicted option index|null
  chosen        INTEGER,                  -- final option index
  actor         TEXT NOT NULL,            -- HUMAN|PROXY
  reason        TEXT,                     -- stated rationale (free text)
  outcome       TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|CONFIRMED|CORRECTED|ABANDONED
  agreement     INTEGER,                  -- 1 if chosen==predicted else 0 (set on resolve)
  -- features for retrieval -------------------------------------------------
  feat          BLOB                      -- packed float vector (§5.2)
);
CREATE INDEX ix_ep_cell ON episodes(domain, decision_type, stakes);

-- decision_type enum:
--   ACCEPT_JOB        accept/reject an external request
--   APPROVE_ARTIFACT  sign off on a produced artifact (intent/plan/exec)
--   CHOOSE_OPTION     pick among generated options
--   RESOLVE_AMBIGUITY answer a clarifying question
--   AUTHORIZE_SPEND   approve a cost above a threshold
--   PRIORITIZE        order/triage competing work
```

### 2.2 Stakes derivation (deterministic)

```
stakes(reversibility, blast_radius) -> 0..3 :
  r = {REVERSIBLE:0, COSTLY:1, IRREVERSIBLE:2}[reversibility]
  b = {LOCAL:0, TEAM:1, PROJECT:2, EXTERNAL:3}[blast_radius]
  return min(3, round((r + b) / 2 + 0.49))   # bias up on ties
```

`reversibility`/`blast_radius` are classified at gate time by a cheap LLM call
(reusing `scripts/classify_*`), cached on the episode.

### 2.3 Policy (private, distilled)

```sql
CREATE TABLE policies (
  id            TEXT PRIMARY KEY,
  domain        TEXT NOT NULL,
  decision_type TEXT,                      -- null = applies to all types in domain
  predicate     TEXT NOT NULL,             -- json structured condition (§3.2 grammar)
  directive     TEXT NOT NULL,             -- what to do when predicate holds
  hardness      TEXT NOT NULL,             -- HARD|SOFT  (HARD => reservation)
  confidence    REAL NOT NULL,             -- 0..1
  provenance    TEXT NOT NULL,             -- json array of supporting episode ids
  status        TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE|SUPERSEDED|RETIRED
  ts_updated    REAL NOT NULL
);
```

`HARD` policies are the **reservation values**; they come from explicit human
config and from corrections on high-stakes cells (§5.3). `SOFT` policies carry a
`preferred` value and `acceptable_range` inside `directive`.

### 2.4 Risk frontier (private)

```sql
CREATE TABLE risk_frontier (
  domain        TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  stakes        INTEGER NOT NULL,
  band          TEXT NOT NULL,             -- ASK_ALWAYS|ASK_WHEN_UNSURE|ACT_AND_TELL|ACT_SILENT
  n             INTEGER NOT NULL DEFAULT 0,
  window        TEXT NOT NULL DEFAULT '[]',-- json ring buffer of last BAND_WINDOW agreements (0/1)
  corrections   INTEGER NOT NULL DEFAULT 0,
  last_corr_ts  REAL,
  PRIMARY KEY (domain, decision_type, stakes)
);
-- band order (promote →):  ASK_ALWAYS < ASK_WHEN_UNSURE < ACT_AND_TELL < ACT_SILENT
```

### 2.5 Standing agreement (shared, repo + membrane)

```yaml
# .teaparty/agreements/<pair_id>.yaml   (PR-reviewed)
pair_id: alice~bob              # sorted principal ids
version: 7
parties: [alice, bob]
# bidirectional; each direction lists the lanes the supplier grants the requester
lanes:
  - supplier: bob
    requester: alice
    scope: billing/*            # glob over scope ids
    budget:
      tokens_per_week: 200000
      per_job_soft: 50000
      wall_sla_hours: 48
    auto_sign:                  # the soft envelope under which bob's proxy may sign
      max_stakes: 1             # ≤ COSTLY auto-signable; higher escalates
      review_level: STANDARD
  - supplier: alice
    requester: bob
    scope: api/*
    budget: { tokens_per_week: 150000, per_job_soft: 40000, wall_sla_hours: 72 }
    auto_sign: { max_stakes: 1, review_level: STANDARD }
signatures:                     # both humans (or proxies under mandate) on this version
  alice: { actor: HUMAN, ts: 1739... , version_hash: 9af.. }
  bob:   { actor: HUMAN, ts: 1739... , version_hash: 9af.. }
```

A lane is a **scope-grant + budget envelope**. Grants are **role/scope-attached**
(open decision resolved this way): the lane keys on `scope`, not on a personal
identity, so it survives personnel rotation; `supplier`/`requester` name the
principals currently holding those scopes per the roster.

### 2.6 Contract (per job; canonical snapshot on membrane)

```jsonc
{
  "id": "ctr_01HX..",            // ULID
  "version": 2,
  "version_hash": "…",           // sha256 of (terms, parties) at this version
  "requester": "alice",
  "supplier":  "bob",
  "agreement": { "pair_id":"alice~bob", "agreement_version":7, "lane":0 },
  "terms": {
    "scope":    { "summary":"…", "scope_ids":["billing/invoices"], "artifacts":["PR"] },
    "intent_ref":"membrane://contracts/ctr_01HX../intent.md",
    "plan_ref":  null,           // filled after planning
    "cost":     { "estimate_p90": 38000, "envelope_remaining": 162000, "exploratory": false },
    "schedule": { "deadline_ts": 1739..., "priority": "HIGH" },
    "review_level": "STANDARD"
  },
  "value": { "priority":"HIGH", "rationale":"critical path for Q3 close" },
  "state": "PROPOSED",
  "signatures": {
    "alice": { "actor":"PROXY", "on_behalf_of":"alice", "version_hash":"…", "ts":1739… },
    "bob":   null
  },
  "history": [ /* prior versions + events */ ]
}
```

---

## 3. Negotiation protocol

A cross-membrane CfA is the lifecycle of one Contract.

### 3.1 State machine

States: `DRAFT, PROPOSED, COUNTERED, ACCEPTED, ACTIVE, AMENDING, FULFILLED,
REJECTED, WITHDRAWN, DEADLOCKED`.

| # | From | Event (actor) | Guard | To | Membrane msg |
|---|------|---------------|-------|----|--------------|
|1|—|create (requester)|—|DRAFT|—|
|2|DRAFT|propose (requester)|requester signed `v`|PROPOSED|`proposal`|
|3|PROPOSED|sign (supplier)|`evaluate==SIGN`|ACCEPTED|`accept`|
|4|PROPOSED|counter (supplier)|`evaluate==COUNTER ∧ budget>0`|COUNTERED|`counter`|
|5|PROPOSED|reject (supplier)|`evaluate==REJECT`, no hard clash|REJECTED|`reject`|
|6|PROPOSED|deadlock (supplier)|hard clash, uncounterable|DEADLOCKED|`deadlock`|
|7|PROPOSED|*escalate* (supplier-proxy)|`evaluate∈{ESCALATE}`|PROPOSED (parked)|— (local page)|
|8|COUNTERED|sign (requester)|`evaluate==SIGN`|ACCEPTED|`accept`|
|9|COUNTERED|reject (requester)|no hard clash|REJECTED|`reject`|
|10|COUNTERED|deadlock (requester)|hard clash|DEADLOCKED|`deadlock`|
|11|ACCEPTED|activate (supplier)|both sigs on `version_hash`|ACTIVE|`activated`|
|12|ACTIVE|amend (supplier)|overrun ∨ scope-surprise|AMENDING|`amend`|
|13|AMENDING|sign (requester)|`evaluate==SIGN`|ACTIVE|`accept`|
|14|AMENDING|reject (requester)|—|WITHDRAWN|`withdraw`|
|15|AMENDING|deadlock (either)|hard clash|DEADLOCKED|`deadlock`|
|16|ACTIVE|deliver (supplier)|artifact accepted by requester|FULFILLED|`delivered`|
|17|ACTIVE/AMENDING|withdraw (either)|—|WITHDRAWN|`withdraw`|

Terminal: `FULFILLED, REJECTED, WITHDRAWN`. `DEADLOCKED` is terminal-until-human;
a human action re-enters at `PROPOSED` (new version) or `WITHDRAWN`.

**Counter-once** is enforced by `COUNTER_BUDGET` decremented per side; from
`COUNTERED` no further counter transition exists — only sign/reject/deadlock.

**Two-axis signing.** For `APPROVE_ARTIFACT` terms the *requester* signs
correctness; for `cost`/`schedule` the *supplier* signs affordability. A single
contract version carries both; `ACCEPTED` needs the union satisfied. In practice
the requester's correctness sign is on `intent_ref`/`plan_ref`, the supplier's
on `cost`/`schedule`.

### 3.2 Mandate & predicate grammar

A mandate is assembled per `(domain, decision_type)` from policies + the lane +
the risk band. Predicates are a small JSON expression language evaluated against
`contract.terms`:

```
pred := {"op":"<=", "lhs":"cost.estimate_p90", "rhs":50000}
      | {"op":"in", "lhs":"scope.scope_ids[*]", "rhs":["billing/*"]}
      | {"op":">=", "lhs":"schedule.deadline_ts", "rhs":"now+48h"}
      | {"op":"all"|"any", "args":[pred, …]}
lhs paths resolve against terms; globs allowed; "now+Nh" is wall-clock.
```

### 3.3 The decision function (the crux)

Run by a proxy when it is asked to sign a contract version.

```python
def evaluate(contract, mandate, frontier, precedents) -> Decision:
    sig = signature(contract)                       # domain, decision_type, stakes, scope
    # 1. HARD gate — reservations must hold
    for t in mandate.hard_terms():
        if not t.predicate(contract.terms):
            fix = minimal_counter_into(t, contract)  # e.g. lower cost to t.bound
            if fix is not None and within_soft_envelope(fix, mandate):
                return Decision.COUNTER(fix, reason=t.id)
            return Decision.ESCALATE(reason=("hard_violation", t.id))   # human must except/decline
    # 2. BAND gate
    band = frontier.band(sig)                        # with backoff (§5.3)
    if band == "ASK_ALWAYS":
        return Decision.ESCALATE(reason="band")
    # 3. SOFT optimization — counter toward preferred, but concede inside acceptable
    counter = {}
    for t in mandate.soft_terms():
        v = read(contract.terms, t.dimension)
        if not t.acceptable(v):
            counter[t.dimension] = t.clamp_to_acceptable(v)   # must-fix soft
        elif v != t.preferred and band == "ASK_WHEN_UNSURE":
            counter[t.dimension] = t.preferred                # opportunistic
    if counter and mandate.counter_budget > 0:
        return Decision.COUNTER(counter, reason="soft")
    # 4. autonomy resolution
    if band == "ASK_WHEN_UNSURE":
        conf = precedents.agreement_confidence(sig)           # §5.2
        return Decision.SIGN() if conf >= PRECEDENT_CONF_THRESHOLD \
               else Decision.ESCALATE(reason="low_precedent_conf")
    if band == "ACT_AND_TELL":
        return Decision.SIGN(notify=True)
    return Decision.SIGN()                                     # ACT_SILENT
```

`ESCALATE` is not a contract state — it parks the contract (`PROPOSED`/`AMENDING`)
and pages the human (§4.5). The human then drives sign/counter/reject. A human
sign is always valid; a proxy sign is valid only when `evaluate==SIGN`.

### 3.4 Reject vs deadlock

`reject` and `deadlock` differ by *cause*, classified at the rejecting side:

```python
def classify_terminal(contract, mandate) -> ("REJECT" | "DEADLOCK"):
    for t in mandate.hard_terms():
        if not t.predicate(contract.terms) and minimal_counter_into(t, contract) is None:
            return "DEADLOCK"      # an irreducible hard-term clash
    return "REJECT"               # a choice not to proceed; requester reroutes
```

`DEADLOCK` emits a `deadlock` message whose body is the **clashing-clause diff**
(this side's violated hard term vs the contract value) and pages both humans.

---

## 4. The membrane (GitHub transport)

### 4.1 Branch layout

One orphan, append-only branch `teaparty-membrane`:

```
inbox/<node_id>/<ulid>.json        # sender writes; recipient reads; unique path
acks/<node_id>/<ulid>              # recipient writes (empty) to permit sender GC
contracts/<contract_id>/<n>.json   # canonical contract snapshots (versioned)
contracts/<contract_id>/intent.md  # artifacts referenced by terms
standing/<pair_id>.json            # mirror of the repo agreement (read-only here)
```

### 4.2 Envelope

```jsonc
{
  "ulid": "01HX…",                 // id + total order by creation time
  "kind": "proposal|counter|accept|reject|deadlock|amend|activated|delivered|withdraw|request",
  "contract_id": "ctr_…",
  "in_reply_to": "01HX… | null",
  "on_behalf_of": "bob",           // principal; MUST match commit author's node (AUTH)
  "execution_owner": "bob",        // only meaningful on request/activated
  "addressed_to": "alice",
  "scope": "billing/invoices",
  "provenance": "AGENT|HUMAN",
  "body": { /* contract delta, counter terms, or deadlock diff */ }
}
```

### 4.3 Consistency model — conflict-free by construction

- Every message is a **new, uniquely-named file** (`inbox/<recipient>/<ulid>`).
  Two senders → different ULIDs → disjoint paths. A node only **writes to
  others' inboxes** and **reads/GCs its own** → single-writer per file.
- A push race on the ref is resolved by `fetch → rebase → repush`; because writes
  never touch the same path, the rebase is always a clean fast-forward of
  disjoint additions. Retry with backoff (the existing push-retry policy).
- **Ordering:** ULID lexical order = creation order; recipients process in ULID
  order. **Idempotency:** processing keyed on ULID against a local high-water
  mark; reprocessing is a no-op. **At-least-once** delivery + idempotent apply =
  effectively-once.
- **Contract snapshots** (`contracts/<id>/<n>.json`) are the source of truth for
  state; inbox messages are the *events* that advance it. A node rebuilds
  contract state by folding its events over the latest snapshot (event sourcing),
  so a lost ack or duplicated event cannot corrupt state.

### 4.4 Identity enforcement (AUTH)

On ingest, before any processing:

```python
def ingest(msg, commit):
    node = roster.node_for_principal(msg.on_behalf_of)   # from PR-reviewed config
    if commit.author_key != node.signing_key:            # GitHub-verified author
        return DROP(reason="auth: author≠principal's node")
    if msg.kind in {"request","activated"} and msg.execution_owner != msg.on_behalf_of:
        return DROP(reason="auth: cannot dispatch for another principal")
    apply(msg)
```

Authorization to *speak for* a principal derives from repo config (membership +
node registration), which changes only via reviewed PR.

### 4.5 Channels by audience

- **Machine handoffs / contract events:** the inbox/contract files above (polled).
- **Human-facing review & signing:** a contract that escalates is rendered to a
  **PR** (when an artifact is involved) or an **issue** (decision-only), addressed
  to the principal's human, carrying the human-readable contract and
  ACCEPT/COUNTER/REJECT affordances (PR review approval, or a
  `/sign|/counter|/reject` comment command). The node watches its own PRs/issues
  and translates the human action into the corresponding membrane message. This
  gives transparency/contestability for free and keeps the audit trail in git.

### 4.6 Polling loop

```python
every POLL_INTERVAL_S (or on repository_dispatch wake):
    tree = fetch("teaparty-membrane", if_none_match=etag)   # conditional GET
    if not modified: continue
    for f in sorted(ls(f"inbox/{self}/")) where ulid(f) > high_water:
        msg = read(f); ingest(msg)
        write(f"acks/{msg.sender}/{msg.ulid}", b""); high_water = ulid(f)
    flush_outgoing()                                         # commit our files, push w/ retry
```

NAT'd nodes poll; a node that runs a personal always-on daemon (still one human,
compliant) can subscribe to `repository_dispatch` to cut latency.

---

## 5. Delegate-memory (private, on-node)

### 5.1 Layers and their retrieval

For a gate query `Q = signature(contract)` the proxy assembles a **context
triple**:

1. **Policies** — `SELECT … WHERE domain=Q.domain AND (decision_type=Q.decision_type
   OR decision_type IS NULL) AND status='ACTIVE'`, keep those whose `predicate`
   matches `Q`, rank by `confidence * recency_decay(ts_updated)`.
2. **Precedents** — k-NN (`PRECEDENT_K`) over `episodes.feat` by cosine, filtered
   to `domain=Q.domain`. Returns the analogous past decisions with their outcomes.
3. **Risk band** — `frontier.band(Q)` (§5.3).

These three are injected into the proxy prompt (replacing today's flat chunk
list in `proxy/hooks.py:proxy_build_prompt`).

### 5.2 Feature vector & precedent confidence

```
feat(ep) = concat(
   onehot(domain), onehot(decision_type),
   [stakes/3, r_ord/2, b_ord/3],
   minhash(scope_ids, 16),
   embed(reason)[:64]            # optional; zeros if no embedding provider
)
agreement_confidence(Q):
   N = knn(Q, PRECEDENT_K)
   if not N: return 0.0
   w_i = cosine(Q, N_i) * recency_decay(N_i.ts)
   return Σ w_i·[N_i.outcome==CONFIRMED] / Σ w_i
```

`agreement_confidence` is what gates `ASK_WHEN_UNSURE` → sign/escalate (§3.3).

### 5.3 Band lookup with backoff & the update rule

```python
def band(Q):
    for key in [(Q.domain,Q.decision_type,Q.stakes),
                (Q.domain,Q.decision_type,"*"),
                (Q.domain,"*","*"), ("*","*","*")]:
        if row := frontier.get(key): return row.band
    return "ASK_ALWAYS"                      # cold start = conservative

def on_resolve(ep):                          # called when outcome becomes known
    ep.agreement = int(ep.chosen == ep.predicted)
    c = frontier.cell(ep)                     # create at ASK_ALWAYS if absent
    c.n += 1; c.window.push(ep.agreement)
    if ep.outcome == "CONFIRMED":
        if rate(c.window) >= BAND_PROMOTE_RATE and len(c.window) >= BAND_PROMOTE_MIN_N:
            c.band = promote(c.band)          # one step up
    elif ep.outcome == "CORRECTED":
        c.corrections += 1; c.last_corr_ts = now()
        if ep.stakes >= 1:                    # COSTLY+ → hard reset (asymmetric regret)
            c.band = "ASK_ALWAYS"
        else:
            c.band = demote(c.band, steps=2)  # cheap miss → drop two
        c.window = clear(c.window)            # corrections invalidate the promotion run
        policies.upsert_from_correction(ep)   # mint/revise a SOFT (or HARD if stakes≥2) policy
    frontier.put(c)
```

Asymmetry is explicit: promotion needs a sustained run; a single costly
correction collapses to `ASK_ALWAYS`. This is the "false approvals cost more than
false escalations" rule, realized as band dynamics rather than a comment.

### 5.4 Shared vs private split

The existing `learning/` promotion chain (session→team→project→global) carries
**org norms** (shared, committed). The four tables above are the **personal
delegate-model** and never promote off-node. The two pipelines share extraction
code (`learning/extract.py`) but write to different stores with opposite trust
direction. This split is the privacy guarantee from §1 (PRIVACY).

---

## 6. Cost & schedule

### 6.1 Estimate (from telemetry)

```python
def estimate(job_sig) -> CostDist:
    rows = telemetry.query(domain=job_sig.domain, kind=job_sig.decision_type)  # token+wall per past job
    if len(rows) < COST_MIN_SAMPLES:
        return CostDist(unknown=True, exploratory=COST_EXPLORATORY_BUDGET)
    return CostDist(median=median(rows.tokens), p90=p90(rows.tokens),
                    wall_p90=p90(rows.wall), n=len(rows))
```

### 6.2 Cost gate (after planning)

```python
def cost_gate(contract, dist, lane):
    remaining = lane.tokens_per_week - consumed_this_period(lane)
    cap = min(remaining, lane.per_job_soft)
    if dist.unknown:
        if dist.exploratory <= remaining:
            run_scoping(budget=dist.exploratory); return cost_gate(contract, estimate(...), lane)
        return Decision.ESCALATE(reason="cost_unknown_no_budget")
    if dist.p90 <= cap:                         return PASS(estimate=dist.p90)
    return Decision.COUNTER(reduce_scope_to(cap)) or Decision.ESCALATE("cost")
```

### 6.3 Overrun monitor (during ACTIVE)

The runner already records tokens per turn. A subscriber compares cumulative to
`contract.terms.cost.estimate_p90`:

```
on_token_tick(contract, consumed):
   if consumed >= estimate_p90:                          emit warning (soft)
   if consumed >= COST_OVERRUN_HARD_FACTOR * estimate_p90:
        pause_execution(); transition(contract, ACTIVE→AMENDING); re-quote   # §3.1 row 12
```

### 6.4 Quota protection (layered)

- **Hard** global per-principal cap (`spent_on_shared_this_week ≤ G`) — a node
  refuses to `activate` any contract that would breach `G`, regardless of lane.
- **Soft** lane envelopes within `G`.
- **Soft** per-job estimate with **hard** overrun escalation (§6.3).

Consumption is attributed per `(principal, pair, contract)` and surfaced so a
human can see the project leaning on their quota and throttle.

---

## 7. Execution-owner enforcement

The single chokepoint where an agent subprocess is launched:

```python
def dispatch_local(task):
    assert task.execution_owner == NODE.principal_id, "EO violation"
    assert task.contract is None or (
        task.contract.state == "ACTIVE" and task.contract.supplier == NODE.principal_id
    ), "no signed contract authorizes this work"
    launch_agent(task)            # the only place runners/ are invoked
```

There is **no** code path from `ingest()` (§4.4) to `dispatch_local()` that
bypasses a signed contract: a membrane message can only create/advance a Contract;
only transition #11 (`activate`, guarded by two signatures and `supplier==self`)
constructs a local task, and it sets `execution_owner = self`.

**Conformance test (CI):**

```
property test_eo(hostile_msg):
   # hostile_msg: arbitrary kind/body, including execution_owner=self from a
   # foreign commit author, and "accept" messages without a matching proposal.
   node.ingest(hostile_msg)
   assert launch_agent was NOT called
   assert no contract reached ACTIVE without two valid signatures on one version_hash
   assert every launch_agent.task.execution_owner == node.principal_id
```

This test is the operational definition of ToS-compliance and must be green to
ship any membrane change.

---

## 8. Worked example (concrete messages)

Alice needs a change in `billing/*` (Bob's scope). Standing agreement `alice~bob`
v7 grants Alice a `billing/*` lane, `per_job_soft=50k`, `auto_sign.max_stakes=1`.

1. **Provenance gate** on Alice's lead: target scope `billing/*` ∉ Alice's scopes
   → external. It creates `ctr_…` (DRAFT), attaches lane 0, Alice's proxy signs
   `v1` (cost not yet known; correctness intent only), → PROPOSED, writes
   `inbox/bob/<ulid>.json kind=proposal`.
2. Bob's node polls, `ingest` passes AUTH. Bob's proxy runs `evaluate` for
   `ACCEPT_JOB`: `domain=billing, stakes=1`. Lane hard term `cost ≤ 50k` not yet
   bindable (no plan) → proxy **plans first** (intent accepted in principle),
   producing `plan_ref` and `estimate(billing,…).p90 = 38k`. Now `cost_gate`:
   `38k ≤ min(remaining=162k, 50k)` → PASS. Band `billing/ACCEPT_JOB/1 =
   ACT_AND_TELL`, no hard violation → `evaluate==SIGN(notify=True)`. Bob's proxy
   signs `v2`, → ACCEPTED, writes `kind=accept`; node notifies Bob (act-and-tell).
3. `activate`: both sigs on `v2.version_hash`, `supplier==bob` → ACTIVE.
   `dispatch_local` runs the work on **Bob's** account in Bob's worktree.
4. Mid-run tokens hit `1.5×38k=57k` → overrun → ACTIVE→AMENDING, re-quote 70k,
   `kind=amend` to Alice. Alice's proxy: `70k` still ≤ her value/priority budget
   and within her mandate → `SIGN` → back to ACTIVE.
5. Deliverable returns as a **PR** under Bob's name; Alice's requester-side
   correctness sign (PR approval) → `kind=delivered` → FULFILLED.
6. Counterfactual: had Bob's mandate carried a HARD term "no `billing/*` changes
   within 2 days of close" and Alice's deadline violated it with no counter that
   satisfies both → `classify_terminal == DEADLOCK` → `kind=deadlock` with the
   clause diff, paging both humans. Nothing runs.

---

## 9. Reuse map

| Existing | Role in this design |
|---|---|
| `cfa/statemachine`, `cfa/engine` | host the Contract state machine (§3.1) + amendment backtracks |
| `cfa/gates/escalation.py` | the ESCALATE→human path (§3.3, §4.5); policy knobs → bands |
| `messaging/conversations.py` | the **local** bus tier, unchanged |
| `proxy/memory.py` (ACT-R) | the **episodic** layer (§5.1) |
| `proxy/hooks.py:proxy_build_prompt` | inject the context triple instead of a flat list |
| `learning/extract.py`, `learning/promotion.py` | shared org-norm path; reused extractor for private policies (§5.4) |
| `telemetry/query.py` | cost estimate source (§6.1) |
| `config/roster.py`, `util/role_enforcer.py` | principal/scope/node registration; AUTH (§4.4) |
| runners (`runners/claude.py`) | `dispatch_local` chokepoint (§7); token ticks (§6.3) |

## 10. New components

Membrane transport + envelope + event-sourced contract store (§4); the Contract
object & state machine (§3); the mandate assembler + `evaluate` (§3.2–3.3); the
four delegate-memory tables + retrieval/band rules (§5); the cost gate, overrun
monitor, quota cap (§6); the EO chokepoint + conformance test (§7); standing
agreements as PR-reviewed config (§2.5); deadlock detection + paging (§3.4).

## 11. Build phases

1. **Delegate-memory on one node** (§2.1–2.4, §5). Prediction→correction loop,
   bands, retrieval triple. The "other party" is the live human. Independently
   valuable; de-risks the proxy with no federation.
2. **Mandate + Contract + cost gate** (§2.6, §3, §6) — still single-node; the CfA
   between human and their own team becomes a signed Contract.
3. **Membrane v0** (§4, §7) — two principals, inbox transport, EO conformance
   test, AUTH, provenance gate, intake CfA over the wire.
4. **Standing agreements + deadlock** (§2.5, §3.4) — two-tier consent, paging.
5. **Relationship learning + quota attribution** (§6.4) — refine lanes from
   outcomes; surface consumption.

## 12. Open decisions (narrowed)

1. **Policy predicate expressiveness** — the §3.2 grammar covers comparisons,
   set membership, and time. Do we need arithmetic/derived predicates (e.g.
   "cost per scope-id")? Start without; add if a real mandate needs it.
2. **Membrane dialog depth** — multi-turn human escalation *dialog*: on the
   PR/issue (legible, rate-limited) or only the final sign? Leaning PR for the
   audit trail, accepting the rate cost.
3. **Snapshot GC** — when may `contracts/<id>/*` and acked inbox files be pruned
   from the branch history? (history growth vs. auditability).
4. **Embedding provider for `feat`** — required for good precedent recall but
   optional in degraded mode; which provider, and is the 64-dim `reason` slice
   enough?
