"""CLI for coordinator agents to invoke orchestration tools.

Usage:
    python -m teaparty_app.cli.orchestrate <subcommand> [args]

Environment variables (injected by agent runtime):
    TEAPARTY_AGENT_ID      - The calling agent's ID
    TEAPARTY_WORKGROUP_ID  - The agent's workgroup ID
    TEAPARTY_ORG_ID        - The agent's organization ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from sqlmodel import Session

from teaparty_app.db import engine
from teaparty_app.services import orchestration


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(json.dumps({"error": f"Missing environment variable: {name}"}))
        sys.exit(1)
    return val


def cmd_browse_directory(args: argparse.Namespace) -> None:
    with Session(engine) as session:
        result = orchestration.browse_directory(session)
        print(json.dumps(result, indent=2))


def cmd_check_balance(args: argparse.Namespace) -> None:
    org_id = args.org_id or _env("TEAPARTY_ORG_ID")
    with Session(engine) as session:
        result = orchestration.check_balance(session, org_id)
        print(json.dumps(result, indent=2))


def cmd_propose_engagement(args: argparse.Namespace) -> None:
    agent_id = _env("TEAPARTY_AGENT_ID")
    with Session(engine) as session:
        result = orchestration.propose_engagement_by_agent(
            session,
            agent_id=agent_id,
            target_org_id=args.target_org_id,
            title=args.title,
            scope=args.scope or "",
            requirements=args.requirements or "",
        )
        if "error" not in result:
            session.commit()
        print(json.dumps(result, indent=2))


def cmd_respond_engagement(args: argparse.Namespace) -> None:
    agent_id = _env("TEAPARTY_AGENT_ID")
    with Session(engine) as session:
        result = orchestration.respond_engagement_by_agent(
            session,
            agent_id=agent_id,
            engagement_id=args.engagement_id,
            action=args.action,
            terms=args.terms or "",
        )
        if "error" not in result:
            session.commit()
        print(json.dumps(result, indent=2))


def cmd_set_price(args: argparse.Namespace) -> None:
    with Session(engine) as session:
        result = orchestration.set_engagement_price(
            session,
            engagement_id=args.engagement_id,
            price_credits=args.price,
        )
        if "error" not in result:
            session.commit()
        print(json.dumps(result, indent=2))


def cmd_create_job(args: argparse.Namespace) -> None:
    agent_id = _env("TEAPARTY_AGENT_ID")
    with Session(engine) as session:
        result = orchestration.create_engagement_job(
            session,
            agent_id=agent_id,
            team_name=args.team,
            title=args.title,
            scope=args.scope or "",
            engagement_id=args.engagement_id,
        )
        # commit happens inside create_engagement_job
        print(json.dumps(result, indent=2))


def cmd_list_team_jobs(args: argparse.Namespace) -> None:
    org_id = args.org_id or _env("TEAPARTY_ORG_ID")
    with Session(engine) as session:
        result = orchestration.list_team_jobs(
            session,
            org_id=org_id,
            team_name=args.team,
            status_filter=args.status,
        )
        print(json.dumps(result, indent=2))


def cmd_read_job_status(args: argparse.Namespace) -> None:
    with Session(engine) as session:
        result = orchestration.read_job_status(
            session,
            job_id=args.job_id,
            message_limit=args.messages or 10,
        )
        print(json.dumps(result, indent=2))


def cmd_post_to_job(args: argparse.Namespace) -> None:
    agent_id = _env("TEAPARTY_AGENT_ID")
    with Session(engine) as session:
        result = orchestration.post_to_job(
            session,
            agent_id=agent_id,
            job_id=args.job_id,
            message_content=args.message,
        )
        # commit happens inside post_to_job
        print(json.dumps(result, indent=2))


def cmd_complete_engagement(args: argparse.Namespace) -> None:
    agent_id = _env("TEAPARTY_AGENT_ID")
    with Session(engine) as session:
        result = orchestration.complete_engagement_by_agent(
            session,
            agent_id=agent_id,
            engagement_id=args.engagement_id,
            summary=args.summary or "",
        )
        if "error" not in result:
            session.commit()
        print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m teaparty_app.cli.orchestrate",
        description="Orchestration CLI for coordinator agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # browse-directory
    sub.add_parser("browse-directory", help="List orgs accepting engagements")

    # check-balance
    p = sub.add_parser("check-balance", help="Check org credit balance")
    p.add_argument("--org-id", default="")

    # propose-engagement
    p = sub.add_parser("propose-engagement", help="Propose a new engagement")
    p.add_argument("--target-org-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--scope", default="")
    p.add_argument("--requirements", default="")

    # respond-engagement
    p = sub.add_parser("respond-engagement", help="Accept or decline an engagement")
    p.add_argument("--engagement-id", required=True)
    p.add_argument("--action", required=True, choices=["accept", "decline"])
    p.add_argument("--terms", default="")

    # set-price
    p = sub.add_parser("set-price", help="Set agreed price for an engagement")
    p.add_argument("--engagement-id", required=True)
    p.add_argument("--price", required=True, type=float)

    # create-job
    p = sub.add_parser("create-job", help="Create a job for a team")
    p.add_argument("--team", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--scope", default="")
    p.add_argument("--engagement-id", default=None)

    # list-team-jobs
    p = sub.add_parser("list-team-jobs", help="List jobs in a team")
    p.add_argument("--team", required=True)
    p.add_argument("--org-id", default="")
    p.add_argument("--status", default=None)

    # read-job-status
    p = sub.add_parser("read-job-status", help="Read job details and messages")
    p.add_argument("--job-id", required=True)
    p.add_argument("--messages", type=int, default=10)

    # post-to-job
    p = sub.add_parser("post-to-job", help="Post a message to a job conversation")
    p.add_argument("--job-id", required=True)
    p.add_argument("--message", required=True)

    # complete-engagement
    p = sub.add_parser("complete-engagement", help="Mark an engagement as completed")
    p.add_argument("--engagement-id", required=True)
    p.add_argument("--summary", default="")

    return parser


_COMMANDS = {
    "browse-directory": cmd_browse_directory,
    "check-balance": cmd_check_balance,
    "propose-engagement": cmd_propose_engagement,
    "respond-engagement": cmd_respond_engagement,
    "set-price": cmd_set_price,
    "create-job": cmd_create_job,
    "list-team-jobs": cmd_list_team_jobs,
    "read-job-status": cmd_read_job_status,
    "post-to-job": cmd_post_to_job,
    "complete-engagement": cmd_complete_engagement,
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
