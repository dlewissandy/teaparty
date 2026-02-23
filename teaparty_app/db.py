"""Database engine setup, lightweight migrations, seed runner, and session helpers."""

import json
import logging
import time
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy import event, text
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.config import settings


connect_args = {}
_extra_kwargs = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    _extra_kwargs["poolclass"] = NullPool

engine = create_engine(settings.database_url, echo=False, connect_args=connect_args, **_extra_kwargs)

# Set WAL mode and busy timeout on every SQLite connection
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _run_lightweight_migrations()
    _drop_custom_tool_tables()
    _ensure_cross_group_task_tables()
    _ensure_llm_usage_table()
    _ensure_agent_memory_table()
    _ensure_agent_todo_table()
    _ensure_workspace_tables()
    _ensure_job_table()
    _ensure_agent_task_table()
    _ensure_org_operations_field()
    _ensure_org_directory_fields()
    _ensure_payment_tables()
    _ensure_engagement_payment_fields()
    _ensure_agent_max_turns()
    _ensure_agent_is_lead()
    _backfill_lead_agents()
    _ensure_conversation_session_id()
    _migrate_topic_to_job()
    _migrate_agent_tool_names()
    _migrate_add_job_max_rounds()
    _migrate_add_job_permission_mode()
    _migrate_drop_agent_follow_up_minutes()
    _migrate_drop_agent_vestigial_fields()
    _migrate_add_org_files()
    _migrate_add_engagement_files()
    _migrate_add_job_files()
    _migrate_engagement_files_to_entity()
    _migrate_job_files_to_entity()
    _ensure_partnership_table()
    _ensure_notification_table()
    _ensure_org_membership_tables()
    _backfill_org_memberships()
    _migrate_partnership_message()
    _migrate_notification_partnership_fk()
    _ensure_projects_table()
    _migrate_workgroup_team_config()
    _migrate_add_job_project_id()
    _migrate_conversation_org_id()
    _migrate_org_config_fields()
    _migrate_message_drop_agent_fk()
    _backfill_projects_lead()
    _migrate_agent_restructure()
    _migrate_agent_nullable_workgroup_id()
    _cleanup_orphaned_agents()
    _migrate_system_workgroups()
    _run_seeds()


def _run_seeds() -> None:
    from teaparty_app.seeds.runner import run_seeds

    run_seeds(engine)


def _sqlite_column_names(table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {row["name"] for row in rows}


def _normalize_workgroup_files_payload(raw_files: object) -> list[dict[str, str]]:
    parsed: object = raw_files
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed or "[]")
        except (TypeError, ValueError):
            parsed = []

    if not isinstance(parsed, list):
        return []

    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for item in parsed:
        file_id = ""
        path = ""
        content = ""

        if isinstance(item, str):
            path = item.strip()
        elif isinstance(item, dict):
            file_id = str(item.get("id", "")).strip()
            path = str(item.get("path", "")).strip()
            content_value = item.get("content", "")
            content = content_value if isinstance(content_value, str) else str(content_value or "")
        else:
            continue

        if not path:
            continue

        path = path[:512]
        content = content[:200000]
        if path in seen_paths:
            continue

        file_id = file_id or str(uuid4())
        while file_id in seen_ids:
            file_id = str(uuid4())

        normalized.append({"id": file_id, "path": path, "content": content})
        seen_paths.add(path)
        seen_ids.add(file_id)

    return normalized


