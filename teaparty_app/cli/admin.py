"""CLI for admin agents to invoke admin workspace tools via Bash.

Usage:
    python -m teaparty_app.cli.admin <subcommand> [args]

Environment variables (injected by agent runtime):
    TEAPARTY_USER_ID      - The requesting user's ID
    TEAPARTY_WORKGROUP_ID - The current workgroup ID (used for local workgroup commands)
    TEAPARTY_ORG_ID       - The organization ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from sqlmodel import Session

from teaparty_app.db import engine
from teaparty_app.services.admin_workspace import file_tools, global_tools, member_tools


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(json.dumps({"error": f"Missing environment variable: {name}"}))
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# Workgroup management
# ---------------------------------------------------------------------------


def cmd_create_workgroup(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.name,
        "organization_name": args.org,
    }
    if args.template:
        tool_input["template_key"] = args.template
    with Session(engine) as session:
        result = global_tools.create_workgroup(session, user_id, tool_input)
        # create_workgroup does its own commit internally
        print(result)


def cmd_list_workgroups(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {}
    if args.org:
        tool_input["organization_name"] = args.org
    with Session(engine) as session:
        result = global_tools.list_workgroups(session, user_id, tool_input)
        print(result)


def cmd_edit_workgroup(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {"workgroup_name": args.name}
    if args.new_name is not None:
        tool_input["new_name"] = args.new_name
    if args.service_description is not None:
        tool_input["service_description"] = args.service_description
    if args.discoverable is not None:
        tool_input["is_discoverable"] = args.discoverable.lower() in ("true", "1", "yes")
    with Session(engine) as session:
        result = global_tools.edit_workgroup(session, user_id, tool_input)
        if not result.startswith("No fields") and "not found" not in result and "required" not in result:
            session.commit()
        print(result)


def cmd_list_templates(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.list_templates(session, user_id, {})
        print(result)


# ---------------------------------------------------------------------------
# Agent management
# ---------------------------------------------------------------------------


def cmd_create_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.name,
    }
    if args.prompt is not None:
        tool_input["prompt"] = args.prompt
    if args.description is not None:
        tool_input["description"] = args.description
    if args.model is not None:
        tool_input["model"] = args.model
    if args.tools is not None:
        tool_input["tools"] = [t.strip() for t in args.tools.split(",") if t.strip()]
    with Session(engine) as session:
        result = global_tools.create_agent(session, user_id, tool_input)
        if "Created agent" in result:
            session.commit()
        print(result)


def cmd_list_agents(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.list_agents(session, user_id, {"workgroup_name": args.workgroup})
        print(result)


def cmd_update_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.name,
    }
    if args.prompt is not None:
        tool_input["prompt"] = args.prompt
    if args.model is not None:
        tool_input["model"] = args.model
    if args.tools is not None:
        tool_input["tools"] = [t.strip() for t in args.tools.split(",") if t.strip()]
    with Session(engine) as session:
        result = global_tools.update_agent(session, user_id, tool_input)
        if "Updated agent" in result:
            session.commit()
        print(result)


def cmd_find_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {"agent_name": args.name}
    if args.org:
        tool_input["organization_name"] = args.org
    with Session(engine) as session:
        result = global_tools.find_agent(session, user_id, tool_input)
        print(result)


def cmd_delete_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.name,
    }
    with Session(engine) as session:
        result = global_tools.delete_agent(session, user_id, tool_input)
        if "Removed member" in result:
            session.commit()
        print(result)


def cmd_add_agent_to_workgroup(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.agent,
    }
    with Session(engine) as session:
        result = global_tools.add_agent_to_workgroup(session, user_id, tool_input)
        if "Added agent" in result:
            session.commit()
        print(result)


def cmd_remove_agent_from_workgroup(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.agent,
    }
    with Session(engine) as session:
        result = global_tools.remove_agent_from_workgroup(session, user_id, tool_input)
        if "Removed agent" in result:
            session.commit()
        print(result)


def cmd_add_tool_to_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.agent,
        "tools": [t.strip() for t in args.tools.split(",") if t.strip()],
    }
    with Session(engine) as session:
        result = global_tools.add_tool_to_agent(session, user_id, tool_input)
        if "Added tools" in result:
            session.commit()
        print(result)


def cmd_remove_tool_from_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "agent_name": args.agent,
        "tools": [t.strip() for t in args.tools.split(",") if t.strip()],
    }
    with Session(engine) as session:
        result = global_tools.remove_tool_from_agent(session, user_id, tool_input)
        if "Removed tools" in result:
            session.commit()
        print(result)


def cmd_list_available_tools(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.list_available_tools(session, user_id, {"workgroup_name": args.workgroup})
        print(result)


# ---------------------------------------------------------------------------
# Organization management
# ---------------------------------------------------------------------------


def cmd_create_organization(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {"name": args.name}
    if args.description is not None:
        tool_input["description"] = args.description
    with Session(engine) as session:
        result = global_tools.create_organization(session, user_id, tool_input)
        if "Created organization" in result:
            session.commit()
        print(result)


def cmd_list_organizations(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.list_organizations(session, user_id, {})
        print(result)


def cmd_find_organization(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.find_organization(session, user_id, {"query": args.query})
        print(result)


# ---------------------------------------------------------------------------
# Partnership management
# ---------------------------------------------------------------------------


def cmd_list_partners(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {"organization_name": args.org}
    if args.status:
        tool_input["status"] = args.status
    with Session(engine) as session:
        result = global_tools.list_partners(session, user_id, tool_input)
        print(result)


def cmd_add_partner(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "source_organization_name": args.source,
        "target_organization_name": args.target,
    }
    if args.direction:
        tool_input["direction"] = args.direction
    with Session(engine) as session:
        result = global_tools.add_partner(session, user_id, tool_input)
        if "Created partnership" in result:
            session.commit()
        print(result)


def cmd_delete_partner(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "source_organization_name": args.source,
        "target_organization_name": args.target,
    }
    with Session(engine) as session:
        result = global_tools.delete_partner(session, user_id, tool_input)
        if "Revoked partnership" in result:
            session.commit()
        print(result)


# ---------------------------------------------------------------------------
# Workflow management
# ---------------------------------------------------------------------------


def cmd_list_workflows(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    with Session(engine) as session:
        result = global_tools.list_workflows(session, user_id, {"workgroup_name": args.workgroup})
        print(result)


def cmd_create_workflow(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "name": args.name,
        "content": args.content or "",
    }
    with Session(engine) as session:
        result = global_tools.create_workflow(session, user_id, tool_input)
        if "Created workflow" in result:
            session.commit()
        print(result)


def cmd_delete_workflow(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "name": args.name,
    }
    with Session(engine) as session:
        result = global_tools.delete_workflow(session, user_id, tool_input)
        if "Deleted workflow" in result:
            session.commit()
        print(result)


def cmd_find_workflow(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    tool_input: dict = {
        "workgroup_name": args.workgroup,
        "name": args.name,
    }
    with Session(engine) as session:
        result = global_tools.find_workflow(session, user_id, tool_input)
        print(result)


# ---------------------------------------------------------------------------
# Local workgroup tools (member_tools, file_tools — use TEAPARTY_WORKGROUP_ID)
# ---------------------------------------------------------------------------


def cmd_add_agent(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = member_tools.admin_tool_add_agent(
            session,
            wg_id,
            user_id,
            args.name,
            prompt=args.prompt or "",
            model=args.model or "",
        )
        if "Created agent" in result:
            session.commit()
        print(result)


def cmd_add_user(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = member_tools.admin_tool_add_user(session, wg_id, user_id, args.email)
        if "Added" in result or "Created invite" in result:
            session.commit()
        print(result)


def cmd_remove_member(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = member_tools.admin_tool_remove_member(session, wg_id, user_id, args.selector)
        if "Removed member" in result:
            session.commit()
        print(result)


def cmd_list_members(args: argparse.Namespace) -> None:
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = member_tools.admin_tool_list_members(session, wg_id)
        print(result)


def cmd_delete_workgroup(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = member_tools.admin_tool_delete_workgroup(session, wg_id, user_id, confirmed=args.confirm)
        if "Confirmed" in result:
            session.commit()
        print(result)


def cmd_add_file(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = file_tools.admin_tool_add_file(session, wg_id, user_id, args.path, content=args.content or "")
        if "Added file" in result:
            session.commit()
        print(result)


def cmd_edit_file(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = file_tools.admin_tool_edit_file(session, wg_id, user_id, args.path, args.content)
        if "Updated file" in result:
            session.commit()
        print(result)


def cmd_rename_file(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = file_tools.admin_tool_rename_file(session, wg_id, user_id, args.source, args.dest)
        if "Renamed file" in result:
            session.commit()
        print(result)


def cmd_delete_file(args: argparse.Namespace) -> None:
    user_id = _env("TEAPARTY_USER_ID")
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = file_tools.admin_tool_delete_file(session, wg_id, user_id, args.path)
        if "Deleted file" in result:
            session.commit()
        print(result)


def cmd_list_files(args: argparse.Namespace) -> None:
    wg_id = _env("TEAPARTY_WORKGROUP_ID")
    with Session(engine) as session:
        result = file_tools.admin_tool_list_files(session, wg_id)
        print(result)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m teaparty_app.cli.admin",
        description="Admin CLI for admin agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- Workgroup management ------------------------------------------------

    # create-workgroup
    p = sub.add_parser("create-workgroup", help="Create a new workgroup")
    p.add_argument("--name", required=True, help="Workgroup name")
    p.add_argument("--org", required=True, help="Organization name")
    p.add_argument("--template", default="", help="Template key (optional)")

    # list-workgroups
    p = sub.add_parser("list-workgroups", help="List workgroups")
    p.add_argument("--org", default="", help="Filter by organization name")

    # edit-workgroup
    p = sub.add_parser("edit-workgroup", help="Edit workgroup properties")
    p.add_argument("--name", required=True, help="Workgroup name")
    p.add_argument("--new-name", default=None, dest="new_name", help="New workgroup name")
    p.add_argument("--service-description", default=None, dest="service_description", help="Service description")
    p.add_argument("--discoverable", default=None, help="Set discoverability (true/false)")

    # list-templates
    sub.add_parser("list-templates", help="List available workgroup templates")

    # -- Agent management ----------------------------------------------------

    # create-agent
    p = sub.add_parser("create-agent", help="Create an agent in a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Agent name")
    p.add_argument("--prompt", default=None, help="Agent prompt/instructions")
    p.add_argument("--description", default=None, help="Agent description")
    p.add_argument("--model", default=None, help="Model name (sonnet, opus, haiku)")
    p.add_argument("--tools", default=None, help="Comma-separated tool names")

    # list-agents
    p = sub.add_parser("list-agents", help="List agents in a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")

    # update-agent
    p = sub.add_parser("update-agent", help="Update an agent's properties")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Agent name")
    p.add_argument("--prompt", default=None, help="New prompt/instructions")
    p.add_argument("--model", default=None, help="New model name")
    p.add_argument("--tools", default=None, help="Comma-separated tool names (replaces existing)")

    # find-agent
    p = sub.add_parser("find-agent", help="Find agents by name across workgroups")
    p.add_argument("--name", required=True, help="Agent name (partial match)")
    p.add_argument("--org", default="", help="Limit search to organization")

    # delete-agent
    p = sub.add_parser("delete-agent", help="Delete an agent from a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Agent name")

    # add-agent-to-workgroup
    p = sub.add_parser("add-agent-to-workgroup", help="Link an existing agent to a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--agent", required=True, help="Agent name")

    # remove-agent-from-workgroup
    p = sub.add_parser("remove-agent-from-workgroup", help="Unlink an agent from a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--agent", required=True, help="Agent name")

    # add-tool-to-agent
    p = sub.add_parser("add-tool-to-agent", help="Add tools to an agent")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--agent", required=True, help="Agent name")
    p.add_argument("--tools", required=True, help="Comma-separated tool names to add")

    # remove-tool-from-agent
    p = sub.add_parser("remove-tool-from-agent", help="Remove tools from an agent")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--agent", required=True, help="Agent name")
    p.add_argument("--tools", required=True, help="Comma-separated tool names to remove")

    # list-available-tools
    p = sub.add_parser("list-available-tools", help="List all tools available for assignment")
    p.add_argument("--workgroup", required=True, help="Workgroup name")

    # -- Organization management ---------------------------------------------

    # create-organization
    p = sub.add_parser("create-organization", help="Create a new organization")
    p.add_argument("--name", required=True, help="Organization name")
    p.add_argument("--description", default=None, help="Organization description")

    # list-organizations
    sub.add_parser("list-organizations", help="List owned organizations")

    # find-organization
    p = sub.add_parser("find-organization", help="Search for organizations by name")
    p.add_argument("--query", required=True, help="Search query")

    # -- Partnership management ----------------------------------------------

    # list-partners
    p = sub.add_parser("list-partners", help="List partnerships for an organization")
    p.add_argument("--org", required=True, help="Organization name")
    p.add_argument("--status", default="", help="Filter by status (accepted, all, etc.)")

    # add-partner
    p = sub.add_parser("add-partner", help="Create a partnership between two organizations")
    p.add_argument("--source", required=True, help="Source organization name (must be owned)")
    p.add_argument("--target", required=True, help="Target organization name")
    p.add_argument("--direction", default="", help="Direction: bidirectional, source_to_target, target_to_source")

    # delete-partner
    p = sub.add_parser("delete-partner", help="Revoke a partnership")
    p.add_argument("--source", required=True, help="Source organization name")
    p.add_argument("--target", required=True, help="Target organization name")

    # -- Workflow management -------------------------------------------------

    # list-workflows
    p = sub.add_parser("list-workflows", help="List workflows in a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")

    # create-workflow
    p = sub.add_parser("create-workflow", help="Create a workflow in a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Workflow name (e.g. onboarding or workflows/onboarding.md)")
    p.add_argument("--content", default="", help="Workflow content (markdown)")

    # delete-workflow
    p = sub.add_parser("delete-workflow", help="Delete a workflow from a workgroup")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Workflow name")

    # find-workflow
    p = sub.add_parser("find-workflow", help="Read a workflow's content")
    p.add_argument("--workgroup", required=True, help="Workgroup name")
    p.add_argument("--name", required=True, help="Workflow name")

    # -- Local workgroup tools (use TEAPARTY_WORKGROUP_ID) -------------------

    # add-agent (local)
    p = sub.add_parser("add-agent", help="Add an agent to the current workgroup")
    p.add_argument("--name", required=True, help="Agent name")
    p.add_argument("--prompt", default="", help="Agent prompt/instructions")
    p.add_argument("--model", default="", help="Model name")

    # add-user
    p = sub.add_parser("add-user", help="Add a user to the current workgroup by email")
    p.add_argument("--email", required=True, help="User email address")

    # remove-member
    p = sub.add_parser("remove-member", help="Remove a member (human or agent) from the current workgroup")
    p.add_argument("--selector", required=True, help="Member ID, email, or name")

    # list-members
    sub.add_parser("list-members", help="List members of the current workgroup")

    # delete-workgroup
    p = sub.add_parser("delete-workgroup", help="Delete the current workgroup")
    p.add_argument("--confirm", action="store_true", default=False, help="Confirm deletion")

    # add-file
    p = sub.add_parser("add-file", help="Add a file to the current workgroup")
    p.add_argument("--path", required=True, help="File path")
    p.add_argument("--content", default="", help="File content")

    # edit-file
    p = sub.add_parser("edit-file", help="Edit a file in the current workgroup")
    p.add_argument("--path", required=True, help="File path")
    p.add_argument("--content", required=True, help="New file content")

    # rename-file
    p = sub.add_parser("rename-file", help="Rename a file in the current workgroup")
    p.add_argument("--source", required=True, help="Current file path")
    p.add_argument("--dest", required=True, help="New file path")

    # delete-file
    p = sub.add_parser("delete-file", help="Delete a file from the current workgroup")
    p.add_argument("--path", required=True, help="File path")

    # list-files
    sub.add_parser("list-files", help="List files in the current workgroup")

    return parser


_COMMANDS = {
    # Workgroup management
    "create-workgroup": cmd_create_workgroup,
    "list-workgroups": cmd_list_workgroups,
    "edit-workgroup": cmd_edit_workgroup,
    "list-templates": cmd_list_templates,
    # Agent management
    "create-agent": cmd_create_agent,
    "list-agents": cmd_list_agents,
    "update-agent": cmd_update_agent,
    "find-agent": cmd_find_agent,
    "delete-agent": cmd_delete_agent,
    "add-agent-to-workgroup": cmd_add_agent_to_workgroup,
    "remove-agent-from-workgroup": cmd_remove_agent_from_workgroup,
    "add-tool-to-agent": cmd_add_tool_to_agent,
    "remove-tool-from-agent": cmd_remove_tool_from_agent,
    "list-available-tools": cmd_list_available_tools,
    # Organization management
    "create-organization": cmd_create_organization,
    "list-organizations": cmd_list_organizations,
    "find-organization": cmd_find_organization,
    # Partnership management
    "list-partners": cmd_list_partners,
    "add-partner": cmd_add_partner,
    "delete-partner": cmd_delete_partner,
    # Workflow management
    "list-workflows": cmd_list_workflows,
    "create-workflow": cmd_create_workflow,
    "delete-workflow": cmd_delete_workflow,
    "find-workflow": cmd_find_workflow,
    # Local workgroup tools
    "add-agent": cmd_add_agent,
    "add-user": cmd_add_user,
    "remove-member": cmd_remove_member,
    "list-members": cmd_list_members,
    "delete-workgroup": cmd_delete_workgroup,
    "add-file": cmd_add_file,
    "edit-file": cmd_edit_file,
    "rename-file": cmd_rename_file,
    "delete-file": cmd_delete_file,
    "list-files": cmd_list_files,
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
