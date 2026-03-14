---
name: arcade-feature
description: Implement a new feature in a game that behaves like an arcade classic. Use when adding a game mechanic, entity, system, or behavior that must be faithful to the original arcade cabinet.
argument-hint: [game-project] [feature-name]
user-invocable: true
---

# Arcade Feature Implementation

You are implementing a new feature in a game that recreates a classic arcade cabinet. The feature must feel right to someone who played the original. The game project is `projects/$0/`. The feature is `$1`.

Read the project first: `INTENT.md`, `CLAUDE.md`, `specification/`, and the source tree.

---

## Phase 1: Research

**Goal**: Know how this feature actually worked on the original cabinet.

Search for primary sources in this order of reliability:
1. ROM disassembly or MAME source analysis — ground truth
2. Frame-by-frame arcade footage analysis — measured observation
3. Manufacturer operator manuals — published reference
4. Fan wikis and strategy guides — community knowledge, verify claims

For each source, note what it claims, whether the claim is measured or assumed, and where sources disagree.

Cross-reference findings against `projects/$0/specification/`. Identify behaviors the spec covers correctly, incorrectly, or not at all.

Write `projects/$0/docs/$1-research.md`: sources (with URLs and reliability), confirmed behaviors, disputed behaviors, unknowns marked `[REQUIRES ESTIMATION]`, and interactions with existing game systems.

**Gate**: Do not proceed until research is complete. Coding against incomplete research produces features that must be rewritten.

---

## Phase 2: Specification

**Goal**: Translate research into a precise behavioral spec an implementer can follow without guessing.

Write or update the relevant file(s) in `projects/$0/specification/`. Cover:

- **Entity definition**: dimensions in tiles (the canonical unit), collision box, visual description
- **State machine**: every state, every transition, every trigger — drawn explicitly, not described narratively
- **Movement**: direction, speed in tiles/second, wrap vs. despawn at screen edges
- **Interactions**: contact with player, other entities, screen boundaries, game events (death, level up, timer)
- **Scoring**: point values for every scoreable interaction
- **Spawn rules**: trigger, frequency, limits, level dependency
- **Level progression**: how the feature changes across levels

Mark uncertainties: `[ESTIMATED — basis]` for derived values, `[REQUIRES VERIFICATION]` for unconfirmed values. Never present estimates as confirmed.

Validate against existing spec — row assignments, scoring, level progression must be consistent.

**Self-test**: Read the spec as the implementer. Can you implement every behavior without asking a clarifying question? If not, the spec is incomplete. The most common gap: happy path is specified, boundaries are not (off-screen, simultaneous events, timer-expired-during-animation).

---

## Phase 3: Architecture

**Goal**: Determine where the feature lives in the codebase and how it integrates.

Read the existing architecture: game loop, entity system, collision system, configuration, rendering pipeline. Then decide:

- **New files**: follow existing naming and directory conventions (entities in `entities/`, systems in `systems/`, config in `config/`)
- **Modified files**: identify the specific functions that change. Minimize the diff.
- **Integration points**: spawn (where instantiated), update (where in the tick, what order relative to collision), collision (what interactions, what handlers), render (what draw layer), lifecycle (what creates and destroys it)

Write `projects/$0/docs/$1-architecture.md`: file plan, integration points with function names, dependencies, and risk assessment (where is a bug most likely?).

---

## Phase 4: Implementation

**Goal**: Write the code. Logic first, then rendering, then wiring.

**Logic**: State machine, movement, spawn rules, scoring — as self-contained code that doesn't depend on the renderer. Speeds must match the spec: `speed_tiles_per_sec * tile_size * dt`.

**Rendering**: Follow the existing visual approach (procedural canvas or sprites). Match the draw layer, color palette, proportions, and animation style of existing entities.

**Wiring**: Connect to game loop, collision system, scoring, level config, and UI. Every integration point from Phase 3 must have corresponding code. Missing wiring is the most common "works in isolation, breaks in game" bug.

---

## Phase 5: Integration Testing

**Goal**: Verify the feature is correct and nothing else broke.

**Automated tests** (game logic, not rendering):
- State machine: every transition in the spec occurs; every transition not in the spec does not
- Movement: position after T seconds at speed Y matches expected value
- Spawn: timing, positioning, and limits enforced
- Collision: correct detection and response for every interaction in the spec
- Boundaries: screen edges, level transitions, timer expiry during animation, player death during interaction

**Playtesting** (rendering and feel):
- Play through the feature's lifecycle at least 3 times
- Visual: proportions, speed, animations, draw order all look correct
- Behavioral: spawns, collisions, scoring match the spec
- Interactions: test overlapping events (feature spawns during death, collection at timer expiry)
- Regression: play the game ignoring the new feature — does everything else still work?

---

## Phase 6: Polish

**Goal**: The feature should feel like it was always part of the game.

- **Timing**: spawn intervals, movement speed, and animation timing harmonize with existing game rhythm
- **Edge cases**: feature at screen edges, during level transition, during pause, during death animation, when window loses focus
- **Code quality**: matches existing naming conventions, code style, module patterns. Config values in config files, not hardcoded. No dead code.
- **Documentation**: update README if player-facing. If implementation deviated from spec, update the spec to match reality.
- **Final pass**: play start-to-game-over. The feature should feel native — removing it would leave a gap, not restore normalcy.

---

## Principles

- **The arcade cabinet is the spec.** Research documents what it does. The spec translates it. The code realizes it. Authority flows in one direction.
- **Measure, don't guess.** Speeds in tiles/second, dimensions in tiles, timing in seconds. Every number traces to a source or is explicitly marked as estimated.
- **Implement the spec, not your mental model.** If you need a state the spec doesn't have, update the spec first.
- **Integration points are the bug surface.** Test boundaries harder than interiors.
- **Feel is a requirement.** A feature that passes all tests but feels wrong has failed.