def _run_lightweight_migrations() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS organizations ("
                "id TEXT PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "description TEXT DEFAULT '' NOT NULL, "
                "owner_id TEXT NOT NULL REFERENCES users(id), "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_organizations_name "
                "ON organizations(name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_organizations_owner_id "
                "ON organizations(owner_id)"
            )
        )

    user_columns = _sqlite_column_names("users")
    workgroup_columns = _sqlite_column_names("workgroups")
    conversation_columns = _sqlite_column_names("conversations")
    agent_columns = _sqlite_column_names("agents")
    membership_columns = _sqlite_column_names("memberships")
    with engine.begin() as conn:
        if "preferences" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN preferences JSON DEFAULT '{}' NOT NULL"))

        if "is_discoverable" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN is_discoverable BOOLEAN DEFAULT 0 NOT NULL"))
        if "service_description" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN service_description TEXT DEFAULT '' NOT NULL"))
        if "organization_id" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN organization_id TEXT REFERENCES organizations(id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_workgroups_organization_id ON workgroups(organization_id)"))

        if "files" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN files JSON DEFAULT '[]' NOT NULL"))
        conn.execute(
            text(
                "UPDATE workgroups "
                "SET files = '[]' "
                "WHERE files IS NULL OR files = '' OR files = 'null'"
            )
        )

        workgroups = conn.execute(text("SELECT id, files FROM workgroups")).mappings().all()
        for workgroup in workgroups:
            normalized = _normalize_workgroup_files_payload(workgroup["files"])

            # Backfill from older topic-scoped conversation files when workgroup files are empty.
            if not normalized and "files" in conversation_columns:
                conversation_rows = conn.execute(
                    text("SELECT files FROM conversations WHERE workgroup_id = :workgroup_id"),
                    {"workgroup_id": workgroup["id"]},
                ).mappings().all()
                merged: list[dict[str, str]] = []
                seen_paths: set[str] = set()
                for row in conversation_rows:
                    row_files = _normalize_workgroup_files_payload(row["files"])
                    for item in row_files:
                        path = item["path"]
                        if path in seen_paths:
                            continue
                        merged.append(item)
                        seen_paths.add(path)
                normalized = merged

            conn.execute(
                text("UPDATE workgroups SET files = :files WHERE id = :workgroup_id"),
                {"files": json.dumps(normalized), "workgroup_id": workgroup["id"]},
            )

        if "is_archived" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN is_archived BOOLEAN DEFAULT 0 NOT NULL"))
        if "archived_at" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN archived_at DATETIME"))
        if "name" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN name TEXT DEFAULT 'general' NOT NULL"))
        if "description" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN description TEXT DEFAULT '' NOT NULL"))
        conn.execute(
            text(
                "UPDATE conversations "
                "SET name = topic "
                "WHERE name IS NULL OR name = ''"
            )
        )

        if "model" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN model TEXT DEFAULT 'sonnet' NOT NULL"))

        # Legacy role backfill removed — role column dropped by _migrate_agent_restructure
        conn.execute(
            text(
                "UPDATE agents "
                "SET model = 'sonnet' "
                "WHERE model IS NULL OR model = '' OR model = 'gpt-4.1-mini' OR model = 'gpt-5-nano'"
            )
        )
        # Normalize long Claude model IDs to short aliases.
        conn.execute(text("UPDATE agents SET model = 'sonnet' WHERE model LIKE 'claude%sonnet%'"))
        conn.execute(text("UPDATE agents SET model = 'haiku' WHERE model LIKE 'claude%haiku%'"))
        conn.execute(text("UPDATE agents SET model = 'opus' WHERE model LIKE 'claude%opus%'"))

        if "workspace_enabled" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN workspace_enabled BOOLEAN DEFAULT 0 NOT NULL"))

        if "budget_limit_usd" not in membership_columns:
            conn.execute(text("ALTER TABLE memberships ADD COLUMN budget_limit_usd REAL"))
        if "budget_used_usd" not in membership_columns:
            conn.execute(text("ALTER TABLE memberships ADD COLUMN budget_used_usd REAL DEFAULT 0.0 NOT NULL"))
        if "budget_refreshed_at" not in membership_columns:
            conn.execute(text("ALTER TABLE memberships ADD COLUMN budget_refreshed_at DATETIME"))

        if "is_system_admin" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_system_admin BOOLEAN DEFAULT 0 NOT NULL"))
            conn.execute(text("UPDATE users SET is_system_admin = 1 WHERE email = 'dlewissandy@gmail.com'"))

        # Create "Acme" organization for ungrouped workgroups
        acme_check = conn.execute(text("SELECT id FROM organizations WHERE name = 'Acme' LIMIT 1")).first()
        if not acme_check:
            import uuid
            acme_id = str(uuid.uuid4())
            admin_user = conn.execute(text(
                "SELECT id FROM users WHERE is_system_admin = 1 LIMIT 1"
            )).first()
            if admin_user:
                conn.execute(text(
                    "INSERT INTO organizations (id, name, description, owner_id, created_at) "
                    "VALUES (:id, 'Acme', '', :owner_id, datetime('now'))"
                ), {"id": acme_id, "owner_id": admin_user[0]})
                conn.execute(text(
                    "UPDATE workgroups SET organization_id = :org_id "
                    "WHERE organization_id IS NULL AND name != 'Administration'"
                ), {"org_id": acme_id})


def _drop_custom_tool_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tool_grants"))
        conn.execute(text("DROP TABLE IF EXISTS tool_definitions"))


def _ensure_cross_group_task_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS cross_group_tasks ("
                "id TEXT PRIMARY KEY, "
                "source_workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "target_workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "requested_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "status TEXT DEFAULT 'requested' NOT NULL, "
                "title TEXT NOT NULL, "
                "scope TEXT DEFAULT '' NOT NULL, "
                "requirements TEXT DEFAULT '' NOT NULL, "
                "terms TEXT DEFAULT '' NOT NULL, "
                "target_conversation_id TEXT REFERENCES conversations(id), "
                "source_conversation_id TEXT REFERENCES conversations(id), "
                "created_at DATETIME NOT NULL, "
                "accepted_at DATETIME, "
                "declined_at DATETIME, "
                "completed_at DATETIME, "
                "satisfied_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS cross_group_task_messages ("
                "id TEXT PRIMARY KEY, "
                "task_id TEXT NOT NULL REFERENCES cross_group_tasks(id), "
                "sender_user_id TEXT NOT NULL REFERENCES users(id), "
                "sender_workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "content TEXT NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS synced_messages ("
                "id TEXT PRIMARY KEY, "
                "task_id TEXT NOT NULL REFERENCES cross_group_tasks(id), "
                "source_message_id TEXT NOT NULL REFERENCES messages(id), "
                "mirror_message_id TEXT NOT NULL REFERENCES messages(id), "
                "created_at DATETIME NOT NULL, "
                "UNIQUE(source_message_id, mirror_message_id)"
                ")"
            )
        )


def _ensure_llm_usage_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS llm_usage_events ("
                "id TEXT PRIMARY KEY, "
                "conversation_id TEXT NOT NULL REFERENCES conversations(id), "
                "agent_id TEXT REFERENCES agents(id), "
                "model TEXT DEFAULT '' NOT NULL, "
                "input_tokens INTEGER DEFAULT 0 NOT NULL, "
                "output_tokens INTEGER DEFAULT 0 NOT NULL, "
                "purpose TEXT DEFAULT 'reply' NOT NULL, "
                "duration_ms INTEGER DEFAULT 0 NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_llm_usage_conversation "
                "ON llm_usage_events(conversation_id)"
            )
        )


def _ensure_agent_memory_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_memories ("
                "id TEXT PRIMARY KEY, "
                "agent_id TEXT NOT NULL REFERENCES agents(id), "
                "conversation_id TEXT NOT NULL REFERENCES conversations(id), "
                "memory_type TEXT NOT NULL, "
                "content TEXT NOT NULL, "
                "source_summary TEXT DEFAULT '' NOT NULL, "
                "confidence REAL DEFAULT 0.7 NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_memories_agent "
                "ON agent_memories(agent_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_memories_type "
                "ON agent_memories(memory_type)"
            )
        )


def _ensure_agent_todo_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_todo_items ("
                "id TEXT PRIMARY KEY, "
                "agent_id TEXT NOT NULL REFERENCES agents(id), "
                "workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "conversation_id TEXT REFERENCES conversations(id), "
                "title TEXT NOT NULL, "
                "description TEXT DEFAULT '' NOT NULL, "
                "status TEXT DEFAULT 'pending' NOT NULL, "
                "priority TEXT DEFAULT 'medium' NOT NULL, "
                "trigger_type TEXT DEFAULT 'manual' NOT NULL, "
                "trigger_config JSON DEFAULT '{}' NOT NULL, "
                "triggered_at DATETIME, "
                "due_at DATETIME, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "completed_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_todo_items_agent "
                "ON agent_todo_items(agent_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_todo_items_workgroup "
                "ON agent_todo_items(workgroup_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_todo_items_status "
                "ON agent_todo_items(status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_todo_items_due_at "
                "ON agent_todo_items(due_at)"
            )
        )


def _ensure_workspace_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS workspaces ("
                "id TEXT PRIMARY KEY, "
                "workgroup_id TEXT NOT NULL UNIQUE REFERENCES workgroups(id), "
                "repo_path TEXT NOT NULL, "
                "main_worktree_path TEXT NOT NULL, "
                "status TEXT DEFAULT 'active' NOT NULL, "
                "error_message TEXT DEFAULT '' NOT NULL, "
                "last_synced_at DATETIME, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_workspaces_workgroup "
                "ON workspaces(workgroup_id)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS workspace_worktrees ("
                "id TEXT PRIMARY KEY, "
                "workspace_id TEXT NOT NULL REFERENCES workspaces(id), "
                "conversation_id TEXT NOT NULL REFERENCES conversations(id), "
                "branch_name TEXT NOT NULL, "
                "worktree_path TEXT NOT NULL, "
                "status TEXT DEFAULT 'active' NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "merged_at DATETIME, "
                "removed_at DATETIME, "
                "UNIQUE(workspace_id, conversation_id)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_workspace_worktrees_workspace "
                "ON workspace_worktrees(workspace_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_workspace_worktrees_conversation "
                "ON workspace_worktrees(conversation_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_workspace_worktrees_branch "
                "ON workspace_worktrees(branch_name)"
            )
        )


