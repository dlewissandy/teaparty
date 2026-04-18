# Artifact Page

The artifact browser and the job screen are the same page, parameterized by mode and chat-blade launch location. There is one implementation: `teaparty/bridge/static/artifact-page.js`.

## Modes

- **Browse mode** (`artifacts.html`): file tree scoped to the project repo, no top strip, chat blade rooted on configuration-lead at the project root.
- **Job mode** (`job.html`): file tree scoped to the job worktree, top strip with original request + workflow bar + changed/all toggle, chat blade rooted on the project lead in the job's worktree.

## Architecture

```
artifacts.html  ──┐
                   ├──> ArtifactPage.mount(config)  [artifact-page.js]
job.html       ──┘       ├── File tree with git-status indicators
                          ├── File viewer (markdown, code, images, PDFs)
                          ├── Live refresh (polls /api/git-status every 2s)
                          ├── AccordionChat blade (#400 shared chat UX)
                          └── Job-mode top strip (workflow-bar.js)
```

Both HTML files are thin shells (~30 lines) that import `artifact-page.js` and call `ArtifactPage.mount()` with mode-specific config. The `config` object carries DOM-element references (`contentEl`, `breadcrumbEl`, `bladeEl`) in addition to mode settings; there is no separate `container` positional argument. No rendering, state, or event-handling code lives in the shells.

## Server Endpoints

- `GET /api/git-status?path=<worktree>` — returns `{files: {relative_path: status}}` where status is `new`, `modified`, or `deleted`.

## Dependencies

- `accordion-chat.js` (#400) — shared chat UX
- `workflow-bar.js` — shared workflow bar (extracted from index.html)
- `breadcrumb.js` — shared breadcrumb helper
