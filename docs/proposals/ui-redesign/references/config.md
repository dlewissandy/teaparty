[UI Redesign](../proposal.md) >

# Config Manager

Organizational hierarchy management. Two levels: global catalog and project assembly.

Mockup: [mockup/config.html](../mockup/config.html)

---

## User Stories

### "I want to set up a new project."
From the home page, click "+ New Project" → Office Manager chat opens. Describe the project ("non-fiction book about tea history"). The office manager assembles it: picks workgroups from the catalog (Editorial, Writing, Research), generates a project lead from template, assigns humans. The project appears on the home page.

### "I want to see what's in my project."
From the home page, click "Config" on a project card. The project config page shows everything assembled: workgroups (tagged `shared` or `local`), agents (tagged `generated`, `shared`, or `local`), participants (Manager, Proxy, humans with D-A-I roles), artifacts, skills, hooks, scheduled tasks.

### "I want to add a shared workgroup to my project."
On the project config, click "+ Catalog" on the Workgroups card. An Office Manager chat opens. "Add the Editorial workgroup to this project." The office manager references the org-level Editorial definition and adds it as a shared workgroup.

### "I want to customize a shared workgroup for this project."
The workgroup shows `shared` badge. Tell the office manager: "Override the Editor's model to opus for this project." The workgroup now shows `shared` + `norms overridden` badge. The override is stored in the project config, not the org definition.

### "I want to add a bespoke agent to my project."
On the project config, click "+ New" on the Agents card. Office Manager chat opens. "Add a Historian agent — opus model, read-only tools, specialist in primary sources." The agent appears tagged `local`.

### "I want to see the org-wide catalog."
Open Global Config (from home org row or project config breadcrumb). Shows the org catalog: all workgroup definitions, agent definitions, skill definitions. These are the building blocks projects assemble from.

### "I want to browse project documentation."
On the project config, the Artifacts card shows sections from `project.md`. Click any section to open the Artifacts viewer.

---

## Global Config

The org catalog. Everything defined here is available for projects to reference.

**Cards:**
- **Projects** — click to drill into project config
- **Workgroup Catalog** — org-level team definitions (Coding, Editorial, etc.)
- **Agent Catalog** — org-level agent definitions (Office Manager, Auditor, etc.)
- **Participants** — Office Manager + humans with D-A-I roles
- **Artifacts** — links to `organization.md` in the Artifacts viewer
- **Skill Catalog** — org-level skill definitions
- **Hooks** — org-level hooks
- **Scheduled Tasks** — org-level cron jobs

All "+ New" buttons open an Office Manager chat.

## Workgroup Config

Three-level navigation: Global Config → [Project →] Workgroup Name. Clicking a workgroup item in either the global catalog or a project's workgroup list drills into the workgroup detail view.

**Cards:**
- **Agents** — list with name, role, model; "+ New" and "+ Catalog" open OM chat
- **Skills** — list with name; "+ New" and "+ Catalog" open OM chat
- **Norms** — read-only; rules grouped by category heading; no add button (OM-driven)
- **Budget** — read-only key/value display; card hidden if budget is empty (OM-driven)

Breadcrumb links back to the parent level (Global Config or Project Config).

Org-level workgroups: Global Config → Workgroup.
Project-scoped workgroups: Global Config → Project → Workgroup.

## Project Config

Assembled from the catalog, customized locally.

**Cards:**
- **Workgroups** — tagged `shared`/`local`, override indicators. Two buttons: "+ New" (create local), "+ Catalog" (pull from org)
- **Agents** — tagged `generated`/`shared`/`local`. Same two buttons.
- **Participants** — Manager, Proxy, Humans (D-A-I roles). Click any to open chat.
- **Artifacts** — sections from `project.md`, click to open Artifacts viewer
- **Skills** — tagged `shared`/`local`. Same two buttons.
- **Hooks** — project-scoped only. "+ New" button.
- **Scheduled Tasks** — project-scoped only. "+ New" button.

Breadcrumb links back to Global Config.

---

## Source Tags

Every item in the project config is tagged by source:

| Tag | Meaning | Visual |
|-----|---------|--------|
| `shared` | From org catalog | Green badge |
| `local` | Defined only in this project | Purple badge |
| `generated` | Auto-created from template (project lead) | Yellow badge |
| `missing` | Declared in `project.yaml skills:` but not installed in org catalog | Red badge |

Shared items may have **override indicators** (e.g., "norms overridden") showing where the project diverges from the org definition.

---

## Controls

| Control | Action |
|---------|--------|
| Click project in Projects card | Drill down to project config |
| Click workgroup item | Drill down to workgroup detail (agents, skills, norms, budget) |
| Click "+ New" | Opens Office Manager chat for creation |
| Click "+ Catalog" | Opens Office Manager chat for catalog selection |
| Click participant | Opens participant chat |
| Click artifact section | Opens Artifacts viewer for this project |
| Click breadcrumb "Global Config" | Returns to global config |
| Click breadcrumb project name | Returns to project config (from workgroup detail) |