def _ensure_job_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, "
                "title TEXT NOT NULL, "
                "scope TEXT DEFAULT '' NOT NULL, "
                "status TEXT DEFAULT 'pending' NOT NULL, "
                "engagement_id TEXT REFERENCES engagements(id), "
                "workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "conversation_id TEXT REFERENCES conversations(id), "
                "created_by_agent_id TEXT REFERENCES agents(id), "
                "deliverables TEXT DEFAULT '' NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "completed_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_engagement ON jobs(engagement_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_workgroup ON jobs(workgroup_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_conversation ON jobs(conversation_id)")
        )


def _ensure_agent_task_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_tasks ("
                "id TEXT PRIMARY KEY, "
                "title TEXT NOT NULL, "
                "description TEXT DEFAULT '' NOT NULL, "
                "status TEXT DEFAULT 'pending' NOT NULL, "
                "agent_id TEXT NOT NULL REFERENCES agents(id), "
                "workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "conversation_id TEXT REFERENCES conversations(id), "
                "created_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "created_at DATETIME NOT NULL, "
                "completed_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_status ON agent_tasks(status)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_agent ON agent_tasks(agent_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_workgroup ON agent_tasks(workgroup_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_conversation ON agent_tasks(conversation_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agent_tasks_created_by ON agent_tasks(created_by_user_id)")
        )


def _ensure_agent_max_turns() -> None:
    # max_turns removed from Agent model — kept as no-op for migration ordering
    pass


def _ensure_agent_is_lead() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    agent_columns = _sqlite_column_names("agents")
    # After M2M migration, is_lead lives in agent_workgroups — skip
    if "workgroup_id" not in agent_columns:
        return
    if "is_lead" not in agent_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agents ADD COLUMN is_lead BOOLEAN DEFAULT 0 NOT NULL"))


def _ensure_conversation_session_id() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("conversations")
    if "claude_session_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN claude_session_id TEXT"))


def _backfill_lead_agents() -> None:
    """For workgroups that have non-admin agents but no lead, set the first non-admin agent as lead."""
    if not settings.database_url.startswith("sqlite"):
        return
    agent_columns = _sqlite_column_names("agents")
    # After M2M migration, is_lead lives in agent_workgroups — use that table
    if "workgroup_id" not in agent_columns:
        _backfill_lead_agents_m2m()
        return
    with engine.begin() as conn:
        # Find workgroups that have non-admin agents but no is_lead=1 agent.
        rows = conn.execute(text(
            "SELECT DISTINCT a.workgroup_id FROM agents a "
            "WHERE (a.description IS NULL OR a.description != '__system_admin_agent__') "
            "AND a.workgroup_id NOT IN ("
            "  SELECT a2.workgroup_id FROM agents a2 WHERE a2.is_lead = 1"
            ")"
        )).fetchall()
        for row in rows:
            wg_id = row[0]
            first = conn.execute(text(
                "SELECT id FROM agents "
                "WHERE workgroup_id = :wg_id "
                "AND (description IS NULL OR description != '__system_admin_agent__') "
                "ORDER BY created_at ASC LIMIT 1"
            ), {"wg_id": wg_id}).first()
            if first:
                conn.execute(text(
                    "UPDATE agents SET is_lead = 1 WHERE id = :id"
                ), {"id": first[0]})


def _backfill_lead_agents_m2m() -> None:
    """Backfill lead agents using the agent_workgroups join table."""
    with engine.begin() as conn:
        # Find workgroups with non-admin agents but no lead in agent_workgroups
        rows = conn.execute(text(
            "SELECT DISTINCT aw.workgroup_id FROM agent_workgroups aw "
            "JOIN agents a ON a.id = aw.agent_id "
            "WHERE (a.description IS NULL OR a.description != '__system_admin_agent__') "
            "AND aw.workgroup_id NOT IN ("
            "  SELECT aw2.workgroup_id FROM agent_workgroups aw2 WHERE aw2.is_lead = 1"
            ")"
        )).fetchall()
        for row in rows:
            wg_id = row[0]
            first = conn.execute(text(
                "SELECT aw.agent_id FROM agent_workgroups aw "
                "JOIN agents a ON a.id = aw.agent_id "
                "WHERE aw.workgroup_id = :wg_id "
                "AND (a.description IS NULL OR a.description != '__system_admin_agent__') "
                "ORDER BY a.created_at ASC LIMIT 1"
            ), {"wg_id": wg_id}).first()
            if first:
                conn.execute(text(
                    "UPDATE agent_workgroups SET is_lead = 1 "
                    "WHERE agent_id = :agent_id AND workgroup_id = :wg_id"
                ), {"agent_id": first[0], "wg_id": wg_id})


def _ensure_org_operations_field() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    org_columns = _sqlite_column_names("organizations")
    if "operations_workgroup_id" not in org_columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE organizations ADD COLUMN operations_workgroup_id TEXT REFERENCES workgroups(id)")
            )


def _ensure_org_directory_fields() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    org_columns = _sqlite_column_names("organizations")
    with engine.begin() as conn:
        if "service_description" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN service_description TEXT DEFAULT '' NOT NULL"))
        if "is_accepting_engagements" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN is_accepting_engagements BOOLEAN DEFAULT 0 NOT NULL"))


def _ensure_payment_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS org_balances ("
                "id TEXT PRIMARY KEY, "
                "organization_id TEXT NOT NULL UNIQUE REFERENCES organizations(id), "
                "balance_credits REAL DEFAULT 0.0 NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_org_balances_org ON org_balances(organization_id)")
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS payment_transactions ("
                "id TEXT PRIMARY KEY, "
                "organization_id TEXT NOT NULL REFERENCES organizations(id), "
                "engagement_id TEXT REFERENCES engagements(id), "
                "transaction_type TEXT NOT NULL, "
                "amount_credits REAL DEFAULT 0.0 NOT NULL, "
                "balance_after_credits REAL DEFAULT 0.0 NOT NULL, "
                "counterparty_org_id TEXT REFERENCES organizations(id), "
                "description TEXT DEFAULT '' NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_payment_transactions_org ON payment_transactions(organization_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_payment_transactions_engagement ON payment_transactions(engagement_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_payment_transactions_type ON payment_transactions(transaction_type)")
        )


def _ensure_engagement_payment_fields() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    eng_columns = _sqlite_column_names("engagements")
    with engine.begin() as conn:
        if "agreed_price_credits" not in eng_columns:
            conn.execute(text("ALTER TABLE engagements ADD COLUMN agreed_price_credits REAL"))
        if "payment_status" not in eng_columns:
            conn.execute(text("ALTER TABLE engagements ADD COLUMN payment_status TEXT DEFAULT 'none' NOT NULL"))


