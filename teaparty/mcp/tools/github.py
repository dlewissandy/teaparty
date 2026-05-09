"""MCP tool layer for GitHub Projects V2 boards and issue management.

Two families of tools, one runner.

* Issue management — list_milestones, list_milestone_issues,
  read_issue, create_issue, close_issue, reopen_issue,
  set_issue_milestone, set_issue_labels, list_issue_comments,
  create_comment.  Wraps the ``gh`` CLI with internal pagination.
* Projects V2 board — list_project_boards, add_issue_to_board,
  set_board_status, read_board_status.  Wraps ``gh api graphql``.

The granularity contract from issue #427:

* Callers pass issue *numbers* and status *names*; never opaque
  GraphQL global ids or option ids.  The mapping lives here.
* No ``repo`` parameter on any tool.  Repo identity is resolved
  from the current project's git remote at call time.
* Listings paginate internally; no ``limit``, ``cursor``, or
  ``page`` exposed.

Handlers accept ``gh_runner`` and ``repo_resolver`` keyword arguments
for tests; production calls go through the module-level defaults
which shell out to ``gh`` and ``git``.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable, Iterable


# ── Defaults: real subprocess wrappers ─────────────────────────────────────

def _run_gh(*args: str, input_text: str = '') -> str:
    """Run ``gh`` with the given argv and return stdout.

    Surfaces ``gh``'s own stderr verbatim on non-zero exit so error
    messages are actionable (auth failure, rate limit, missing repo)
    rather than a generic ``CalledProcessError``.
    """
    proc = subprocess.run(
        ['gh', *args],
        input=input_text or None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip()
        raise RuntimeError(f'gh {" ".join(args)!r} failed: {stderr}')
    return proc.stdout


_REMOTE_URL_HTTPS = re.compile(
    r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
)
_REMOTE_URL_SSH = re.compile(
    r'^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$'
)


def _parse_remote_url(url: str) -> tuple[str, str]:
    """Parse a GitHub remote URL into ``(owner, repo)``.

    Accepts ``https://github.com/owner/repo[.git]`` and
    ``git@github.com:owner/repo[.git]`` forms.  Raises ``ValueError``
    for any non-GitHub remote — silently falling back to a wrong
    owner/repo would corrupt state without an error.
    """
    url = url.strip()
    m = _REMOTE_URL_HTTPS.match(url) or _REMOTE_URL_SSH.match(url)
    if not m:
        raise ValueError(
            f'cannot resolve GitHub repo from remote URL {url!r}: '
            f'only github.com remotes are supported',
        )
    return m.group(1), m.group(2)


def _resolve_repo() -> tuple[str, str]:
    """Return ``(owner, repo)`` from the current cwd's git remote."""
    proc = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            'cannot resolve GitHub repo: no git remote "origin" found '
            'in the current working directory',
        )
    return _parse_remote_url(proc.stdout)


# Type alias for the injectable runner.
GhRunner = Callable[..., str]
RepoResolver = Callable[[], tuple[str, str]]


def _gh_api(
    path: str,
    *extra: str,
    gh_runner: GhRunner,
    paginate: bool = False,
) -> str:
    """Call ``gh api`` for a REST endpoint and return raw JSON stdout.

    ``--paginate`` makes ``gh`` follow ``Link: rel="next"`` until
    exhausted; required for any listing where the result might
    exceed one page (30 items by default).
    """
    args = ['api', '-H', 'Accept: application/vnd.github+json']
    if paginate:
        args.append('--paginate')
    args.append(path)
    args.extend(extra)
    return gh_runner(*args)


