# Federated Teams — The Organizational Model

**Status:** Conceptual model (authoritative) · **Spec:** [`design.md`](design.md)

This is the frame the detailed design hangs on. It replaces the earlier
"every human is their own organization" framing, which was wrong: it aligned the
account boundary with the institution boundary and made multi-human orgs
impossible. The corrected model keeps the federation + contract + delegate-memory
spine (in `design.md`) and adds the layer it was missing.

## Two metaphors, both first-class

Teamwork here draws on two hierarchical metaphors, and we need both:

- **Vertically-integrated organization** — many humans inside one institution,
  arranged in a hierarchy with directive authority and shared norms. (Internal
  *initiatives*.)
- **Distributed partnership** — separate organizations contracting at arm's
  length. (External *engagements*.)

The mistake to avoid: defining an org structure that is valid only for one
initiative or one engagement. **Organizations are durable and first-class; they
outlive any single piece of work** and participate in many initiatives and many
engagements over their lifetime. Standing agreements, accruing org norms, and an
org's external reputation all *presuppose* a durable org — so first-class orgs
aren't a nicety, they're load-bearing.

## Layer 1 — Structure (durable, authored once)

Changed only by deliberate, reviewed acts (a hire, a reorg, signing a
partnership) — never by starting work.

- **Organization** — a durable institution: identity, members, an internal
  hierarchy of teams, roles, norms, and an **org-mandate** (what the org will
  commit to, internally and externally). Home: an *org-definition repo*.
- **Team** — a durable unit within an org. **A team is its doers.** Recursive:
  team-of-one (base case) → team-of-entities-with-roles → team-of-teams. A team's
  substructure comes from the org, never from a project.
- **Role** — a durable *seat* in the structure, carrying authority and a mandate
  scope. Filled by a human or an agent. (This is where the "seat" abstraction
  belongs — at org-structure altitude, not in the per-decision loop.)
- **Membership** — **human ↔ role, many-to-many.** A human may hold several
  roles, across one or more orgs, and *acts under a specific role* in any given
  binding. Authority derives from the role; preferences from the human; the
  effective mandate is *personal hard limits ∩ role authority*.
- **Standing agreement** — a durable relationship between two orgs (the
  partnership book), persisting across engagements. **Attached to org + role,
  not to individuals**, so it survives personnel rotation.

## Layer 2 — Work (transient, binds to structure)

Work *references* structure for authority and staffing; it never defines it.

- **Initiative** — internal work an org undertakes. **A matrix**: it pulls in
  appropriate org teams and binds them with participation roles. Authority is
  sourced from the org hierarchy → **directive** (light ceremony).
- **Engagement** — cross-org work: a contract between orgs under their standing
  agreement. Authority is sourced from the org-mandates → **negotiated** (full
  membrane ceremony).

Both are *projections of durable structure onto a unit of work.* The same durable
team can be a **doer** in one initiative and an **advisor** in another — its
substructure is fixed, its participation role is per-work. That is matrix reality,
and it falls out for free.

## The wiring — DAI bindings

A team is its doers; **D / A / I (Decider, Advisor, Informed) are participation
bindings around a unit of work**, not team membership. They are sourced from
anywhere — in-team, elsewhere in the org, or another org. (The decider being
external to the executing team isn't an edge case; in CfA it's the normal shape.)

Four properties make this the load-bearing mechanism:

1. **Only the doer binding carries execution.** Account, the execution-owner
   invariant, quota, and cost attach to the doer alone. D/A/I are pure
   information flow — cheap, no execution-ownership, free to cross any boundary.
   So **the membrane carries information freely and execution never**, and the
   doer binding is the sole carrier of execution-ownership. This is the clean
   ToS boundary.
2. **Every binding is filled by an entity acting *under a role*** — authority and
   mandate from the role, identity and preferences from the human/agent.
3. **The decider binding is the escalation path, and where it lands sets the
   collaboration mode:**
   - decider in the same principal → **implicit** (the local CfA),
   - decider elsewhere in the same org → **directive**,
   - decider in another org → **negotiated contract**.
4. **A contract is the seam between an external WHAT-decider and a team's
   internal HOW-decider.** The external decider owns *what* the team commits to
   deliver; the team's internal decider owns *how* it executes. The contract is
   their interface (the liaison/context boundary), present at every level, heavy
   only when it crosses an org line. This is why the "two deciders" of a
   matrixed team are not in conflict.

## The federation spine (universal, orthogonal)

Underneath both layers, unchanged from the spec:

- **Account = human = node** (ToS). Every human runs their own CLI on their own
  account; work executes locally; no node ever runs another human's work.
- **The execution-owner invariant** (`design.md` §7) is the enforcement point.
- **Three durable knowledge scopes**, each with a different home and trust
  direction: **personal** (delegate-memory, per-human, private), **org-internal**
  (norms/procedures, per-org, accrues across initiatives), **relationship**
  (standing agreement + history, per org-pair, accrues across engagements).

## Recursion and graceful degeneracy

- **team-of-one** is the base case; a whole org is a team-of-teams. Each dispatch
  level is a CfA whose decider is the level above.
- **A one-person org** degenerates to a team-of-one whose decider binding points
  at itself — i.e. single-human TeaParty is the *n = 1* case of the same model,
  not a special mode.
- **The contract substrate is the general form**; intra-org (directive) and
  intra-principal (implicit) are its **high-trust degenerate cases**,
  distinguished only by which boundary the decider binding crosses. Nothing in
  the spec is thrown out — the spectrum is "how far up does the decider binding
  reach."

## Consequences of multiple roles

- **Quota:** one human, one account, one quota, split across their roles;
  attribution is per-role so the human can throttle.
- **Acting context:** every doer/decider/advisor binding records *which role* the
  entity is acting under; authority is evaluated against that role.
- **Conflict of interest:** when one human holds roles on both sides of an
  engagement, the system **flags** it rather than silently allowing it.

## First-class entities

Structure: **Organization, Team, Role, Membership, Standing-agreement,
Org-mandate.** Work: **Initiative, Engagement.** Wiring: **DAI binding** (with
the doer binding as the sole execution carrier). Spine: **Principal**
(human + proxy + node + account), **Contract**, **Delegate-memory**.

## Boundary → artifact map

| Boundary | Artifact |
|---|---|
| Account = human = node | local runtime, private (ToS) |
| Organization | org-definition repo (durable identity, members, hierarchy, roles, norms, mandate) |
| Initiative | workspace repo, references its org for authority + staffing |
| Engagement | cross-org space, anchored to both org repos + the standing agreement |

## Deferred decisions

1. **Matrix depth** — structure is at least a tree of teams; full matrix
   (cross-functional staffing across functional lines) can be layered on later.
   Confirmed: project teams *are* matrixed compositions of durable teams.
2. **Conflict-of-interest policy** — flag-only, or block? Start with flag.
3. **Engagement-space mechanics** — dedicated partnership repo vs. cross-repo
   issues/PRs (see `design.md` §4 / §12).
4. **Org-definition administration** — whether multi-human orgs map onto
   Anthropic Team/Enterprise seat semantics vs. individual accounts (affects how
   membership and node registration are administered).