def _migrate_topic_to_job() -> None:
    """Rename conversation kind 'topic' → 'job' and trigger types for existing rows."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE conversations SET kind = 'job' WHERE kind = 'topic'"))
        conn.execute(text("UPDATE agent_todo_items SET trigger_type = 'job_stall' WHERE trigger_type = 'topic_stall'"))
        conn.execute(text("UPDATE agent_todo_items SET trigger_type = 'job_resolved' WHERE trigger_type = 'topic_resolved'"))


def _migrate_agent_tool_names() -> None:
    """Replace stale bespoke tool names with Claude native tools for non-admin agents."""
    import json as _json

    from teaparty_app.services.claude_tools import claude_tool_names

    valid = set(claude_tool_names())
    replacement = _json.dumps(claude_tool_names())

    # Column may be tool_names (old) or tools (new)
    cols = _sqlite_column_names("agents")
    col_name = "tools" if "tools" in cols else "tool_names" if "tool_names" in cols else None
    if not col_name:
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"SELECT id, {col_name} FROM agents "
                "WHERE description != '__system_admin_agent__' OR description IS NULL"
            )
        ).fetchall()

        for row in rows:
            raw = row[1]
            if not raw:
                continue
            try:
                names = _json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                continue
            if not names or not isinstance(names, list):
                continue
            if any(n not in valid for n in names):
                conn.execute(
                    text(f"UPDATE agents SET {col_name} = :tools WHERE id = :id"),
                    {"tools": replacement, "id": row[0]},
                )


def _migrate_add_job_max_rounds() -> None:
    """Add max_rounds column to jobs table."""
    if not settings.database_url.startswith("sqlite"):
        return
    job_columns = _sqlite_column_names("jobs")
    if "max_rounds" not in job_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN max_rounds INTEGER DEFAULT NULL"))


def _migrate_add_job_permission_mode() -> None:
    """Add permission_mode column to jobs table."""
    if not settings.database_url.startswith("sqlite"):
        return
    job_columns = _sqlite_column_names("jobs")
    if "permission_mode" not in job_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN permission_mode TEXT DEFAULT 'acceptEdits' NOT NULL"))


def _migrate_drop_agent_follow_up_minutes() -> None:
    """Drop orphaned follow_up_minutes column from agents table."""
    cols = _sqlite_column_names("agents")
    if "follow_up_minutes" not in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agents DROP COLUMN follow_up_minutes"))


def _migrate_drop_agent_vestigial_fields() -> None:
    """Drop unused agent fields: verbosity, response_threshold, learning_state, sentiment_state, learned_preferences."""
    cols = _sqlite_column_names("agents")
    drop_cols = ["verbosity", "response_threshold", "learning_state", "sentiment_state", "learned_preferences"]
    to_drop = [c for c in drop_cols if c in cols]
    if not to_drop:
        return
    with engine.begin() as conn:
        for col in to_drop:
            conn.execute(text(f"ALTER TABLE agents DROP COLUMN {col}"))


def _migrate_add_org_files() -> None:
    """Add files JSON column to organizations table."""
    if not settings.database_url.startswith("sqlite"):
        return
    org_columns = _sqlite_column_names("organizations")
    if "files" not in org_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN files JSON DEFAULT '[]' NOT NULL"))


def _migrate_add_engagement_files() -> None:
    """Add files JSON column to engagements table."""
    if not settings.database_url.startswith("sqlite"):
        return
    eng_columns = _sqlite_column_names("engagements")
    if "files" not in eng_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE engagements ADD COLUMN files JSON DEFAULT '[]' NOT NULL"))


def _migrate_add_job_files() -> None:
    """Add files JSON column to jobs table."""
    if not settings.database_url.startswith("sqlite"):
        return
    job_columns = _sqlite_column_names("jobs")
    if "files" not in job_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN files JSON DEFAULT '[]' NOT NULL"))


def _migrate_engagement_files_to_entity() -> None:
    """Move engagement files from workgroup.files to Engagement.files."""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        engagements = conn.execute(
            text("SELECT id, files FROM engagements WHERE status != 'declined'")
        ).mappings().all()

        for eng in engagements:
            eng_id = eng["id"]
            # Skip if engagement already has files
            existing = eng["files"]
            if isinstance(existing, str):
                try:
                    existing = json.loads(existing or "[]")
                except (ValueError, TypeError):
                    existing = []
            if existing:
                continue

            prefix = f"engagements/{eng_id}/"

            # Scan all workgroups for files matching this engagement
            workgroups = conn.execute(text("SELECT id, files FROM workgroups")).mappings().all()
            eng_files: list[dict] = []
            seen_paths: set[str] = set()

            for wg in workgroups:
                wg_files = wg["files"]
                if isinstance(wg_files, str):
                    try:
                        wg_files = json.loads(wg_files or "[]")
                    except (ValueError, TypeError):
                        continue
                if not isinstance(wg_files, list):
                    continue

                remaining = []
                changed = False
                for f in wg_files:
                    if not isinstance(f, dict):
                        remaining.append(f)
                        continue
                    path = f.get("path", "")
                    if path.startswith(prefix):
                        # Strip the engagement prefix for the entity-scoped path
                        short_path = path[len(prefix):]
                        if short_path and short_path not in seen_paths:
                            eng_files.append({
                                "id": f.get("id", str(uuid4())),
                                "path": short_path,
                                "content": f.get("content", ""),
                            })
                            seen_paths.add(short_path)
                        changed = True
                    else:
                        remaining.append(f)

                if changed:
                    conn.execute(
                        text("UPDATE workgroups SET files = :files WHERE id = :id"),
                        {"files": json.dumps(remaining), "id": wg["id"]},
                    )

            if eng_files:
                conn.execute(
                    text("UPDATE engagements SET files = :files WHERE id = :id"),
                    {"files": json.dumps(eng_files), "id": eng_id},
                )


def _migrate_job_files_to_entity() -> None:
    """Move job-scoped files from workgroup.files to Job.files."""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        jobs = conn.execute(
            text("SELECT id, conversation_id, workgroup_id, files FROM jobs WHERE conversation_id IS NOT NULL")
        ).mappings().all()

        for job in jobs:
            job_id = job["id"]
            conv_id = job["conversation_id"]
            wg_id = job["workgroup_id"]

            # Skip if job already has files
            existing = job["files"]
            if isinstance(existing, str):
                try:
                    existing = json.loads(existing or "[]")
                except (ValueError, TypeError):
                    existing = []
            if existing:
                continue

            # Get the workgroup files
            wg_row = conn.execute(
                text("SELECT files FROM workgroups WHERE id = :id"),
                {"id": wg_id},
            ).mappings().first()
            if not wg_row:
                continue

            wg_files = wg_row["files"]
            if isinstance(wg_files, str):
                try:
                    wg_files = json.loads(wg_files or "[]")
                except (ValueError, TypeError):
                    continue
            if not isinstance(wg_files, list):
                continue

            # Find files scoped to this job's conversation
            job_files: list[dict] = []
            remaining = []
            changed = False

            for f in wg_files:
                if not isinstance(f, dict):
                    remaining.append(f)
                    continue
                topic_id = f.get("topic_id", "")
                if topic_id == conv_id:
                    job_files.append({
                        "id": f.get("id", str(uuid4())),
                        "path": f.get("path", ""),
                        "content": f.get("content", ""),
                    })
                    changed = True
                else:
                    remaining.append(f)

            if changed:
                conn.execute(
                    text("UPDATE workgroups SET files = :files WHERE id = :id"),
                    {"files": json.dumps(remaining), "id": wg_id},
                )

            if job_files:
                conn.execute(
                    text("UPDATE jobs SET files = :files WHERE id = :id"),
                    {"files": json.dumps(job_files), "id": job_id},
                )


def _ensure_partnership_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS partnerships ("
                "id TEXT PRIMARY KEY, "
                "source_org_id TEXT NOT NULL REFERENCES organizations(id), "
                "target_org_id TEXT NOT NULL REFERENCES organizations(id), "
                "proposed_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "status TEXT DEFAULT 'proposed' NOT NULL, "
                "direction TEXT DEFAULT 'bidirectional' NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "accepted_at DATETIME, "
                "revoked_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_partnerships_source_org ON partnerships(source_org_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_partnerships_target_org ON partnerships(target_org_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_partnerships_status ON partnerships(status)")
        )


def _ensure_notification_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS notifications ("
                "id TEXT PRIMARY KEY, "
                "user_id TEXT NOT NULL REFERENCES users(id), "
                "type TEXT NOT NULL, "
                "title TEXT NOT NULL, "
                "body TEXT DEFAULT '' NOT NULL, "
                "source_conversation_id TEXT REFERENCES conversations(id), "
                "source_job_id TEXT REFERENCES jobs(id), "
                "source_engagement_id TEXT REFERENCES engagements(id), "
                "is_read BOOLEAN DEFAULT 0 NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notifications_type ON notifications(type)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications(is_read)")
        )


def _ensure_org_membership_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS org_memberships ("
                "id TEXT PRIMARY KEY, "
                "organization_id TEXT NOT NULL REFERENCES organizations(id), "
                "user_id TEXT NOT NULL REFERENCES users(id), "
                "role TEXT DEFAULT 'member' NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "UNIQUE(organization_id, user_id)"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_org_memberships_organization ON org_memberships(organization_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_org_memberships_user ON org_memberships(user_id)")
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS org_invites ("
                "id TEXT PRIMARY KEY, "
                "organization_id TEXT NOT NULL REFERENCES organizations(id), "
                "invited_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "email TEXT NOT NULL, "
                "token TEXT NOT NULL UNIQUE, "
                "status TEXT DEFAULT 'pending' NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "expires_at DATETIME, "
                "accepted_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_org_invites_organization ON org_invites(organization_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_org_invites_email ON org_invites(email)")
        )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_org_invites_token ON org_invites(token)")
        )


def _migrate_partnership_message() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("partnerships")
    if "message" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE partnerships ADD COLUMN message TEXT DEFAULT '' NOT NULL"))


def _migrate_notification_partnership_fk() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("notifications")
    if "source_partnership_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN source_partnership_id TEXT REFERENCES partnerships(id)"))


def _backfill_org_memberships() -> None:
    """Idempotently create OrgMembership rows from existing org ownership and workgroup membership."""
    with engine.begin() as conn:
        # Backfill org owner memberships
        conn.execute(
            text(
                "INSERT OR IGNORE INTO org_memberships (id, organization_id, user_id, role, created_at) "
                "SELECT lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || "
                "substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || "
                "substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))), "
                "o.id, o.owner_id, 'owner', datetime('now') "
                "FROM organizations o "
                "WHERE o.owner_id IS NOT NULL"
            )
        )
        # Backfill workgroup member memberships (deduplicated per org)
        conn.execute(
            text(
                "INSERT OR IGNORE INTO org_memberships (id, organization_id, user_id, role, created_at) "
                "SELECT lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || "
                "substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || "
                "substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))), "
                "w.organization_id, m.user_id, 'member', datetime('now') "
                "FROM memberships m "
                "JOIN workgroups w ON w.id = m.workgroup_id "
                "WHERE w.organization_id IS NOT NULL "
                "GROUP BY w.organization_id, m.user_id"
            )
        )


def _ensure_projects_table() -> None:
    """Create the projects table if it doesn't exist."""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id TEXT PRIMARY KEY, "
            "organization_id TEXT NOT NULL REFERENCES organizations(id), "
            "conversation_id TEXT REFERENCES conversations(id), "
            "created_by_user_id TEXT NOT NULL REFERENCES users(id), "
            "name TEXT NOT NULL DEFAULT 'Untitled Project', "
            "prompt TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'pending', "
            "model TEXT NOT NULL DEFAULT 'sonnet', "
            "max_turns INTEGER NOT NULL DEFAULT 30, "
            "permission_mode TEXT NOT NULL DEFAULT 'plan', "
            "max_cost_usd REAL, "
            "max_time_seconds INTEGER, "
            "max_tokens INTEGER, "
            "workgroup_ids JSON NOT NULL DEFAULT '[]', "
            "created_at DATETIME NOT NULL, "
            "completed_at DATETIME"
            ")"
        ))


