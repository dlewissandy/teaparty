"""Load and apply workgroup templates from YAML seed files."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

import yaml

logger = logging.getLogger(__name__)

TEMPLATE_ROOT = ".templates/organizations/default/workgroups"
TEMPLATE_WORKGROUP_FILENAME = "workgroup.json"
WORKGROUP_STORAGE_ROOT = "workgroups"


class WorkgroupTemplateFile(TypedDict):
    path: str
    content: str


class WorkgroupTemplateAgent(TypedDict):
    name: str
    description: str
    role: str
    personality: str
    backstory: str
    model: str
    temperature: float
    tool_names: list[str]


class WorkgroupTemplate(TypedDict):
    key: str
    name: str
    description: str
    files: list[WorkgroupTemplateFile]
    agents: list[WorkgroupTemplateAgent]


_YAML_TEMPLATES_DIR = Path(__file__).parent.parent / "seeds" / "templates"

_cached_templates: list[WorkgroupTemplate] | None = None


def _load_templates_from_yaml() -> list[WorkgroupTemplate]:
    templates: list[WorkgroupTemplate] = []
    seen_keys: set[str] = set()

    if not _YAML_TEMPLATES_DIR.is_dir():
        logger.warning("YAML templates directory not found: %s", _YAML_TEMPLATES_DIR)
        return templates

    for yaml_path in sorted(_YAML_TEMPLATES_DIR.glob("*.yaml")):
        try:
            with open(yaml_path) as fh:
                data = yaml.safe_load(fh)
        except Exception:
            logger.exception("Failed to load template YAML: %s", yaml_path)
            continue

        if not isinstance(data, dict):
            continue

        normalized = _normalize_storage_template(data, fallback_key=yaml_path.stem)
        if not normalized:
            continue

        if normalized["key"] in seen_keys:
            continue
        seen_keys.add(normalized["key"])
        templates.append(normalized)

    return templates


def _clone_template(template: WorkgroupTemplate) -> WorkgroupTemplate:
    return {
        "key": template["key"],
        "name": template["name"],
        "description": template["description"],
        "files": [{"path": item["path"], "content": item["content"]} for item in template["files"]],
        "agents": [
            {
                "name": item["name"],
                "description": item["description"],
                "role": item["role"],
                "personality": item["personality"],
                "backstory": item["backstory"],
                "model": item["model"],
                "temperature": item["temperature"],
                "tool_names": list(item["tool_names"]),
            }
            for item in template["agents"]
        ],
    }


def list_workgroup_templates() -> list[WorkgroupTemplate]:
    global _cached_templates
    if _cached_templates is None:
        _cached_templates = _load_templates_from_yaml()
    return [_clone_template(template) for template in _cached_templates]


def get_workgroup_template(template_key: str | None) -> WorkgroupTemplate | None:
    if not template_key:
        return None

    normalized_key = template_key.strip()
    if not normalized_key:
        return None

    for template in list_workgroup_templates():
        if template["key"] == normalized_key:
            return template
    return None


def _coerce_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _normalize_relative_file_path(path: str) -> str:
    cleaned = path.replace("\\", "/")
    parts = []
    for part in cleaned.split("/"):
        token = part.strip()
        if not token or token == ".":
            continue
        if token == "..":
            continue
        parts.append(token)
    return "/".join(parts)


def _normalize_storage_path(path: str) -> str:
    return re.sub(r"/+", "/", path.replace("\\", "/")).lstrip("/")


def _normalize_storage_template_file(value: object) -> WorkgroupTemplateFile | None:
    if not isinstance(value, dict):
        return None
    raw_path = str(value.get("path", "")).strip()
    path = _normalize_relative_file_path(raw_path)
    if not path:
        return None
    content_value = value.get("content", "")
    content = content_value if isinstance(content_value, str) else str(content_value or "")
    return {"path": path, "content": content}


def _normalize_storage_template_agent(value: object) -> WorkgroupTemplateAgent | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name", "")).strip()
    if not name:
        return None

    tools_raw = value.get("tool_names", [])
    tool_names: list[str] = []
    if isinstance(tools_raw, list):
        seen_tools: set[str] = set()
        for raw_tool in tools_raw:
            tool = str(raw_tool or "").strip()
            if not tool or tool in seen_tools:
                continue
            seen_tools.add(tool)
            tool_names.append(tool)

    return {
        "name": name,
        "description": str(value.get("description", "")),
        "role": str(value.get("role", "")),
        "personality": str(value.get("personality", "Professional and concise")) or "Professional and concise",
        "backstory": str(value.get("backstory", "")),
        "model": str(value.get("model", "sonnet")) or "sonnet",
        "temperature": _coerce_float(value.get("temperature"), 0.7, 0.0, 2.0),
        "tool_names": tool_names,
    }


def _normalize_storage_template(value: object, fallback_key: str | None = None) -> WorkgroupTemplate | None:
    if not isinstance(value, dict):
        return None

    key = str(value.get("key", fallback_key or "")).strip()
    name = str(value.get("name", key)).strip()
    if not key or not name:
        return None

    files_raw = value.get("files", [])
    files: list[WorkgroupTemplateFile] = []
    seen_paths: set[str] = set()
    if isinstance(files_raw, list):
        for item in files_raw:
            normalized = _normalize_storage_template_file(item)
            if not normalized:
                continue
            path = normalized["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            files.append(normalized)

    agents_raw = value.get("agents", [])
    agents: list[WorkgroupTemplateAgent] = []
    seen_names: set[str] = set()
    if isinstance(agents_raw, list):
        for item in agents_raw:
            normalized = _normalize_storage_template_agent(item)
            if not normalized:
                continue
            lowered = normalized["name"].lower()
            if lowered in seen_names:
                continue
            seen_names.add(lowered)
            agents.append(normalized)

    return {
        "key": key,
        "name": name,
        "description": str(value.get("description", "")),
        "files": files,
        "agents": agents,
    }


def _agent_filename_base(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return normalized or "agent"


def template_storage_files(templates: list[WorkgroupTemplate] | None = None) -> list[WorkgroupTemplateFile]:
    catalog = templates if templates is not None else list_workgroup_templates()
    rows = sorted(catalog, key=lambda item: item["key"])
    files: list[WorkgroupTemplateFile] = [
        {
            "path": ".templates/organizations/default/organization.json",
            "content": json.dumps(
                {"key": "default", "name": "Default", "description": "Default organization template"},
                indent=2,
                sort_keys=True,
            ),
        },
        {
            "path": f"{TEMPLATE_ROOT}/README.md",
            "content": (
                "# Workgroup Templates\n\n"
                "Each template lives in its own folder:\n"
                f"- `{TEMPLATE_ROOT}/<template>/{TEMPLATE_WORKGROUP_FILENAME}`\n"
                f"- `{TEMPLATE_ROOT}/<template>/agents/*.json`\n"
                f"- `{TEMPLATE_ROOT}/<template>/files/**`\n"
            ),
        },
    ]

    for template in rows:
        base_path = f"{TEMPLATE_ROOT}/{template['key']}"
        config_payload = {
            "key": template["key"],
            "name": template["name"],
            "description": template["description"],
        }
        files.append(
            {
                "path": f"{base_path}/{TEMPLATE_WORKGROUP_FILENAME}",
                "content": json.dumps(config_payload, indent=2, sort_keys=True),
            }
        )

        used_agent_filenames: set[str] = set()
        for agent in template["agents"]:
            stem = _agent_filename_base(agent["name"])
            candidate = stem
            suffix = 2
            while candidate in used_agent_filenames:
                candidate = f"{stem}_{suffix}"
                suffix += 1
            used_agent_filenames.add(candidate)
            files.append(
                {
                    "path": f"{base_path}/agents/{candidate}.json",
                    "content": json.dumps(agent, indent=2, sort_keys=True),
                }
            )

        seen_file_paths: set[str] = set()
        for file_entry in template["files"]:
            relative_path = _normalize_relative_file_path(file_entry["path"])
            if not relative_path or relative_path in seen_file_paths:
                continue
            seen_file_paths.add(relative_path)
            files.append(
                {
                    "path": f"{base_path}/files/{relative_path}",
                    "content": file_entry["content"],
                }
            )

    return files


def _templates_from_structured_storage(entries_by_path: dict[str, str]) -> list[WorkgroupTemplate]:
    _LEGACY_TEMPLATE_ROOT = ".templates/workgroups"
    config_pattern = re.compile(
        r"^(?P<root>"
        + re.escape(TEMPLATE_ROOT)
        + r"|"
        + re.escape(_LEGACY_TEMPLATE_ROOT)
        + r")/(?P<folder>[^/]+)/(?:"
        + re.escape(TEMPLATE_WORKGROUP_FILENAME)
        + r"|config\.json)$"
    )

    # Collect (folder, root) pairs — prefer new root over legacy
    folder_roots: dict[str, str] = {}
    for path in entries_by_path:
        match = config_pattern.match(path)
        if match:
            folder = match.group("folder")
            root = match.group("root")
            if folder not in folder_roots or root == TEMPLATE_ROOT:
                folder_roots[folder] = root
    template_folders = sorted(folder_roots.keys())

    parsed: list[WorkgroupTemplate] = []
    seen_keys: set[str] = set()
    for folder in template_folders:
        root = folder_roots[folder]
        config_path = f"{root}/{folder}/{TEMPLATE_WORKGROUP_FILENAME}"
        legacy_config_path = f"{root}/{folder}/config.json"
        config_payload: object = {}
        try:
            config_payload = json.loads(
                entries_by_path.get(config_path, entries_by_path.get(legacy_config_path, "{}")) or "{}"
            )
        except (TypeError, ValueError):
            config_payload = {}
        if not isinstance(config_payload, dict):
            config_payload = {}

        template_key = str(config_payload.get("key", folder)).strip() or folder
        template_name = str(config_payload.get("name", template_key)).strip() or template_key
        description = str(config_payload.get("description", ""))

        agent_prefix = f"{root}/{folder}/agents/"
        agents: list[WorkgroupTemplateAgent] = []
        seen_agent_names: set[str] = set()
        for path, content in sorted(entries_by_path.items()):
            if not path.startswith(agent_prefix) or not path.endswith(".json"):
                continue
            try:
                payload = json.loads(content or "{}")
            except (TypeError, ValueError):
                continue
            normalized_agent = _normalize_storage_template_agent(payload)
            if not normalized_agent:
                continue
            lowered = normalized_agent["name"].lower()
            if lowered in seen_agent_names:
                continue
            seen_agent_names.add(lowered)
            agents.append(normalized_agent)

        if not agents and isinstance(config_payload.get("agents"), list):
            for item in config_payload["agents"]:
                normalized_agent = _normalize_storage_template_agent(item)
                if not normalized_agent:
                    continue
                lowered = normalized_agent["name"].lower()
                if lowered in seen_agent_names:
                    continue
                seen_agent_names.add(lowered)
                agents.append(normalized_agent)

        files_prefix = f"{root}/{folder}/files/"
        files: list[WorkgroupTemplateFile] = []
        seen_file_paths: set[str] = set()
        for path, content in sorted(entries_by_path.items()):
            if not path.startswith(files_prefix):
                continue
            relative = _normalize_relative_file_path(path[len(files_prefix) :])
            if not relative or relative in seen_file_paths:
                continue
            seen_file_paths.add(relative)
            files.append({"path": relative, "content": content})

        if not files and isinstance(config_payload.get("files"), list):
            for item in config_payload["files"]:
                normalized_file = _normalize_storage_template_file(item)
                if not normalized_file:
                    continue
                relative = normalized_file["path"]
                if relative in seen_file_paths:
                    continue
                seen_file_paths.add(relative)
                files.append(normalized_file)

        template: WorkgroupTemplate = {
            "key": template_key,
            "name": template_name,
            "description": description,
            "files": files,
            "agents": agents,
        }
        if template["key"] in seen_keys:
            continue
        seen_keys.add(template["key"])
        parsed.append(template)

    return sorted(parsed, key=lambda item: item["key"])


def _templates_from_legacy_storage(entries_by_path: dict[str, str]) -> list[WorkgroupTemplate]:
    parsed: list[WorkgroupTemplate] = []
    seen_keys: set[str] = set()
    for path, content in sorted(entries_by_path.items()):
        if not path.startswith("templates/") or not path.endswith(".json"):
            continue
        if path.endswith("/README.json") or path.endswith("README.json"):
            continue

        try:
            payload = json.loads(content or "{}")
        except (TypeError, ValueError):
            continue

        normalized = _normalize_storage_template(payload)
        if not normalized:
            continue
        key = normalized["key"]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        parsed.append(normalized)
    return parsed


def templates_from_storage_files(raw_files: list[dict[str, str]]) -> list[WorkgroupTemplate]:
    entries_by_path: dict[str, str] = {}
    for raw_entry in raw_files:
        if not isinstance(raw_entry, dict):
            continue
        raw_path = str(raw_entry.get("path", "")).strip()
        path = _normalize_storage_path(raw_path)
        if not path:
            continue
        if path in entries_by_path:
            continue
        raw_content = raw_entry.get("content", "")
        content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        entries_by_path[path] = content

    parsed = _templates_from_structured_storage(entries_by_path)
    if parsed:
        return parsed

    parsed = _templates_from_legacy_storage(entries_by_path)
    return sorted(parsed, key=lambda item: item["key"])


def _is_workgroup_storage_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return normalized == f"{WORKGROUP_STORAGE_ROOT}/README.md" or normalized.startswith(f"{WORKGROUP_STORAGE_ROOT}/")


ORG_STORAGE_PATHS_PREFIXES = ("organization.json", "teams/", "members/")


def _is_org_storage_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("/")
    return any(normalized == prefix or normalized.startswith(prefix) for prefix in ORG_STORAGE_PATHS_PREFIXES)


def org_storage_files(
    org: dict,
    workgroups: list[dict],
    agents_by_workgroup: dict[str, list[dict]],
    members: list[dict],
    members_by_workgroup: dict[str, list[dict]] | None = None,
) -> list[WorkgroupTemplateFile]:
    rows = sorted(workgroups, key=lambda item: item.get("id", ""))
    files: list[WorkgroupTemplateFile] = []

    # organization.json
    team_refs = [{"id": wg.get("id", ""), "name": wg.get("name", "")} for wg in rows]
    member_refs = [{"user_id": m.get("user_id", ""), "role": m.get("role", "")} for m in members]
    org_payload = {
        "id": org.get("id", ""),
        "name": org.get("name", ""),
        "description": org.get("description", ""),
        "owner_id": org.get("owner_id", ""),
        "teams": team_refs,
        "members": member_refs,
    }
    files.append({
        "path": "organization.json",
        "content": json.dumps(org_payload, indent=2, default=str),
    })

    # teams/README.md
    catalog_lines = ["# Teams\n\n"]
    for wg in rows:
        catalog_lines.append(f"- **{wg.get('name', '')}** — `teams/{wg.get('id', '')}/`\n")
    files.append({"path": "teams/README.md", "content": "".join(catalog_lines)})

    # Per-team files
    for wg in rows:
        wg_id = wg.get("id", "")
        base_path = f"teams/{wg_id}"
        agents = agents_by_workgroup.get(wg_id, [])

        wg_members = (members_by_workgroup or {}).get(wg_id, [])
        member_refs_wg = [{"user_id": m.get("user_id", ""), "role": m.get("role", "")} for m in wg_members]
        agent_refs = [{"id": a.get("id", ""), "name": a.get("name", ""), "role": a.get("role", "")} for a in agents]
        team_payload = {
            "id": wg_id,
            "name": wg.get("name", ""),
            "owner_id": wg.get("owner_id", ""),
            "is_discoverable": wg.get("is_discoverable", False),
            "service_description": wg.get("service_description", ""),
            "created_at": wg.get("created_at", ""),
            "members": member_refs_wg,
            "agents": agent_refs,
        }
        files.append({
            "path": f"{base_path}/team.json",
            "content": json.dumps(team_payload, indent=2, default=str),
        })

        used_agent_filenames: set[str] = set()
        for agent in agents:
            stem = _agent_filename_base(agent.get("name", ""))
            candidate = stem
            suffix = 2
            while candidate in used_agent_filenames:
                candidate = f"{stem}_{suffix}"
                suffix += 1
            used_agent_filenames.add(candidate)

            agent_payload = {
                "id": agent.get("id", ""),
                "name": agent.get("name", ""),
                "description": agent.get("description", ""),
                "role": agent.get("role", ""),
                "personality": agent.get("personality", ""),
                "backstory": agent.get("backstory", ""),
                "model": agent.get("model", ""),
                "temperature": agent.get("temperature", 0.7),
                "tool_names": agent.get("tool_names", []),
            }
            files.append({
                "path": f"{base_path}/agents/{candidate}/agent.json",
                "content": json.dumps(agent_payload, indent=2, default=str),
            })

    # Per-member files
    for m in sorted(members, key=lambda x: x.get("user_id", "")):
        uid = m.get("user_id", "")
        member_payload = {
            "user_id": uid,
            "name": m.get("name", ""),
            "email": m.get("email", ""),
            "role": m.get("role", ""),
        }
        files.append({
            "path": f"members/{uid}/member.json",
            "content": json.dumps(member_payload, indent=2, default=str),
        })

    return files


def workgroup_storage_files(
    workgroups: list[dict],
    agents_by_workgroup: dict[str, list[dict]],
    members_by_workgroup: dict[str, list[dict]] | None = None,
) -> list[WorkgroupTemplateFile]:
    rows = sorted(workgroups, key=lambda item: item.get("id", ""))
    files: list[WorkgroupTemplateFile] = []

    catalog_lines = ["# Workgroups\n\n"]
    for wg in rows:
        catalog_lines.append(f"- **{wg.get('name', '')}** — `{WORKGROUP_STORAGE_ROOT}/{wg.get('id', '')}/`\n")
    files.append({"path": f"{WORKGROUP_STORAGE_ROOT}/README.md", "content": "".join(catalog_lines)})

    for wg in rows:
        wg_id = wg.get("id", "")
        base_path = f"{WORKGROUP_STORAGE_ROOT}/{wg_id}"
        agents = agents_by_workgroup.get(wg_id, [])

        members = (members_by_workgroup or {}).get(wg_id, [])
        member_refs = [{"user_id": m.get("user_id", ""), "role": m.get("role", "")} for m in members]
        agent_refs = [{"id": a.get("id", ""), "name": a.get("name", ""), "role": a.get("role", "")} for a in agents]
        wg_payload = {
            "id": wg_id,
            "name": wg.get("name", ""),
            "owner_id": wg.get("owner_id", ""),
            "is_discoverable": wg.get("is_discoverable", False),
            "service_description": wg.get("service_description", ""),
            "created_at": wg.get("created_at", ""),
            "members": member_refs,
            "agents": agent_refs,
        }
        files.append({
            "path": f"{base_path}/workgroup.json",
            "content": json.dumps(wg_payload, indent=2, default=str),
        })

        used_agent_filenames: set[str] = set()
        for agent in agents:
            stem = _agent_filename_base(agent.get("name", ""))
            candidate = stem
            suffix = 2
            while candidate in used_agent_filenames:
                candidate = f"{stem}_{suffix}"
                suffix += 1
            used_agent_filenames.add(candidate)

            agent_payload = {
                "id": agent.get("id", ""),
                "name": agent.get("name", ""),
                "description": agent.get("description", ""),
                "role": agent.get("role", ""),
                "personality": agent.get("personality", ""),
                "backstory": agent.get("backstory", ""),
                "model": agent.get("model", ""),
                "temperature": agent.get("temperature", 0.7),
                "tool_names": agent.get("tool_names", []),
            }
            files.append({
                "path": f"{base_path}/agents/{candidate}.json",
                "content": json.dumps(agent_payload, indent=2, default=str),
            })

    return files
