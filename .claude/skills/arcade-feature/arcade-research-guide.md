# Arcade Research Guide

How to find and evaluate information about classic arcade game behavior.

---

## Source Hierarchy

| Source Type | Reliability | What It Tells You | Watch For |
|-------------|------------|-------------------|-----------|
| ROM disassembly / MAME source | Definitive | Exact values: speeds, timings, state machines, scoring tables | Reading assembly requires domain knowledge; constants may be in hardware-specific units |
| Frame-by-frame footage analysis | High | Measured speeds, sprite dimensions, timing windows | Analyst may be working from a clone or modified ROM |
| Manufacturer documentation | High | Intended behavior, scoring, difficulty curves | May describe design intent rather than shipped behavior |
| Strategy guides (published books) | Medium-High | Scoring, spawn conditions, level progression | Written from player observation, not code analysis |
| Fan wikis (StrategyWiki, HG101) | Medium | General behavior, entity lists, level descriptions | Community-edited; errors propagate across wikis via copy |
| YouTube longplays | Medium | Visual reference for proportions, timing, feel | Video compression obscures pixel-level detail |
| Forum posts / Reddit | Low-Medium | Anecdotal observations, edge case reports | Unreliable for exact values; valuable for "did you know" behaviors |

## Search Strategies

**For exact numeric values** (speeds, timings, dimensions):
- `"$GAME" MAME source speed` or `"$GAME" disassembly constants`
- `"$GAME" frame data` or `"$GAME" hitbox data`
- Check the MAME source on GitHub directly: `github.com/mamedev/mame`

**For behavioral rules** (what happens when X):
- `"$GAME" mechanics guide`
- `"$GAME" StrategyWiki` — often the most complete single source
- `"$GAME" "$FEATURE" behavior` or `"$GAME" "$FEATURE" rules`

**For visual reference** (what it looks like):
- `"$GAME" arcade sprites` — look for sprite rips, not screenshots
- `"$GAME" sprite sheet` — raw assets extracted from ROM
- `"$GAME" longplay` on YouTube — watch at 0.25x speed for timing

**For disputed behaviors** (sources disagree):
- Check whether sources refer to different versions (Japanese vs. US release, different hardware revisions)
- Check MAME source for the specific ROM set — MAME often documents version differences
- When genuinely ambiguous, document both behaviors and flag for human decision

## Common Research Pitfalls

- **Wiki echo chambers**: One wiki gets a detail wrong, others copy it. Cross-reference against non-wiki sources.
- **Clone confusion**: Many "arcade" videos are actually MAME or fan remakes with subtly different behavior.
- **Version differences**: Arcade games often had multiple ROM revisions. The "correct" behavior may differ between the Japanese and US release.
- **Memory conflation**: Players remember a composite of multiple games in the same genre. "Frogger had power-ups" — no, that was a sequel or clone.
- **Spec-as-shipped gap**: What the designer intended and what shipped may differ. The shipped behavior is correct, even if it was a bug the players learned to exploit.