def _gh_graphql(query: str, *, gh_runner: GhRunner, **variables: Any) -> dict:
    """Call ``gh api graphql`` with the given query and variables.

    Returns the parsed JSON response.  Variables are passed via
    ``-F key=value`` (numeric/bool) or ``-f key=value`` (string)
    flags; ``gh`` handles the JSON-encoding.
    """
    args = ['api', 'graphql', '-f', f'query={query}']
    for k, v in variables.items():
        if isinstance(v, bool):
            args.extend(['-F', f'{k}={"true" if v else "false"}'])
        elif isinstance(v, int):
            args.extend(['-F', f'{k}={v}'])
        else:
            args.extend(['-f', f'{k}={v}'])
    out = gh_runner(*args)
    return json.loads(out)


# ── Issue management ───────────────────────────────────────────────────────

def list_milestones_handler(
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Return all milestones (open and closed) as a JSON array.

    Each entry: ``{number, title, state, open_issues, due_on}``.
    """
    owner, repo = repo_resolver()
    out = _gh_api(
        f'/repos/{owner}/{repo}/milestones?state=all&per_page=100',
        gh_runner=gh_runner, paginate=True,
    )
    raw = json.loads(out) if out.strip() else []
    result = [{
        'number': m.get('number'),
        'title': m.get('title'),
        'state': m.get('state'),
        'open_issues': m.get('open_issues'),
        'due_on': m.get('due_on'),
    } for m in raw]
    return json.dumps(result)


def list_milestone_issues_handler(
    milestone: str,
    state: str = 'all',
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """List issues attached to a milestone.  ``state`` is ``open|closed|all``.

    First resolves the milestone name to its number (the REST issues
    endpoint accepts only milestone numbers, not names), then walks
    the issues endpoint with ``--paginate`` so all pages return.
    """
    if state not in ('open', 'closed', 'all'):
        return json.dumps({'error': f'invalid state {state!r}; must be open|closed|all'})
    owner, repo = repo_resolver()

    milestone_number = _resolve_milestone_number(
        owner, repo, milestone, gh_runner=gh_runner,
    )
    if milestone_number is None:
        return json.dumps({'error': f'unknown milestone {milestone!r}'})

    raw = _gh_api(
        f'/repos/{owner}/{repo}/issues'
        f'?milestone={milestone_number}&state={state}&per_page=100',
        gh_runner=gh_runner, paginate=True,
    )
    items = json.loads(raw) if raw.strip() else []
    # The issues endpoint returns both issues and PRs; filter PRs out
    # so the caller sees only issues, matching the gh issue list shape.
    issues = [i for i in items if not i.get('pull_request')]
    result = [{
        'number': i.get('number'),
        'title': i.get('title'),
        'state': i.get('state'),
        'labels': i.get('labels', []),
        'milestone': i.get('milestone'),
        'assignees': i.get('assignees', []),
    } for i in issues]
    return json.dumps(result)


def _resolve_milestone_number(
    owner: str, repo: str, milestone: str,
    *,
    gh_runner: GhRunner,
) -> int | None:
    """Look up a milestone number by title (or accept a numeric string)."""
    if milestone.isdigit():
        return int(milestone)
    out = _gh_api(
        f'/repos/{owner}/{repo}/milestones?state=all&per_page=100',
        gh_runner=gh_runner, paginate=True,
    )
    raw = json.loads(out) if out.strip() else []
    for m in raw:
        if m.get('title') == milestone:
            return m.get('number')
    return None


def read_issue_handler(
    number: int,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Return the issue's number, title, body, state, labels, milestone, assignees."""
    owner, repo = repo_resolver()
    out = gh_runner(
        'issue', 'view', str(number),
        '--repo', f'{owner}/{repo}',
        '--json', 'number,title,body,state,labels,milestone,assignees',
    )
    return out.strip()


def create_issue_handler(
    title: str,
    body: str,
    milestone: str = '',
    labels: list[str] | None = None,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Create an issue.  Returns ``{"number": N}`` JSON."""
    owner, repo = repo_resolver()
    args: list[str] = [
        'issue', 'create',
        '--repo', f'{owner}/{repo}',
        '--title', title,
        '--body', body,
    ]
    if milestone:
        args.extend(['--milestone', milestone])
    for label in (labels or []):
        args.extend(['--label', label])
    out = gh_runner(*args)
    # gh prints the new issue URL on success; trailing path component is
    # the new issue number.
    m = re.search(r'/issues/(\d+)', out)
    if not m:
        return json.dumps({'error': f'could not parse issue URL from gh output: {out!r}'})
    return json.dumps({'number': int(m.group(1))})


def close_issue_handler(
    number: int,
    comment: str = '',
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Close an issue, optionally with a resolution comment."""
    owner, repo = repo_resolver()
    args = ['issue', 'close', str(number), '--repo', f'{owner}/{repo}']
    if comment:
        args.extend(['-c', comment])
    gh_runner(*args)
    return json.dumps({'closed': number})


def reopen_issue_handler(
    number: int,
    comment: str = '',
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Reopen an issue, optionally with a comment."""
    owner, repo = repo_resolver()
    args = ['issue', 'reopen', str(number), '--repo', f'{owner}/{repo}']
    if comment:
        args.extend(['-c', comment])
    gh_runner(*args)
    return json.dumps({'reopened': number})


def set_issue_milestone_handler(
    number: int,
    milestone: str,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Set the milestone for an issue."""
    owner, repo = repo_resolver()
    gh_runner(
        'issue', 'edit', str(number),
        '--repo', f'{owner}/{repo}',
        '--milestone', milestone,
    )
    return json.dumps({'number': number, 'milestone': milestone})


def set_issue_labels_handler(
    number: int,
    labels: list[str],
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Replace the label set on an issue.

    Uses ``PUT /repos/{owner}/{repo}/issues/{N}/labels`` for atomic
    replacement; ``--add-label`` / ``--remove-label`` would require
    a read-then-diff and is racier.
    """
    owner, repo = repo_resolver()
    args: list[str] = [
        'api', '-X', 'PUT',
        f'/repos/{owner}/{repo}/issues/{number}/labels',
    ]
    for label in labels:
        args.extend(['-f', f'labels[]={label}'])
    out = gh_runner(*args)
    return out.strip() or json.dumps({'number': number, 'labels': labels})


def list_issue_comments_handler(
    number: int,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Return all comments on an issue (paginated internally)."""
    owner, repo = repo_resolver()
    out = _gh_api(
        f'/repos/{owner}/{repo}/issues/{number}/comments?per_page=100',
        gh_runner=gh_runner, paginate=True,
    )
    return out.strip() or '[]'


def create_comment_handler(
    number: int,
    body: str,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Post a comment to an issue."""
    owner, repo = repo_resolver()
    out = gh_runner(
        'issue', 'comment', str(number),
        '--repo', f'{owner}/{repo}',
        '--body', body,
    )
    return out.strip() or json.dumps({'number': number, 'commented': True})


# ── Projects V2 board ──────────────────────────────────────────────────────

# GraphQL fragment shared by the board-discovery queries.  Includes all
# fields a Status field declares so callers can resolve a status name to
# an option id at call time without a second round-trip.
_BOARD_FIELDS_FRAGMENT = """
fields(first: 50) {
  nodes {
    ... on ProjectV2SingleSelectField {
      id
      name
      options {
        id
        name
      }
    }
  }
}
""".strip()


def _query_boards(
    owner: str, repo: str,
    *,
    gh_runner: GhRunner,
    issue_number: int | None = None,
) -> dict:
    """Fetch all Projects V2 boards linked to the repo, plus optionally
    the issue's GraphQL node id in the same query."""
    issue_block = (
        f'issue(number: {issue_number}) {{ id }}'
        if issue_number is not None else ''
    )
    query = f"""
    query {{
      repository(owner: "{owner}", name: "{repo}") {{
        projectsV2(first: 50) {{
          pageInfo {{ hasNextPage endCursor }}
          nodes {{
            id
            number
            title
            {_BOARD_FIELDS_FRAGMENT}
          }}
        }}
        {issue_block}
      }}
    }}
    """
    return _gh_graphql(query, gh_runner=gh_runner)


def _extract_boards(response: dict) -> list[dict]:
    """Pull the boards array out of a board-query response, with the
    Status field's option metadata flattened to ``status_options``."""
    repo_node = (response.get('data') or {}).get('repository') or {}
    nodes = ((repo_node.get('projectsV2') or {}).get('nodes')) or []
    boards = []
    for node in nodes:
        status_options: list[dict] = []
        for f in (((node.get('fields') or {}).get('nodes')) or []):
            if not f:
                continue
            if f.get('name') == 'Status' and f.get('options'):
                status_options = [
                    {'id': o.get('id'), 'name': o.get('name')}
                    for o in f.get('options', [])
                ]
        boards.append({
            'id': node.get('id'),
            'number': node.get('number'),
            'title': node.get('title'),
            'status_field_id': next(
                (f.get('id') for f in (((node.get('fields') or {}).get('nodes')) or [])
                 if f and f.get('name') == 'Status'),
                None,
            ),
            'status_options': status_options,
        })
    return boards


def _pick_sprint_board(boards: list[dict]) -> dict | None:
    """Return the unique board whose Status field carries the canonical
    sprint set (Backlog/Approved/In Progress/Done/Won't Do), or
    ``None`` if no such board exists.

    A repo can have multiple linked Projects V2 boards; the sprint
    board is identified by its option set, not by ordering.  Refusing
    to substitute when the canonical board is missing is intentional —
    silently writing Status to a different board would corrupt state
    invisibly.
    """
    canonical = {'Backlog', 'Approved', 'In Progress', 'Done', "Won't Do"}
    for b in boards:
        names = {o.get('name') for o in b.get('status_options', [])}
        if canonical.issubset(names):
            return b
    return None


_NO_SPRINT_BOARD_ERROR = (
    'no sprint board found: no Projects V2 board declares the '
    "canonical Status option set "
    "(Backlog, Approved, In Progress, Done, Won't Do)"
)


def list_project_boards_handler(
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Return Projects V2 boards in the repo with Status field metadata."""
    owner, repo = repo_resolver()
    response = _query_boards(owner, repo, gh_runner=gh_runner)
    boards = _extract_boards(response)
    return json.dumps(boards)


def _query_board_items(
    owner: str, repo: str, board_number: int,
    *,
    gh_runner: GhRunner,
    include_field_values: bool = False,
) -> Iterable[dict]:
    """Yield every item on a board, paginated.

    When ``include_field_values=True``, each item carries its
    ``fieldValues`` (used by ``read_board_status``).  Without that
    fragment the query is cheaper and is enough for ``set_board_status``,
    which only needs the item id.
    """
    field_values_block = """
    fieldValues(first: 20) {
      nodes {
        ... on ProjectV2ItemFieldSingleSelectValue {
          name
          field {
            ... on ProjectV2SingleSelectField { name }
          }
        }
      }
    }
    """ if include_field_values else ''

    cursor = ''
    while True:
        after = f', after: "{cursor}"' if cursor else ''
        query = f"""
        query {{
          repository(owner: "{owner}", name: "{repo}") {{
            projectV2(number: {board_number}) {{
              items(first: 100{after}) {{
                pageInfo {{ hasNextPage endCursor }}
                nodes {{
                  id
                  content {{
                    ... on Issue {{ number }}
                  }}
                  {field_values_block}
                }}
              }}
            }}
          }}
        }}
        """
        response = _gh_graphql(query, gh_runner=gh_runner)
        proj = (((response.get('data') or {}).get('repository') or {})
                .get('projectV2') or {})
        items = proj.get('items') or {}
        for node in items.get('nodes') or []:
            yield node
        page = items.get('pageInfo') or {}
        if not page.get('hasNextPage'):
            return
        cursor = page.get('endCursor') or ''
        if not cursor:
            return


def add_issue_to_board_handler(
    number: int,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Add an issue to the sprint board.  Idempotent — the GitHub API
    returns the existing item id when called for an issue already on
    the board, so repeat calls return the same id."""
    owner, repo = repo_resolver()
    response = _query_boards(
        owner, repo, gh_runner=gh_runner, issue_number=number,
    )
    boards = _extract_boards(response)
    board = _pick_sprint_board(boards)
    if board is None:
        return json.dumps({'error': _NO_SPRINT_BOARD_ERROR})

    repo_node = (response.get('data') or {}).get('repository') or {}
    issue_node = repo_node.get('issue') or {}
    content_id = issue_node.get('id')
    if not content_id:
        return json.dumps({'error': f'issue #{number} not found in repo'})

    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
        item { id }
      }
    }
    """
    result = _gh_graphql(
        mutation, gh_runner=gh_runner,
        projectId=board['id'], contentId=content_id,
    )
    item = (((result.get('data') or {}).get('addProjectV2ItemById') or {})
            .get('item') or {})
    return json.dumps({'item_id': item.get('id'), 'number': number})


def set_board_status_handler(
    number: int,
    status: str,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Set the Status field for an issue's board item by status *name*.

    Resolves the option id from the board's own metadata at call time
    so a board reconfigured upstream is handled correctly.
    """
    owner, repo = repo_resolver()
    response = _query_boards(owner, repo, gh_runner=gh_runner)
    boards = _extract_boards(response)
    board = _pick_sprint_board(boards)
    if board is None:
        return json.dumps({'error': _NO_SPRINT_BOARD_ERROR})

    option = next(
        (o for o in board.get('status_options', [])
         if o.get('name') == status),
        None,
    )
    if option is None:
        valid = [o.get('name') for o in board.get('status_options', [])]
        return json.dumps({
            'error': f'unknown status name {status!r}; '
                     f'valid status names on this board: {valid}',
        })

    item_id = None
    for item in _query_board_items(
        owner, repo, board['number'], gh_runner=gh_runner,
    ):
        content = item.get('content') or {}
        if content.get('number') == number:
            item_id = item.get('id')
            break
    if item_id is None:
        return json.dumps({
            'error': f'issue #{number} is not on the board; '
                     'add it with add_issue_to_board first',
        })

    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId,
        itemId: $itemId,
        fieldId: $fieldId,
        value: { singleSelectOptionId: $optionId }
      }) {
        projectV2Item { id }
      }
    }
    """
    _gh_graphql(
        mutation, gh_runner=gh_runner,
        projectId=board['id'],
        itemId=item_id,
        fieldId=board['status_field_id'],
        optionId=option['id'],
    )
    return json.dumps({
        'number': number, 'status': status, 'item_id': item_id,
    })


def read_board_status_handler(
    number: int,
    *,
    gh_runner: GhRunner = _run_gh,
    repo_resolver: RepoResolver = _resolve_repo,
) -> str:
    """Return the Status field name for an issue's item, or ``None``."""
    owner, repo = repo_resolver()
    response = _query_boards(owner, repo, gh_runner=gh_runner)
    boards = _extract_boards(response)
    board = _pick_sprint_board(boards)
    if board is None:
        return json.dumps({'error': _NO_SPRINT_BOARD_ERROR})

    for item in _query_board_items(
        owner, repo, board['number'],
        gh_runner=gh_runner, include_field_values=True,
    ):
        content = item.get('content') or {}
        if content.get('number') != number:
            continue
        for fv in (((item.get('fieldValues') or {}).get('nodes')) or []):
            if not fv:
                continue
            field_name = (fv.get('field') or {}).get('name')
            if field_name == 'Status':
                return json.dumps({
                    'number': number, 'status': fv.get('name'),
                })
        return json.dumps({'number': number, 'status': None})
    return json.dumps({
        'error': f'issue #{number} is not on the board',
    })
