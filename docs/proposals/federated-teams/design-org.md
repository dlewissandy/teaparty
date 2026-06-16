# Federated Teams — Organizational Spec (Structure, Work, Engagement)

**Status:** Design · completes [`design.md`](design.md) at the org layer ·
conceptual frame: [`model.md`](model.md)

`design.md` specifies the per-principal spine (contract state machine, membrane
transport, delegate-memory, cost, execution-owner enforcement). This document
specifies the layer above it: how organizations, teams, roles, and memberships
are represented; how initiatives and engagements bind to that structure; the
**intra-org directive protocol** (the light-ceremony path); the **cross-org
engagement membrane**; conflict-of-interest, quota-across-roles, bootstrapping,
failure/recovery; and it closes every open decision (§13).

Conventions, enums, `CONSTANTS`, and the Contract object are inherited from
`design.md`; new constants are named here.

```
CONSTANTS (additions)
  HEARTBEAT_S            = 30
  CONTRACT_SLA_GRACE     = 2.0    # × wall_p90 before an unstarted ACTIVE is reassignable
  INBOX_RETENTION_DAYS   = 90     # acked machine messages compacted after this
  ENGAGEMENT_ARCHIVE_GRACE_DAYS = 30
```

---

## 1. Structure layer — the org-definition repo

An organization is a durable, version-controlled entity. Its source of truth is
an **org-definition repo** (one per org); structural changes land only by
reviewed PR. Layout:

```
.org/
  organization.yaml          # identity, org-mandate, admin model, representatives
  roles/<role_id>.yaml       # role definitions: authority, mandate scope, reporting edge
  teams/<team_id>.yaml       # team substructure: role-slots, nesting
  members/<human_id>.yaml    # humans: node signing key, role bindings, quota
  partnerships/<org_id>.yaml # standing agreements with other orgs
  keys/<human_id>.pub        # published signing keys (read by partners for cross-org AUTH)
  norms/                     # org-internal shared knowledge (promotion-chain target)
  membrane/                  # intra-org membrane branch root (see §4)
```

### 1.1 organization.yaml

```yaml
id: acme
display_name: Acme Corp
admin_model: enterprise_seats | individual_accounts   # §13 item 5
representatives: [eng_director, product_director]      # roles that may sign engagements
mandate:                                               # bounds ALL engagements (org-level)
  hard:
    - { id: no_sec_subcontract, dimension: SCOPE,
        predicate: {"op":"not","args":[{"op":"in","lhs":"scope.scope_ids[*]","rhs":["security/*"]}]} }
    - { id: data_residency, dimension: SCOPE,
        predicate: {"op":"==","lhs":"terms.region","rhs":"us"} }
  soft:
    - { id: default_review, dimension: REVIEW, preferred: STANDARD,
        acceptable: [STANDARD, DEEP] }
```

### 1.2 roles/<role_id>.yaml

A role is a durable seat carrying authority and a mandate scope.

```yaml
id: eng_lead
title: Engineering Lead
parent: eng_director                # functional reporting edge (the hierarchy)
authority:
  may_direct: [eng_ic, qa_ic]       # roles this role has DIRECTIVE authority over
  may_sign_engagements: false       # only representatives sign external contracts
  spend_ceiling_tokens_week: 100000 # role-scoped spend authority
mandate_scope:                      # projected into the per-human mandate when acting AS this role
  domains: [backend, infra]
  max_stakes_auto: 1                # ≤ COSTLY auto-signable in directive mode
  hard:                             # role reservations (merged with personal reservations)
    - { id: no_prod_friday, dimension: SCHEDULE,
        predicate: {"op":"not","args":[{"op":"window","lhs":"now","rhs":"fri 16:00-23:59"}]} }
```

### 1.3 teams/<team_id>.yaml