def _migrate_add_job_project_id() -> None:
    """Add project_id column to jobs table."""
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("jobs")
    if "project_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN project_id TEXT REFERENCES projects(id)"))


def _migrate_conversation_org_id() -> None:
    """Make conversations.workgroup_id nullable and add organization_id.

    Project conversations belong to organizations, not workgroups.
    SQLite doesn't support ALTER COLUMN, so we recreate the table.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("conversations")
    if "organization_id" in cols:
        return  # Already migrated.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE conversations_new ("
            "id TEXT PRIMARY KEY, "
            "workgroup_id TEXT REFERENCES workgroups(id), "
            "organization_id TEXT REFERENCES organizations(id), "
            "created_by_user_id TEXT NOT NULL REFERENCES users(id), "
            "kind TEXT NOT NULL DEFAULT 'job', "
            "topic TEXT NOT NULL DEFAULT 'general', "
            "name TEXT NOT NULL DEFAULT 'general', "
            "description TEXT NOT NULL DEFAULT '', "
            "claude_session_id TEXT, "
            "is_archived BOOLEAN NOT NULL DEFAULT 0, "
            "archived_at DATETIME, "
            "created_at DATETIME NOT NULL"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO conversations_new "
            "(id, workgroup_id, organization_id, created_by_user_id, kind, topic, "
            "name, description, claude_session_id, is_archived, archived_at, created_at) "
            "SELECT id, workgroup_id, NULL, created_by_user_id, kind, topic, "
            "name, description, claude_session_id, is_archived, archived_at, created_at "
            "FROM conversations"
        ))
        conn.execute(text("DROP TABLE conversations"))
        conn.execute(text("ALTER TABLE conversations_new RENAME TO conversations"))
        # Recreate indexes.
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_workgroup_id ON conversations(workgroup_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_organization_id ON conversations(organization_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_created_by_user_id ON conversations(created_by_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_kind ON conversations(kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_conversations_is_archived ON conversations(is_archived)"))


def _migrate_org_config_fields() -> None:
    """Add is_discoverable, engagement_base_fee, engagement_markup_pct, and icon_url to organizations."""
    if not settings.database_url.startswith("sqlite"):
        return
    org_columns = _sqlite_column_names("organizations")
    with engine.begin() as conn:
        if "is_discoverable" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN is_discoverable BOOLEAN DEFAULT 1 NOT NULL"))
        if "engagement_base_fee" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN engagement_base_fee REAL DEFAULT 0.0 NOT NULL"))
        if "engagement_markup_pct" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN engagement_markup_pct REAL DEFAULT 5.0 NOT NULL"))
        if "icon_url" not in org_columns:
            conn.execute(text("ALTER TABLE organizations ADD COLUMN icon_url TEXT DEFAULT '' NOT NULL"))


def _migrate_message_drop_agent_fk() -> None:
    """Drop the foreign key on messages.sender_agent_id.

    Project team messages use ephemeral agent IDs (e.g. 'project:{id}',
    'liaison:{wg_id}') that are not rows in the agents table.
    SQLite doesn't support ALTER CONSTRAINT so we recreate the table.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.connect() as conn:
        schema = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages'"
        )).scalar() or ""
    if "FOREIGN KEY(sender_agent_id)" not in schema:
        return  # Already migrated or FK never existed.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE messages_new ("
            "id VARCHAR NOT NULL PRIMARY KEY, "
            "conversation_id VARCHAR NOT NULL REFERENCES conversations(id), "
            "sender_type VARCHAR NOT NULL, "
            "sender_user_id VARCHAR REFERENCES users(id), "
            "sender_agent_id VARCHAR, "
            "content VARCHAR NOT NULL, "
            "requires_response BOOLEAN NOT NULL, "
            "response_to_message_id VARCHAR REFERENCES messages_new(id), "
            "created_at DATETIME NOT NULL"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO messages_new SELECT * FROM messages"
        ))
        conn.execute(text("DROP TABLE messages"))
        conn.execute(text("ALTER TABLE messages_new RENAME TO messages"))
        conn.execute(text("CREATE INDEX ix_messages_conversation_id ON messages(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_messages_sender_type ON messages(sender_type)"))
        conn.execute(text("CREATE INDEX ix_messages_sender_user_id ON messages(sender_user_id)"))
        conn.execute(text("CREATE INDEX ix_messages_sender_agent_id ON messages(sender_agent_id)"))
        conn.execute(text("CREATE INDEX ix_messages_response_to_message_id ON messages(response_to_message_id)"))


