"""Workflow auto-selection helpers.

Extracted from the former agent_tools.py. These functions match new job
conversations against available workflow files and bootstrap state.
"""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from sqlmodel import Session

from teaparty_app.models import Conversation, Workgroup
from teaparty_app.services.file_helpers import (
    _normalize_workgroup_files,
    _topic_id_for_conversation,
)

logger = logging.getLogger(__name__)

_WORKFLOW_STATE_PATH = "_workflow_state.md"


def _extract_workflow_title_and_trigger(content: str) -> tuple[str, str]:
    """Extract the first ``# Title`` and ``## Trigger`` section from markdown."""
    title = ""
    trigger = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
        if stripped.startswith("## Trigger"):
            idx = content.index(stripped) + len(stripped)
            rest = content[idx:].strip()
            trigger_lines = []
            for tl in rest.splitlines():
                if tl.strip().startswith("## "):
                    break
                if tl.strip():
                    trigger_lines.append(tl.strip())
            trigger = " ".join(trigger_lines)[:200]
            break
    return title, trigger


def _build_initial_workflow_state(workflow_path: str, workflow_title: str, topic: str) -> str:
    """Return the initial ``_workflow_state.md`` content for a newly selected workflow."""
    return (
        f"# Workflow State\n"
        f"\n"
        f"- **Workflow**: {workflow_path}\n"
        f"- **Status**: pending\n"
        f"- **Current Step**: 1\n"
        f"\n"
        f"## Step Log\n"
        f"- [ ] 1. (pending)\n"
        f"\n"
        f"## Notes\n"
        f"- Auto-selected for job \"{topic}\"\n"
    )


def _match_workflow_to_job(
    session: Session,
    conversation_id: str,
    topic: str,
    description: str,
    workflows: list[dict[str, str]],
) -> str | None:
    """Use a cheap model to match a job name/description against workflow triggers."""
    from teaparty_app.services import llm_client
    from teaparty_app.services.llm_usage import record_llm_usage

    manifest_json = json.dumps(workflows)
    topic_text = topic
    if description:
        topic_text += f" -- {description}"

    try:
        model = llm_client.resolve_model("cheap", "haiku")
        start = time.monotonic()

        response = llm_client.create_message(
            model=model,
            max_tokens=256,
            system=(
                "You match a conversation job against available workflow triggers. "
                'Return strict JSON only: {"path": "<workflow path>", "confidence": <0.0-1.0>}. '
                'If no workflow is a good match, return {"path": null, "confidence": 0.0}.'
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Job topic: {topic_text}\n\n"
                        f"Available workflows:\n{manifest_json}\n\n"
                        "Which workflow best matches this job? Return JSON only."
                    ),
                }
            ],
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        record_llm_usage(
            session, conversation_id, None, model,
            response.usage.input_tokens, response.usage.output_tokens,
            "workflow_match", duration_ms,
        )

        text = response.content[0].text.strip()
        data = json.loads(text)
        path = data.get("path")
        confidence = data.get("confidence", 0.0)

        if path and confidence >= 0.3:
            valid_paths = {w["path"] for w in workflows}
            if path in valid_paths:
                return path
    except Exception:
        logger.debug("Workflow matching failed", exc_info=True)

    return None


def auto_select_workflow(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
) -> str | None:
    """Match a new job against available workflows and bootstrap state.

    Returns the selected workflow path, or None if no match.
    """
    # Only shared (non-job-scoped) files -- no job files exist yet
    all_files = _normalize_workgroup_files(workgroup)
    shared_files = [f for f in all_files if not f.get("topic_id")]
    workflows = [
        f for f in shared_files
        if f["path"].startswith("workflows/")
        and f["path"].endswith(".md")
        and f["path"] != "workflows/README.md"
    ]

    if not workflows:
        return None

    # Build manifest of {path, title, trigger} for each workflow
    manifest: list[dict[str, str]] = []
    for wf in workflows:
        content = wf.get("content") or ""
        title, trigger = _extract_workflow_title_and_trigger(content)
        manifest.append({
            "path": wf["path"],
            "title": title or wf["path"],
            "trigger": trigger,
        })

    if len(workflows) == 1:
        selected_path = manifest[0]["path"]
        selected_title = manifest[0]["title"]
    else:
        # Multiple workflows -- ask Haiku to pick the best match
        topic_text = (conversation.name or conversation.topic or "").strip()
        description = (conversation.description or "").strip()
        selected_path = _match_workflow_to_job(
            session, conversation.id, topic_text, description, manifest,
        )
        if not selected_path:
            return None
        selected_title = next(
            (m["title"] for m in manifest if m["path"] == selected_path),
            selected_path,
        )

    # Build and persist the initial state file
    topic_text = (conversation.name or conversation.topic or "").strip()
    state_content = _build_initial_workflow_state(selected_path, selected_title, topic_text)

    topic_id = _topic_id_for_conversation(conversation)
    all_files = _normalize_workgroup_files(workgroup)
    created = {
        "id": str(uuid4()),
        "path": _WORKFLOW_STATE_PATH,
        "content": state_content,
        "topic_id": topic_id,
    }
    all_files.append(created)
    workgroup.files = all_files
    session.add(workgroup)

    return selected_path
