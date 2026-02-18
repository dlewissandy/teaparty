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

        if "role" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN role TEXT DEFAULT '' NOT NULL"))
        if "backstory" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN backstory TEXT DEFAULT '' NOT NULL"))
        if "model" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN model TEXT DEFAULT 'claude-sonnet-4-5' NOT NULL"))
        if "temperature" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN temperature FLOAT DEFAULT 0.7 NOT NULL"))
        if "verbosity" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN verbosity FLOAT DEFAULT 0.5 NOT NULL"))
        if "learning_state" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN learning_state JSON DEFAULT '{}' NOT NULL"))
        if "sentiment_state" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN sentiment_state JSON DEFAULT '{}' NOT NULL"))
        if "icon" not in agent_columns:
            conn.execute(text("ALTER TABLE agents ADD COLUMN icon TEXT DEFAULT '' NOT NULL"))

        conn.execute(
            text(
                "UPDATE agents "
                "SET role = description "
                "WHERE (role IS NULL OR role = '') "
                "AND description IS NOT NULL "
                "AND description != '__system_admin_agent__'"
            )
        )
        conn.execute(
            text(
                "UPDATE agents "
                "SET learning_state = learned_preferences "
                "WHERE learned_preferences IS NOT NULL "
                "AND (learning_state IS NULL OR learning_state = '{}' OR learning_state = 'null')"
            )
        )
        conn.execute(
            text(
                "UPDATE agents "
                "SET model = 'claude-sonnet-4-5' "
                "WHERE model IS NULL OR model = '' OR model = 'gpt-4.1-mini' OR model = 'gpt-5-nano'"
            )
        )
        conn.execute(
            text(
                "UPDATE agents "
                "SET verbosity = 0.5 "
                "WHERE verbosity IS NULL OR verbosity < 0 OR verbosity > 1"
            )
        )

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
    if not settings.database_url.startswith("sqlite"):
        return
    agent_columns = _sqlite_column_names("agents")
    if "max_turns" not in agent_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE agents ADD COLUMN max_turns INTEGER DEFAULT 3 NOT NULL"))


def _ensure_agent_is_lead() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    agent_columns = _sqlite_column_names("agents")
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

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, tool_names FROM agents "
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
                    text("UPDATE agents SET tool_names = :tools WHERE id = :id"),
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
