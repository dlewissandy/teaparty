# Integration Checklist

Every arcade game feature touches the game through specific seams. This checklist ensures nothing is missed during architecture planning (Phase 3) and wiring (Phase 4).

---

## Spawn Integration

- [ ] Where in the game loop is the feature instantiated?
- [ ] What triggers the spawn? (Lane timer, game event, level start, random interval)
- [ ] Is spawn level-dependent? If so, is the level config updated?
- [ ] What limits apply? (Max active count, cooldown between spawns, zone exclusion)
- [ ] What happens if the spawn condition is met but the limit is reached?

## Update Integration

- [ ] Where in the update tick does the feature's logic run?
- [ ] Does it update before or after collision detection?
- [ ] Does it update before or after other entities in the same lane?
- [ ] Does order-of-update matter? (Usually yes for movement + collision)
- [ ] Does the feature update when the game is paused? (Usually no)
- [ ] Does the feature update during player death animation? (Check spec — often yes for lane objects, no for bonus items)

## Collision Integration

- [ ] What entities does this feature collide with?
- [ ] For each collision pair: what is the detection shape? (Bounding box, circle, pixel-perfect, inset box)
- [ ] For each collision pair: what is the response? (Player dies, score awarded, feature destroyed, state change, bounce)
- [ ] Are there sub-regions with different collision behavior? (e.g., crocodile body is safe, mouth is lethal)
- [ ] Is the collision handler registered in the collision system?

## Rendering Integration

- [ ] What draw layer does the feature render on?
- [ ] Does it render above or below the player when in the same lane?
- [ ] Does it render above or below other entities in the same lane?
- [ ] Does it have multiple visual states? (Idle, active, dying, collected)
- [ ] Are animations frame-counted or time-based? (Match existing convention)
- [ ] Does it need a HUD indicator? (Score popup, status icon, counter)

## Scoring Integration

- [ ] Is the scoring system updated with new point values?
- [ ] Are score popups displayed at the correct position?
- [ ] Does the score cap (if any) still apply?
- [ ] Are bonus conditions documented and implemented?

## Level Progression Integration

- [ ] Is the feature present on all levels or only some?
- [ ] Does speed/frequency/behavior change per level?
- [ ] Is the level config data structure updated?
- [ ] What happens at level transition while the feature is active? (Destroyed? Persists? Resets?)

## Lifecycle Integration

- [ ] What destroys the feature? (Screen edge, timer, collection, level end)
- [ ] Is cleanup complete? (Removed from entity list, collision registry, render queue)
- [ ] What happens to the feature when the player dies?
- [ ] What happens to the feature on game over?
- [ ] What happens to the feature on game restart?

## Regression Surface

- [ ] List every existing file modified by this feature
- [ ] For each: what existing behavior could break?
- [ ] Are existing entity speeds unchanged?
- [ ] Are existing spawn rates unchanged?
- [ ] Are existing collision behaviors unchanged?
- [ ] Does the game still run correctly if the feature never spawns?
