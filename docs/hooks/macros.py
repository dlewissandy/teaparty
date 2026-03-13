"""MkDocs macros hook — computes live project statistics at build time."""

import os
from pathlib import Path


def define_env(env):
    """Define variables available in all markdown pages as {{ var_name }}."""
    projects_dir = Path(env.project_dir) / "projects"

    # Count project directories (exclude dotfiles, .gitignore, MEMORY.md, etc.)
    project_dirs = sorted(
        p.name
        for p in projects_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ) if projects_dir.exists() else []

    # Count total sessions across all projects
    total_sessions = 0
    project_session_counts = {}
    for proj in project_dirs:
        sessions_dir = projects_dir / proj / ".sessions"
        if sessions_dir.exists():
            count = sum(1 for s in sessions_dir.iterdir() if s.is_dir())
            project_session_counts[proj] = count
            total_sessions += count

    # Categorize projects by examining names
    categories = {
        "Software": [],
        "Research & papers": [],
        "Game development": [],
        "Writing & documentation": [],
        "Other": [],
    }

    research_keywords = {"paper", "publication", "research", "memory", "cfa", "reasoning"}
    game_keywords = {"game", "arcade", "frogger"}
    writing_keywords = {"guide", "powerpoint", "doc"}
    infra_keywords = {"poc", "ui", "ux", "portability", "server", "explorer",
                      "factorization", "stock", "mandelbrot"}

    for proj in project_dirs:
        name_lower = proj.lower().replace("-", " ")
        sessions = project_session_counts.get(proj, 0)

        if any(k in name_lower for k in game_keywords):
            categories["Game development"].append((proj, sessions))
        elif any(k in name_lower for k in research_keywords):
            categories["Research & papers"].append((proj, sessions))
        elif any(k in name_lower for k in writing_keywords):
            categories["Writing & documentation"].append((proj, sessions))
        elif any(k in name_lower for k in infra_keywords) or proj == "POC":
            categories["Software"].append((proj, sessions))
        else:
            categories["Other"].append((proj, sessions))

    projects_with_sessions = sum(1 for c in project_session_counts.values() if c > 0)

    # Expose to templates
    env.variables["project_count"] = len(project_dirs)
    env.variables["projects_with_sessions"] = projects_with_sessions
    env.variables["total_sessions"] = total_sessions
    env.variables["poc_sessions"] = project_session_counts.get("POC", 0)
    env.variables["project_categories"] = categories
    env.variables["project_session_counts"] = project_session_counts