def _backfill_projects_lead() -> None:
    """Ensure every org's Administration workgroup has a projects-lead agent."""
    if not settings.database_url.startswith("sqlite"):
        return

    import json as _json
    from teaparty_app.services.claude_tools import claude_tool_names

    tools_json = _json.dumps(claude_tool_names())
    cols = _sqlite_column_names("agents")

    # Post-M2M migration: workgroup_id is gone, use agent_workgroups
    if "workgroup_id" not in cols:
        _backfill_projects_lead_m2m(tools_json)
        return

    # Determine column names (may be pre- or post-restructure)
    tools_col = "tools" if "tools" in cols else "tool_names"
    image_col = "image" if "image" in cols else "icon"
    has_prompt = "prompt" in cols
    has_old = "role" in cols

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT w.id, w.owner_id FROM workgroups w "
            "WHERE w.name = 'Administration' AND w.organization_id IS NOT NULL "
            "AND w.id NOT IN ("
            "  SELECT a.workgroup_id FROM agents a WHERE a.name = 'projects-lead'"
            ")"
        )).fetchall()

        for row in rows:
            wg_id, owner_id = row[0], row[1]
            agent_id = str(uuid4())
            if has_prompt and not has_old:
                # New schema
                conn.execute(text(
                    f"INSERT INTO agents "
                    f"(id, workgroup_id, created_by_user_id, name, description, prompt, "
                    f"model, {tools_col}, is_lead, {image_col}, created_at) "
                    f"VALUES (:id, :wg_id, :owner_id, 'projects-lead', "
                    f"'Project coordinator', 'Strategic and collaborative project coordinator.', "
                    f"'sonnet', :tools, 1, '', datetime('now'))"
                ), {"id": agent_id, "wg_id": wg_id, "owner_id": owner_id, "tools": tools_json})
            else:
                # Old schema (pre-restructure)
                conn.execute(text(
                    f"INSERT INTO agents "
                    f"(id, workgroup_id, created_by_user_id, name, description, role, "
                    f"personality, backstory, model, temperature, {tools_col}, "
                    f"max_turns, is_lead, {image_col}, created_at) "
                    f"VALUES (:id, :wg_id, :owner_id, 'projects-lead', '', 'Project coordinator', "
                    f"'Strategic and collaborative project coordinator', '', 'sonnet', 0.7, :tools, "
                    f"3, 1, '', datetime('now'))"
                ), {"id": agent_id, "wg_id": wg_id, "owner_id": owner_id, "tools": tools_json})


def _backfill_projects_lead_m2m(tools_json: str) -> None:
    """Backfill projects-lead using agent_workgroups join table."""
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT w.id, w.owner_id, w.organization_id FROM workgroups w "
            "WHERE w.name = 'Administration' AND w.organization_id IS NOT NULL "
            "AND w.id NOT IN ("
            "  SELECT aw.workgroup_id FROM agent_workgroups aw "
            "  JOIN agents a ON a.id = aw.agent_id "
            "  WHERE a.name = 'projects-lead'"
            ")"
        )).fetchall()

        for row in rows:
            wg_id, owner_id, org_id = row[0], row[1], row[2]
            agent_id = str(uuid4())
            link_id = str(uuid4())
            conn.execute(text(
                "INSERT INTO agents "
                "(id, organization_id, created_by_user_id, name, description, prompt, "
                "model, tools, image, created_at) "
                "VALUES (:id, :org_id, :owner_id, 'projects-lead', "
                "'Project coordinator', 'Strategic and collaborative project coordinator.', "
                "'sonnet', :tools, '', datetime('now'))"
            ), {"id": agent_id, "org_id": org_id, "owner_id": owner_id, "tools": tools_json})
            conn.execute(text(
                "INSERT INTO agent_workgroups (id, agent_id, workgroup_id, is_lead, created_at) "
                "VALUES (:link_id, :agent_id, :wg_id, 1, datetime('now'))"
            ), {"link_id": link_id, "agent_id": agent_id, "wg_id": wg_id})


