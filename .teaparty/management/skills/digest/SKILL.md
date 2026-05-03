---
name: digest
description: Write findings to the team scratch hierarchy — broad-to-specific, no
  file over 200 lines, with in-progress/done status markers.
user-invocable: false
allowed-tools: Read, Write, Glob
---

# Digest

Write your findings to the team scratch hierarchy before signaling completion.

## Steps

1. **Read the index.** Open `scratch/index.md`. If it does not exist, create it. Identify whether a section for your role already exists.

2. **Write your section.** Add your findings under a heading named for your role (e.g., `## web-researcher`). Mark it `status: in-progress` at the top of the section.

3. **Keep files under 200 lines.** If your content would push the file past 200 lines, move the detail into a subtopic file (`scratch/<subtopic>.md`) and replace it in the parent with a one-line pointer: `See [subtopic](subtopic.md)`. The subtopic file must also stay under 200 lines.

4. **Organize broad-to-specific.** Lead with your conclusion or key finding. Put supporting detail below. A reader should be able to stop reading as soon as they have what they need.

5. **Mark done.** When your findings are complete, update the status marker to `status: done`.

6. **Do not modify other agents' sections.** Sections owned by other roles are read-only. If you see a conflict, note it at the bottom of your section — the lead resolves it at consolidation.

## Scratch structure

```
scratch/
  index.md          # broad summary + pointers; always under 200 lines
  <subtopic>.md     # detail file; also under 200 lines
```

The lead reads `scratch/index.md` first, drills into subtopic files only as needed, and resolves any conflicts before producing the final deliverable.
