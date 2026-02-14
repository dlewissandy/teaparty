import json
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from teaparty_app.config import settings


connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _run_lightweight_migrations()
    _ensure_custom_tool_tables()
    _ensure_cross_group_task_tables()
    _ensure_llm_usage_table()
    _ensure_agent_memory_table()


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

    user_columns = _sqlite_column_names("users")
    workgroup_columns = _sqlite_column_names("workgroups")
    conversation_columns = _sqlite_column_names("conversations")
    agent_columns = _sqlite_column_names("agents")
    with engine.begin() as conn:
        if "preferences" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN preferences JSON DEFAULT '{}' NOT NULL"))

        if "is_discoverable" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN is_discoverable BOOLEAN DEFAULT 0 NOT NULL"))
        if "service_description" not in workgroup_columns:
            conn.execute(text("ALTER TABLE workgroups ADD COLUMN service_description TEXT DEFAULT '' NOT NULL"))

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


def _ensure_custom_tool_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS tool_definitions ("
                "id TEXT PRIMARY KEY, "
                "workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "created_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "name TEXT NOT NULL, "
                "description TEXT DEFAULT '' NOT NULL, "
                "tool_type TEXT DEFAULT 'prompt' NOT NULL, "
                "prompt_template TEXT DEFAULT '' NOT NULL, "
                "webhook_url TEXT DEFAULT '' NOT NULL, "
                "webhook_method TEXT DEFAULT 'POST' NOT NULL, "
                "webhook_headers JSON DEFAULT '{}' NOT NULL, "
                "webhook_timeout_seconds INTEGER DEFAULT 30 NOT NULL, "
                "input_schema JSON DEFAULT '{}' NOT NULL, "
                "is_shared BOOLEAN DEFAULT 0 NOT NULL, "
                "enabled BOOLEAN DEFAULT 1 NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS tool_grants ("
                "id TEXT PRIMARY KEY, "
                "tool_definition_id TEXT NOT NULL REFERENCES tool_definitions(id), "
                "grantee_workgroup_id TEXT NOT NULL REFERENCES workgroups(id), "
                "granted_by_user_id TEXT NOT NULL REFERENCES users(id), "
                "created_at DATETIME NOT NULL, "
                "UNIQUE(tool_definition_id, grantee_workgroup_id)"
                ")"
            )
        )


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


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