def _migrate_agent_restructure() -> None:
    """Restructure agents table: replace role/personality/backstory/temperature/max_turns
    with prompt/permission_mode/hooks/memory/background/isolation, rename icon→image and tool_names→tools."""
    if not settings.database_url.startswith("sqlite"):
        return

    cols = _sqlite_column_names("agents")

    with engine.begin() as conn:
        # Add new columns
        if "prompt" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN prompt TEXT DEFAULT '' NOT NULL"))

            # Backfill prompt from role + personality + backstory
            rows = conn.execute(text(
                "SELECT id, role, personality, backstory FROM agents"
            )).fetchall() if "role" in cols else []
            for row in rows:
                parts = []
                role = (row[1] or "").strip()
                personality = (row[2] or "").strip()
                backstory = (row[3] or "").strip()
                if role:
                    parts.append(role + ".")
                if personality and personality != "Professional and concise":
                    parts.append(personality)
                if backstory:
                    parts.append(backstory)
                prompt_val = " ".join(parts)
                if prompt_val:
                    conn.execute(text(
                        "UPDATE agents SET prompt = :prompt WHERE id = :id"
                    ), {"prompt": prompt_val, "id": row[0]})

        if "permission_mode" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN permission_mode TEXT DEFAULT 'default' NOT NULL"))
        if "hooks" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN hooks JSON DEFAULT '{}' NOT NULL"))
        if "memory" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN memory TEXT DEFAULT '' NOT NULL"))
        if "background" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN background BOOLEAN DEFAULT 0 NOT NULL"))
        if "isolation" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN isolation BOOLEAN DEFAULT 1 NOT NULL"))

        # Rename icon → image
        if "icon" in cols and "image" not in cols:
            conn.execute(text("ALTER TABLE agents RENAME COLUMN icon TO image"))
        elif "image" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN image TEXT DEFAULT '' NOT NULL"))

        # Rename tool_names → tools
        if "tool_names" in cols and "tools" not in cols:
            conn.execute(text("ALTER TABLE agents RENAME COLUMN tool_names TO tools"))
        elif "tools" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN tools JSON DEFAULT '[]' NOT NULL"))

    # Refresh cols after additions/renames
    cols = _sqlite_column_names("agents")

    # Drop old columns
    drop_cols = ["role", "personality", "backstory", "temperature", "max_turns"]
    to_drop = [c for c in drop_cols if c in cols]
    if to_drop:
        with engine.begin() as conn:
            for col in to_drop:
                conn.execute(text(f"ALTER TABLE agents DROP COLUMN {col}"))


def _migrate_workgroup_team_config() -> None:
    """Add team configuration columns to workgroups table."""
    if not settings.database_url.startswith("sqlite"):
        return
    cols = _sqlite_column_names("workgroups")
    with engine.begin() as conn:
        if "team_model" not in cols:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN team_model TEXT NOT NULL DEFAULT 'sonnet'"))
        if "team_permission_mode" not in cols:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN team_permission_mode TEXT NOT NULL DEFAULT 'acceptEdits'"))
        if "team_max_turns" not in cols:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN team_max_turns INTEGER NOT NULL DEFAULT 30"))
        if "team_max_cost_usd" not in cols:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN team_max_cost_usd REAL"))
        if "team_max_time_seconds" not in cols:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN team_max_time_seconds INTEGER"))