```yaml
id: platform_team
parent_team: eng                    # team nesting (team-of-teams)
members:                            # role-slots, each filled by a human
  - { role: eng_lead, human: alice }
  - { role: eng_ic,   human: bob }
  - { role: eng_ic,   human: carol }
subteams: [platform_data, platform_api]
```

### 1.4 members/<human_id>.yaml

```yaml
id: alice
display_name: Alice Ng
node:
  signing_key_ref: keys/alice.pub   # GitHub-verified commit-author key (AUTH anchor, §4)
  endpoint: poll | dispatch         # 'dispatch' = always-on personal node (lower latency)
roles: [eng_lead, security_advisor] # many-to-many membership (may span orgs, §13.2)
quota:
  weekly_token_cap: 2000000         # the human's hard total (§7)
  allocation:                       # soft per-role sub-caps; Σ ≤ cap
    eng_lead: 1500000
    security_advisor: 300000
```

### 1.5 Structure is a graph (matrix model — resolves model.md deferred #1)

Two durable relations over roles/teams:

- **Functional hierarchy** — `role.parent` edges. Source of directive authority.
- **Team composition** — `team.members` (role→human) and `team.subteams`.

A **project team** (an initiative's team, §2) is a *transient view*: it selects
role-slots and teams **across** functional lines and binds them with
participation roles. Structure is therefore a graph; an initiative is a
cross-cutting projection of it. No initiative ever edits structure.

### 1.6 partnerships/<org_id>.yaml — the standing agreement

The `design.md` §2.5 standing agreement, **attached to org + role** and persisting
across engagements.

```yaml
partner_org: globex
engagement_space: github.com/acme-globex/engagements   # the partnership repo (§5)
agreement_version: 3
coi_policy: flag | block                               # §6
signed_by:
  acme:   { role: eng_director, human: alice, ts: 1739…, version_hash: 7c1… }
  globex: { role: vp_eng,       human: rao,   ts: 1739…, version_hash: 7c1… }
lanes:
  - direction: acme->globex          # acme requests, globex supplies
    supplier_role: globex/api_team   # a team or role in the partner org
    scope: api/*
    budget: { tokens_per_week: 200000, per_job_soft: 50000, wall_sla_hours: 48 }
    auto_sign: { max_stakes: 1, review_level: STANDARD }
  - direction: globex->acme
    supplier_role: acme/platform_team
    scope: billing/*
    budget: { tokens_per_week: 150000, per_job_soft: 40000, wall_sla_hours: 72 }
    auto_sign: { max_stakes: 1, review_level: STANDARD }
```

---

## 2. Work layer — initiatives, engagements, DAI bindings

### 2.1 Initiative (internal work)

Lives in a workspace repo (`.teaparty/initiative.yaml`); references the org for
authority and staffing.

```yaml
id: 01HX…                     # ULID
org: acme
title: Q3 billing revamp
decider: { unit: dana, acting_as_role: product_lead }   # the initiative WHAT-decider
project_team:                 # the matrix: pulled-in units + DAI bindings (§2.3)
  - { unit: platform_team, participation: DOER }
  - { unit: security_team, participation: ADVISOR }
  - { unit: dana,          participation: DECIDER }
  - { unit: cfo,           participation: INFORMED }
mandate_overrides: {}         # optional initiative-specific tightening
```

### 2.2 Engagement (cross-org work)

An engagement is a `design.md` Contract whose `requester`/`supplier` are **orgs**
acting through representative roles, under a partnership lane. It lives in the
engagement space (§5). It pulls the partner org's team in as a **DOER bound
across the org boundary**. No separate object type — an engagement *is* a
top-level contract with `cross_org: true`.

### 2.3 DAI binding (concrete)

Recorded on the initiative/contract for each participant:

```jsonc
{
  "participation": "DOER | DECIDER | ADVISOR | INFORMED",
  "unit": "team_id | human_id",        // who fills it
  "acting_as_role": "eng_lead",         // authority source (mandate scoped to this role)
  "org": "acme",
  "carries_execution": true             // MUST be true iff participation == DOER
}
```

Invariants:
- **Exactly the DOER binding carries execution.** `carries_execution ⟺ DOER`.
  ADVISOR/INFORMED are information-only and never reach the §7/`design.md`-§7
  dispatch path; an ADVISOR's account never runs the work.
- Every binding names an `acting_as_role`; authority is evaluated against it
  (§3), the delegate-memory is queried with it as a feature (§8).
- A DECIDER binding is the escalation target for its doer(s); the boundary it sits
  across selects the collaboration mode (§3).

### 2.4 Recursive dispatch

Work assigned to a DOER team is itself a CfA: the team's internal decider (or its
liaison) re-dispatches to subteams, each level a contract whose decider is the
level above. Intra-org levels use the directive protocol (§3); a level that
crosses an org boundary uses the engagement membrane (§5). This is the existing
TeaParty recursive dispatch, now mode-aware.

