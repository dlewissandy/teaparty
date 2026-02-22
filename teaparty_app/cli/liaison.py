"""CLI for liaison agents to relay tasks to workgroup sub-teams.

Usage:
    python -m teaparty_app.cli.liaison relay-to-subteam --message "..." [--job-id ID]

Environment variables (injected by project team session):
    TEAPARTY_PROJECT_ID    - The parent project ID
    TEAPARTY_WORKGROUP_ID  - The target workgroup ID
    TEAPARTY_ORG_ID        - The organization ID
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from sqlmodel import Session

from teaparty_app.db import engine
from teaparty_app.models import Conversation, Job, Organization, Project, Workgroup
from teaparty_app.services.agent_workgroups import agents_for_workgroup
from teaparty_app.services.liaison import (
    create_subteam_job,
    materialize_workgroup_files_sync,
    resolve_team_params,
    run_subteam,
    sync_directory_to_files,
)


ADMIN_AGENT_SENTINEL = "Workgroup administration assistant"


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(json.dumps({"error": f"Missing environment variable: {name}"}))
        sys.exit(1)
    return val


def cmd_relay_to_subteam(args: argparse.Namespace) -> None:
    """Relay a message to a workgroup sub-team.

    On first call (no --job-id): creates a Job + Conversation, runs the sub-team.
    On subsequent calls (with --job-id): sends a follow-up to the existing sub-team.
    """
    project_id = _env("TEAPARTY_PROJECT_ID")
    workgroup_id = _env("TEAPARTY_WORKGROUP_ID")
    org_id = _env("TEAPARTY_ORG_ID")
    message = args.message

    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            print(json.dumps({"error": "Project not found"}))
            sys.exit(1)

        workgroup = session.get(Workgroup, workgroup_id)
        if not workgroup:
            print(json.dumps({"error": "Workgroup not found"}))
            sys.exit(1)

        org = session.get(Organization, org_id)
        org_files = org.files if org else []

        # Get or create the job
        if args.job_id:
            job = session.get(Job, args.job_id)
            if not job:
                print(json.dumps({"error": "Job not found"}))
                sys.exit(1)
            conversation = session.get(Conversation, job.conversation_id)
            if not conversation:
                print(json.dumps({"error": "Job conversation not found"}))
                sys.exit(1)
        else:
            job, conversation = create_subteam_job(
                session, project_id, workgroup_id, message,
            )
            session.commit()
            session.refresh(job)
            session.refresh(conversation)

        # Get workgroup agents (non-admin)
        all_agents = agents_for_workgroup(session, workgroup_id)
        agents = [a for a in all_agents if a.description != ADMIN_AGENT_SENTINEL]
        agents.sort(key=lambda a: a.created_at)

        if not agents:
            print(json.dumps({
                "job_id": job.id,
                "status": "error",
                "summary": "No agents in workgroup",
            }))
            return

        # Resolve team parameters
        params = resolve_team_params(project, workgroup)

        # Materialize files
        dir_path, original_file_ids = materialize_workgroup_files_sync(
            session, workgroup, conversation,
        )

        try:
            # Run the sub-team
            summary = run_subteam(
                session=session,
                job=job,
                conversation=conversation,
                workgroup=workgroup,
                agents=list(agents),
                message=message,
                params=params,
                working_dir=dir_path,
                org_files=org_files,
            )

            # Sync files back
            sync_directory_to_files(
                session, workgroup, conversation, dir_path, original_file_ids,
            )

            # Mark job completed
            from teaparty_app.models import utc_now
            job.status = "completed"
            job.completed_at = utc_now()
            session.add(job)
            session.commit()

            print(json.dumps({
                "job_id": job.id,
                "status": "completed",
                "summary": summary,
            }))

        finally:
            # Clean up temp directory
            shutil.rmtree(dir_path, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m teaparty_app.cli.liaison",
        description="Liaison CLI for relaying tasks to workgroup sub-teams",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("relay-to-subteam", help="Relay a task to a sub-team")
    p.add_argument("--message", required=True, help="Task description or follow-up message")
    p.add_argument("--job-id", default=None, help="Existing job ID for follow-up calls")

    return parser


_COMMANDS = {
    "relay-to-subteam": cmd_relay_to_subteam,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = _COMMANDS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
