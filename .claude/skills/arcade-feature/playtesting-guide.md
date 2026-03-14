# Playtesting Guide

Automated tests verify logic. Playtesting verifies feel. Both are required. A feature that passes all tests but feels wrong has failed — arcade games are feel-first.

---

## Before You Start

- Clear any cached/compiled assets so you are testing fresh code
- Have the spec open for reference — you are verifying against the spec, not against vibes
- If possible, have an arcade longplay video open for visual comparison

## Session 1: Feature in Isolation

Play through the feature's lifecycle 3 times, focusing only on the new feature:

**Visual**
- Are proportions correct relative to the player (1-tile unit)?
- Does movement speed look right compared to entities in adjacent lanes?
- Do animations transition cleanly between states?
- Is draw order correct? (Nothing rendering above/below where it shouldn't)

**Behavioral**
- Does the feature spawn at the right time, position, and frequency?
- Does collision work from all approach directions?
- Does scoring award the correct points?
- Does the feature's death/destruction/collection look correct?
- Does the feature wrap or despawn at screen edges as specified?

**Timing**
- Does the feature's rhythm match the game's existing rhythm?
- Do spawn intervals feel natural alongside existing entity patterns?
- Are animation durations consistent with other entities' animations?

## Session 2: Interactions

Play scenarios that combine the feature with other game systems:

- Feature spawns during player death animation — does it behave correctly?
- Player collects/contacts feature at the exact moment timer expires
- Feature is active during level transition — what happens?
- Feature overlaps spatially with another entity — correct draw order and collision priority?
- Multiple features active simultaneously (if applicable) — do they interact correctly?
- Player ignores the feature entirely for a full game — does it clean up properly?

## Session 3: Regression

Play the full game from start to game-over, deliberately NOT engaging with the new feature:

- Do existing entity speeds feel the same?
- Do existing spawn patterns feel the same?
- Do existing collisions work the same?
- Does scoring for existing interactions work correctly?
- Does level progression work correctly?
- Does the game feel the same as before, except for the addition?

## What "Feels Wrong" Means

When something feels wrong but you can't articulate why, check these in order:

1. **Speed**: Is the entity 10-20% too fast or too slow? Small speed errors are the most common source of vague wrongness.
2. **Proportions**: Is the entity slightly too large or too small relative to the player?
3. **Timing**: Is a state transition happening too quickly or lingering too long?
4. **Position**: Is the entity spawning a few pixels off from where it should be?
5. **Rhythm**: Is the entity's spawn pattern out of sync with the game's natural beat?

If the feeling persists and you can't pin it down, compare side-by-side with arcade footage at 0.25x speed.

## Recording Results

Note any issue with:
- **What you observed** (not what you think the cause is)
- **What the spec says should happen**
- **Steps to reproduce** (starting state, player actions, result)
- **Severity**: blocks (game-breaking), degrades (feels wrong), cosmetic (looks wrong but plays right)