---

## 3. The intra-org directive protocol (light path)

Same Contract object and state machine as `design.md` §3 — but the "standing
agreement" is **role authority**, and well-formed directives are **pushed
pre-accepted** instead of negotiated.

### 3.1 Directive guard

```python
def is_directive(directing_role, supplier_role, work, frontier) -> bool:
    return (
        supplier_role in directing_role.authority.may_direct
        and work.domain in supplier_role.mandate_scope.domains
        and work.stakes <= supplier_role.mandate_scope.max_stakes_auto
        and work.est_tokens <= spend_remaining(directing_role)   # ceiling − consumed-this-period (§7)
        and all(t.predicate(work) for t in supplier_role.mandate_scope.hard)   # report's role reservations
        and personal_hard_terms_ok(supplier_human, work)                       # report's PERSONAL reservations
        and frontier.band(sig(work)) != "ASK_ALWAYS"                            # learned: still ask here
    )
```

- **True** → the directing role creates the contract directly in `ACCEPTED`
  (supplier signature = standing role-consent), skipping `PROPOSED/COUNTERED`.
  The supplier node activates it (EO check passes: supplier_role ∈ self.roles).
- **False** → fall back to the negotiated path (`PROPOSED`): out-of-mandate,
  over-ceiling, high-stakes, hard-term, or `ASK_ALWAYS` work requires the
  report's proxy or human to sign, **even inside the org.** Directive authority
  is bounded by the report's reservations and learned risk band — it is not
  absolute.

### 3.2 Authority primitives org-hierarchy adds (beyond contracts)

New events on the state machine, guarded by `may_direct`, available only
intra-org to a directing role over a supplier role it controls:

| Event | Effect | Guard |
|---|---|---|
| `REPRIORITIZE(contract, priority)` | reorder a supplier's queued/active contracts | `supplier_role ∈ may_direct` |
| `REASSIGN(contract, new_supplier_role)` | move work to another controlled role-slot; old doer checkpoints (WITHDRAWN-with-handoff artifact) and work re-dispatches | both roles ∈ may_direct |
| `PREEMPT(contract)` | pull a doer to free capacity; contract → AMENDING (parked) | `supplier_role ∈ may_direct` |

All three respect the report's hard reservations: a report may still refuse and
escalate up the `parent` chain if a primitive would violate a personal/role hard
term.

### 3.3 Intra-org deadlock

A report's refusal that the directing role cannot resolve escalates **up the
`parent` chain** to the first role with authority to decide (a human manager).
Unlike the engagement boundary, intra-org deadlock has a resolver — the hierarchy
— so it does not page peers; it surfaces to the manager's decision queue.

---

## 4. Intra-org membrane

The `design.md` §4 transport, hosted on a branch of the **org-definition repo**
(`membrane/…`), shared by the org's nodes. All §4 mechanics apply unchanged:
conflict-free unique-file inboxes, ULID ordering/idempotency, event-sourced
contract state, and **AUTH against the GitHub commit author** resolved through
the org's own `members/` + `keys/`. Intra-org messages never leave the org repo.