def _migrate_agent_nullable_workgroup_id() -> None:
    """Migrate agents to many-to-many workgroup relationship via agent_workgroups table."""
    if not settings.database_url.startswith("sqlite"):
        return

    cols = _sqlite_column_names("agents")

    # Nothing to do if workgroup_id is already gone (migration already ran)
    if "workgroup_id" not in cols:
        return

    # Step 1: Add organization_id to agents if missing
    if "organization_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agents ADD COLUMN organization_id TEXT"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_organization_id ON agents (organization_id)"))
            conn.execute(text(
                "UPDATE agents SET organization_id = ("
                "  SELECT w.organization_id FROM workgroups w WHERE w.id = agents.workgroup_id"
                ") WHERE organization_id IS NULL AND workgroup_id IS NOT NULL"
            ))

    # Step 2: Create agent_workgroups join table and backfill
    existing_tables = set()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        existing_tables = {r[0] for r in rows}

    if "agent_workgroups" not in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE agent_workgroups (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    workgroup_id TEXT NOT NULL,
                    is_lead BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (agent_id, workgroup_id)
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_workgroups_agent_id ON agent_workgroups (agent_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_workgroups_workgroup_id ON agent_workgroups (workgroup_id)"))

            # Backfill from agents.workgroup_id
            is_lead_col = "is_lead" if "is_lead" in cols else "0"
            conn.execute(text(f"""
                INSERT INTO agent_workgroups (id, agent_id, workgroup_id, is_lead, created_at)
                SELECT lower(hex(randomblob(16))), id, workgroup_id, {is_lead_col}, created_at
                FROM agents
                WHERE workgroup_id IS NOT NULL AND workgroup_id != ''
            """))

    # Step 3: Recreate agents table without workgroup_id and is_lead
    # (full recreation avoids SQLite FK constraint issue with DROP COLUMN)
    with engine.connect() as conn:
        info = conn.execute(text("PRAGMA table_info(agents)")).mappings().all()

    # Columns to keep (everything except workgroup_id and is_lead)
    keep_cols = [c["name"] for c in info if c["name"] not in ("workgroup_id", "is_lead")]

    if not keep_cols or "workgroup_id" not in [c["name"] for c in info]:
        return  # Already migrated

    # Build CREATE TABLE for the new schema
    col_defs = []
    for c in info:
        if c["name"] in ("workgroup_id", "is_lead"):
            continue
        name = c["name"]
        col_type = c["type"] or "TEXT"
        parts = [name, col_type]
        if name == "id":
            parts.append("PRIMARY KEY")
        else:
            if c["notnull"]:
                parts.append("NOT NULL")
            if c["dflt_value"] is not None:
                parts.append(f"DEFAULT {c['dflt_value']}")
        col_defs.append(" ".join(parts))

    col_list = ", ".join(keep_cols)
    create_sql = f"CREATE TABLE agents_new ({', '.join(col_defs)})"

    with engine.begin() as conn:
        conn.execute(text(create_sql))
        conn.execute(text(f"INSERT INTO agents_new ({col_list}) SELECT {col_list} FROM agents"))
        conn.execute(text("DROP TABLE agents"))
        conn.execute(text("ALTER TABLE agents_new RENAME TO agents"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_organization_id ON agents (organization_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_created_by_user_id ON agents (created_by_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_name ON agents (name)"))


def _cleanup_orphaned_agents() -> None:
    """Delete orphaned agents that have no agent_workgroups links
    and where a linked agent with the same name exists in the same org."""
    if not settings.database_url.startswith("sqlite"):
        return

    existing_tables = set()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        existing_tables = {r[0] for r in rows}

    if "agent_workgroups" not in existing_tables:
        return

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM agents WHERE id IN (
                SELECT a.id FROM agents a
                WHERE a.id NOT IN (SELECT aw.agent_id FROM agent_workgroups aw)
                AND EXISTS (
                    SELECT 1 FROM agents a2
                    JOIN agent_workgroups aw2 ON aw2.agent_id = a2.id
                    WHERE a2.name = a.name AND a2.organization_id = a.organization_id
                )
            )
        """))


def _migrate_system_workgroups() -> None:
    """Ensure each org has three system workgroups (Administration, Project Management, Engagement)
    with the correct lead agents. Moves agents out of Administration into their own workgroups."""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "agent_workgroups" not in tables:
        return

    with engine.begin() as conn:
        # Find all org-level Administration workgroups
        admin_wgs = conn.execute(text(
            "SELECT id, owner_id, organization_id FROM workgroups "
            "WHERE name = 'Administration' AND organization_id IS NOT NULL"
        )).fetchall()

        for admin_wg_id, owner_id, org_id in admin_wgs:
            # --- Project Management workgroup ---
            row = conn.execute(text(
                "SELECT id FROM workgroups WHERE name = 'Project Management' AND organization_id = :org_id"
            ), {"org_id": org_id}).first()
            if not row:
                pm_id = str(uuid4())
                conn.execute(text(
                    "INSERT INTO workgroups (id, name, files, owner_id, organization_id, created_at) "
                    "VALUES (:id, 'Project Management', '[]', :owner_id, :org_id, datetime('now'))"
                ), {"id": pm_id, "owner_id": owner_id, "org_id": org_id})
                conn.execute(text(
                    "INSERT INTO memberships (id, workgroup_id, user_id, role, created_at) "
                    "VALUES (:id, :wg_id, :uid, 'owner', datetime('now'))"
                ), {"id": str(uuid4()), "wg_id": pm_id, "uid": owner_id})
            else:
                pm_id = row[0]

            # Move projects-lead from Administration → Project Management
            pl = conn.execute(text(
                "SELECT a.id FROM agents a "
                "JOIN agent_workgroups aw ON aw.agent_id = a.id "
                "WHERE a.name = 'projects-lead' AND aw.workgroup_id = :wg_id"
            ), {"wg_id": admin_wg_id}).first()
            if pl:
                conn.execute(text(
                    "DELETE FROM agent_workgroups WHERE agent_id = :aid AND workgroup_id = :wg_id"
                ), {"aid": pl[0], "wg_id": admin_wg_id})
                exists = conn.execute(text(
                    "SELECT id FROM agent_workgroups WHERE agent_id = :aid AND workgroup_id = :wg_id"
                ), {"aid": pl[0], "wg_id": pm_id}).first()
                if not exists:
                    conn.execute(text(
                        "INSERT INTO agent_workgroups (id, agent_id, workgroup_id, is_lead, created_at) "
                        "VALUES (:id, :aid, :wg_id, 1, datetime('now'))"
                    ), {"id": str(uuid4()), "aid": pl[0], "wg_id": pm_id})

            # --- Engagement workgroup ---
            row = conn.execute(text(
                "SELECT id FROM workgroups WHERE name = 'Engagement' AND organization_id = :org_id"
            ), {"org_id": org_id}).first()
            if not row:
                eng_id = str(uuid4())
                conn.execute(text(
                    "INSERT INTO workgroups (id, name, files, owner_id, organization_id, created_at) "
                    "VALUES (:id, 'Engagement', '[]', :owner_id, :org_id, datetime('now'))"
                ), {"id": eng_id, "owner_id": owner_id, "org_id": org_id})
                conn.execute(text(
                    "INSERT INTO memberships (id, workgroup_id, user_id, role, created_at) "
                    "VALUES (:id, :wg_id, :uid, 'owner', datetime('now'))"
                ), {"id": str(uuid4()), "wg_id": eng_id, "uid": owner_id})
            else:
                eng_id = row[0]

            # Move engagements-lead from Administration → Engagement
            el = conn.execute(text(
                "SELECT a.id FROM agents a "
                "JOIN agent_workgroups aw ON aw.agent_id = a.id "
                "WHERE a.name = 'engagements-lead' AND aw.workgroup_id = :wg_id"
            ), {"wg_id": admin_wg_id}).first()
            if el:
                conn.execute(text(
                    "DELETE FROM agent_workgroups WHERE agent_id = :aid AND workgroup_id = :wg_id"
                ), {"aid": el[0], "wg_id": admin_wg_id})
                exists = conn.execute(text(
                    "SELECT id FROM agent_workgroups WHERE agent_id = :aid AND workgroup_id = :wg_id"
                ), {"aid": el[0], "wg_id": eng_id}).first()
                if not exists:
                    conn.execute(text(
                        "INSERT INTO agent_workgroups (id, agent_id, workgroup_id, is_lead, created_at) "
                        "VALUES (:id, :aid, :wg_id, 1, datetime('now'))"
                    ), {"id": str(uuid4()), "aid": el[0], "wg_id": eng_id})

            # --- Rename organization-admin → administrator ---
            admin = conn.execute(text(
                "SELECT a.id FROM agents a "
                "JOIN agent_workgroups aw ON aw.agent_id = a.id "
                "WHERE a.name = 'organization-admin' AND aw.workgroup_id = :wg_id"
            ), {"wg_id": admin_wg_id}).first()
            if admin:
                conn.execute(text(
                    "UPDATE agents SET name = 'administrator', "
                    "description = 'Organization administrator' "
                    "WHERE id = :id"
                ), {"id": admin[0]})
                conn.execute(text(
                    "UPDATE agent_workgroups SET is_lead = 1 "
                    "WHERE agent_id = :aid AND workgroup_id = :wg_id"
                ), {"aid": admin[0], "wg_id": admin_wg_id})


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def commit_with_retry(session: Session, max_retries: int = 3, base_delay: float = 0.1) -> None:
    """Commit with retry on SQLite 'database is locked' errors."""
    for attempt in range(max_retries):
        try:
            session.commit()
            return
        except Exception as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logging.getLogger(__name__).warning(
                    "SQLite locked on commit (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, max_retries, delay,
                )
                session.rollback()
                time.sleep(delay)
            else:
                raise