---

## 5. Cross-org engagement membrane (resolves model.md deferred #3)

Two orgs are two repos; an engagement needs a space both can write to.
**Decision: a dedicated partnership repo per org-pair** (named in
`partnerships/<org>.yaml:engagement_space`), with write access for both orgs'
relevant nodes. Chosen over cross-repo issues/PRs because it reuses the §4
conflict-free branch model verbatim, with clean repo-level access control and a
durable home for the agreement + engagement contracts + exchanged artifacts.

### 5.1 Partnership repo layout

```
agreement.yaml                         # the dual-signed standing agreement (mirror of both orgs')
keys/<org_id>/<human_id>.pub           # each org publishes its representatives' keys here
inbox/<org_id>/<node_id>/<ulid>.json   # cross-org messages, org+node addressed
contracts/<engagement_id>/<n>.json     # engagement contract snapshots
artifacts/<engagement_id>/…            # deliverables exchanged across the boundary
acks/<org_id>/<node_id>/<ulid>
```

### 5.2 Establishing a partnership (the one genuinely heavy negotiation)

1. A representative of Org A creates (or is granted) the partnership repo and
   grants Org B's representative write access.
2. Each org **publishes its members' public signing keys** (`keys/<org>/…`),
   attested by its own org-definition repo (the partner reads A's `keys/` from
   A's org repo or the mirror). This bootstraps cross-org identity.
3. The standing agreement is drafted and negotiated via the full
   `design.md` §3 CfA (human representatives in the loop) and **dual-signed**
   (both signatures on one `version_hash`) into `agreement.yaml`. Lanes,
   budgets, and `coi_policy` are set here.
4. Thereafter engagements flow as contracts under the lanes — mostly
   proxy-auto-signed where they fit (§3-style fit checks, but at org+role scope).

### 5.3 Cross-org AUTH (generalizes design.md §4.4)

The trust anchor is still the GitHub commit author. For a **partner** message,
the key→holder mapping comes from **the partner org's published registry**, not
the local roster:

```python
def ingest_cross_org(msg, commit, partner_org):
    holder = partner_org.roster.holder_of(msg.acting_as_role)      # from partner's members/
    key    = partner_org.keys.get(holder)                          # from partner's keys/
    if commit.author_key != key:               return DROP("auth: author≠partner role holder")
    if not partner_org.binds(holder, msg.acting_as_role):          # role still held?
                                               return DROP("auth: role no longer held")
    if not agreement.lane_allows(msg):         return DROP("auth: outside any signed lane")
    apply(msg)
```

A partner can only act under a role its own current roster binds, only within a
signed lane, and only with its published key. Membership/role changes on either
side take effect through the normal PR-reviewed roster update + key publication.

### 5.4 Cross-org execution-owner

EO (`design.md` §7) holds across the boundary unchanged: a DOER binding across
the org line means the **supplier org's node runs it on the supplier human's
account**. Org A never runs Org B's work. Engagement activation dispatches only
on a node whose `roles` include the contract's `supplier` role; the supplier-side
conformance test (`design.md` §7) covers cross-org messages identically.

---

## 6. Conflict of interest (resolves model.md deferred #2)

A single human may hold roles on both sides of an engagement (§13.2). Detection
runs at proposal and at every `REASSIGN`:

```python
def coi_check(contract) -> COIResult:
    req_humans = {b.human for b in contract.bindings if b.org == contract.requester_org}
    sup_humans = {b.human for b in contract.bindings if b.org == contract.supplier_org}
    overlap = req_humans & sup_humans
    if not overlap: return OK
    severe = any(b.carries_execution or b.participation in ("DECIDER",)  # signer/doer conflict
                 for h in overlap for b in contract.bindings if b.human == h)
    return COIResult(humans=overlap, severe=severe)
```

- **`coi_policy: flag` (default):** record the COI on the contract, surface to
  both representatives, proceed.
- **`coi_policy: block`:** if `severe` (the conflicted human is a doer or a
  signer/decider on the engagement), refuse activation until that binding is
  reassigned to a non-conflicted role-holder.

---

## 7. Quota across roles

- `quota.weekly_token_cap` is the human's **hard** global cap (`design.md` §6.4):
  a node refuses to **activate** any contract that would breach it, regardless of
  role or org.
- `quota.allocation[role]` are **soft** sub-caps. A doer turn consumes from the
  allocation of its `acting_as_role`. The runner tags every turn
  `(human, role, contract, initiative|engagement)`; consumption is summed per
  role. A soft sub-cap breach escalates to the human (throttle / reallocate); the
  global cap stays hard.
- Reallocation is a human act (edit `members/<id>.yaml`), PR-reviewed if org
  policy requires. Consumption is surfaced per role/engagement so a human can see
  who is leaning on their quota and rebalance.

---

## 8. Acting-context & role-aware delegate-memory

Every dispatch and membrane message carries `acting_as_role` + `org`. Two effects:

- **Mandate assembly** (`design.md` §3.2) selects hard/soft terms scoped to that
  role: `mandate = personal_hard ∪ role.mandate_scope.hard ∪ lane_terms`, soft
  defaults from the role + learned bands.
- **Delegate-memory** (`design.md` §5) extends the decision signature with a
  `role` feature dimension (onehot in `feat`, §5.2) so precedent retrieval and
  the risk frontier are **role-contextualized** — the proxy learns that the human
  decides differently as `eng_lead` than as `security_advisor`. The memory store
  stays per-human and private; role is just another retrieval key.

---

## 9. Bootstrapping & node identity

On startup a node:

1. Clones/pulls the org-definition repo(s) for each org the human belongs to and
   reads its `members/<self>.yaml` → human id, roles, orgs, signing key, quota.
2. Verifies its own `signing_key_ref` matches its GitHub commit-author key.
3. Instantiates a **proxy + delegate-memory** (per-human) and per-(org, role)
   `AskQuestionRunner`s.
4. Begins polling each org's intra-org membrane branch and each partnership
   inbox addressed to its orgs (`endpoint: dispatch` nodes also subscribe to
   `repository_dispatch` wakes).
5. Rebuilds in-flight contract state by folding inbox events over the latest
   snapshots (`design.md` §4.3).

---

## 10. Failure & recovery

| Failure | Detection | Response |
|---|---|---|
| Doer node offline | `HEARTBEAT_S` miss / `CONTRACT_SLA_GRACE × wall_p90` elapsed on `ACTIVE` | intra-org: `REASSIGN` to another `may_direct` role; engagement: `AMENDING`→counter or `withdraw`+reroute |
| Partial push | append-only disjoint paths | safe; fetch→rebase→retry (`design.md` §4.3) |
| Concurrent amendments | snapshot version mismatch | second amendment is stale → rebase its counter against latest, or reject |
| Intra-org deadlock | report refusal unresolved | escalate up `parent` chain to a deciding manager (§3.3) |
| Engagement deadlock | hard-term clash, uncounterable | `DEADLOCKED`, page both representatives (`design.md` §3.4) |
| Partner unreachable / partnership revoked | inbox stale / `agreement` retracted | in-flight: SLA timeout → `AMENDING`/`withdraw`; new requests rejected with reroute |
| Crashed mid-execution worktree | existing `workspace/recovery.py` | resume or checkpoint-and-reassign |

---

## 11. Observability

No centralized executor → no centralized dashboard. Each node runs the existing
bridge over its **own** orgs' membranes, rendering its roles, contracts, queues,
and per-role quota. The **partnership repo** gives both orgs a shared,
symmetric engagement view (each renders it from the same data). An initiative
**operating picture** is assembled by the initiative decider's node from the
intra-org membrane (org-private). Cross-org visibility is exactly what the shared
partnership repo exposes — nothing more.

---

## 12. Mapping to existing TeaParty code

| Existing | Role here |
|---|---|
| recursive dispatch (uber/subteam) | §2.4, now mode-aware (directive vs engagement) |
| `cfa/` + `cfa/gates/` | Contract machinery at every level; directive guard wraps the gate |
| `config/roster.py`, `util/role_enforcer.py` | §1 structure: roles, memberships, DAI, AUTH |
| `messaging/conversations.py` | local bus (intra-node); membrane branches are §4/§5 |
| `proxy/*`, `learning/*` | per-human delegate-memory (private) + org-internal norms (shared) split |
| `workspace/recovery.py`, heartbeat | §10 recovery / reassignment |
| `bridge/*` | §11 per-node observability |
| `telemetry/*` | §7 per-role consumption + cost priors |

---

## 13. Closed decisions (the previously open list)

1. **Matrix depth** — structure is a **graph** (functional hierarchy + team
   composition); initiatives staff cross-functionally (§1.5, §2.1). Done, not
   deferred.
2. **Multi-org / multi-role humans** — supported: membership is many-to-many,
   every binding carries `acting_as_role`, quota splits per role with a hard
   global cap (§1.4, §2.3, §7, §8).
3. **Conflict of interest** — `flag` by default, `block` (severe only)
   configurable per partnership (§6).
4. **Engagement-space mechanics** — a **dedicated partnership repo** per org-pair
   reusing the §4 branch model; partnership bootstrap + cross-org AUTH specified
   (§5).
5. **Org administration** — `admin_model` field; `enterprise_seats` (org-managed
   seats, recommended for multi-human orgs) vs `individual_accounts`; affects only
   how membership/keys are administered, not the protocol (§1.1).
6. **Standing-agreement attachment** — **org + role**, not individuals (§1.6);
   survives rotation.
7. **Policy predicate grammar** — finalized: comparisons (`==,<=,>=,<,>`), set
   membership (`in`) with globs, boolean (`all,any,not`), time (`window`,
   `now±Nh`), and **one** level of aggregation (`count`, `sum`) over scope/lane
   lists (e.g. "≤ N scopes", "Σ lane spend ≤ X"). No general arithmetic.
8. **Membrane dialog depth** — human escalation **dialog lives on the PR/issue**
   (audit trail, contestability); machine handoffs on the inbox; batch to manage
   rate (`design.md` §4.6).
9. **Snapshot GC** — contracts retained indefinitely as the audit record, moved
   to `contracts/archive/` `ENGAGEMENT_ARCHIVE_GRACE_DAYS` after `FULFILLED`;
   acked inbox files **tombstoned** (git-rm in a compaction commit, history
   preserved) after `INBOX_RETENTION_DAYS`. History is an append-only audit log;
   nodes needing only current state may shallow-clone.
10. **Embedding provider** — pluggable; defaults to the org-configured learning
    provider; degrades to lexical (minhash) when absent; `feat` reason-slice
    width is tunable (`design.md` §5.2).

---

## 14. Glossary

- **Organization** — durable institution; org-definition repo is its identity.
- **Role** — durable seat with authority + mandate scope; filled by a human/agent.
- **Membership** — human↔role, many-to-many; a human *acts as* one role per binding.
- **Team** — durable unit (its doers); recursive; substructure from the org.
- **Initiative** — internal work; a matrixed projection of structure (directive).
- **Engagement** — cross-org work; a contract under a partnership (negotiated).
- **DAI binding** — Decider/Advisor/Informed/(Doer) participation around work;
  only the doer carries execution.
- **Principal** — human + proxy + node + account; the execution/accountability unit.
- **Standing agreement** — durable org-pair partnership; lanes = scope-grants+budgets.
- **Mandate** — `personal_hard ∩ role authority`; the proxy's signing authority.
- **Membrane** — the git-hosted message layer; intra-org (org repo) or cross-org
  (partnership repo); carries information freely and execution never.
