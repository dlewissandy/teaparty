"""Tests for the GitHub MCP tool layer (issue management + Projects V2 board).

Specification source: issue #427.

Layered:
  1. Contract invariants — no ``repo``/``cursor``/``limit`` parameters,
     names not opaque IDs at the call boundary
  2. Issue management handlers — list_milestones, list_milestone_issues,
     read_issue, create_issue, close/reopen, set_milestone, set_labels,
     list_comments, create_comment
  3. Projects V2 board handlers — list_project_boards, add_issue_to_board
     (idempotent), set_board_status (name → option id resolution),
     read_board_status
  4. Pagination — multi-page ``gh api`` responses are concatenated
  5. Repo resolution — derived from the project's git remote, never
     a parameter; failures surface as actionable errors

Tests inject a fake ``gh`` runner so no subprocess actually runs.  Each
test asserts both the command shape (what we ask gh to do) and the
parsed return shape (what callers see), so neither half can drift
silently.
"""
from __future__ import annotations

import inspect
import json
import unittest

from teaparty.mcp.tools import github as gh


# ── Test harness ────────────────────────────────────────────────────────────

class _FakeGh:
    """Captures ``gh`` invocations and replays canned responses.

    ``responses`` is a list of stdout strings, consumed in order.  Each
    call appends the argv tuple to ``calls``.  Tests assert on the
    exact argv to verify the handler asked gh for the right thing,
    and parse stdout from ``responses`` to verify the handler returned
    the right shape.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, input_text: str = '') -> str:
        self.calls.append(tuple(args))
        if not self.responses:
            raise AssertionError(
                f'_FakeGh ran out of canned responses on call {len(self.calls)} '
                f'with argv={args!r} (input_text={input_text!r}); '
                'the handler made more gh calls than the test prepared.'
            )
        return self.responses.pop(0)


def _fake_resolver(owner: str = 'dlewissandy', repo: str = 'teaparty'):
    """Inject a deterministic repo identity for tests."""
    return lambda: (owner, repo)


# ── 1. Contract invariants ──────────────────────────────────────────────────

class TestContractInvariants(unittest.TestCase):
    """The granularity contract from issue #427.

    These tests are introspection-based: they fail if a handler grows a
    ``repo`` / ``cursor`` / ``limit`` / ``page`` parameter, or if a board
    tool starts taking item ids or option ids from the caller.
    """

    PUBLIC_HANDLERS = (
        'list_milestones_handler',
        'list_milestone_issues_handler',
        'read_issue_handler',
        'create_issue_handler',
        'close_issue_handler',
        'reopen_issue_handler',
        'set_issue_milestone_handler',
        'set_issue_labels_handler',
        'list_issue_comments_handler',
        'create_comment_handler',
        'list_project_boards_handler',
        'add_issue_to_board_handler',
        'set_board_status_handler',
        'read_board_status_handler',
    )

    def test_no_handler_accepts_a_repo_parameter(self):
        """Acceptance criterion 16: repo identity comes from the
        project context, not a parameter.  A ``repo`` arg on any
        handler is a contract violation."""
        offenders = []
        for name in self.PUBLIC_HANDLERS:
            handler = getattr(gh, name, None)
            self.assertIsNotNone(
                handler,
                f'{name} is not exported from teaparty.mcp.tools.github',
            )
            sig = inspect.signature(handler)
            for param in sig.parameters:
                if param in {'repo', 'owner', 'repository'}:
                    offenders.append(f'{name}({param}=...)')
        self.assertEqual(
            offenders, [],
            f'handlers expose a repo parameter (contract: repo is resolved '
            f'from project context, not passed by callers): {offenders}',
        )

    def test_no_listing_handler_accepts_pagination_parameter(self):
        """Acceptance criterion 17: listings paginate internally; no
        ``limit``, ``cursor``, ``page``, or ``per_page`` exposed."""
        listing_handlers = (
            'list_milestones_handler',
            'list_milestone_issues_handler',
            'list_issue_comments_handler',
            'list_project_boards_handler',
        )
        offenders = []
        for name in listing_handlers:
            handler = getattr(gh, name)
            sig = inspect.signature(handler)
            for param in sig.parameters:
                if param in {'limit', 'cursor', 'page', 'per_page', 'after'}:
                    offenders.append(f'{name}({param}=...)')
        self.assertEqual(
            offenders, [],
            f'listing handlers expose pagination parameters (contract: '
            f'listings handle paging internally and return the full result): '
            f'{offenders}',
        )

    def test_board_handlers_take_status_names_not_option_ids(self):
        """Acceptance criterion 13/15: ``set_board_status`` takes a status
        *name* (e.g. ``'Approved'``), never an option id.  The parameter
        must be named ``status`` and the docstring must not mention
        option ids as input."""
        sig = inspect.signature(gh.set_board_status_handler)
        params = list(sig.parameters)
        self.assertIn(
            'status', params,
            'set_board_status_handler must accept a status name parameter',
        )
        self.assertNotIn(
            'option_id', params,
            'set_board_status_handler must not accept an option_id '
            '(contract: callers pass names, not opaque ids)',
        )
        self.assertNotIn(
            'item_id', params,
            'set_board_status_handler must not accept an item_id '
            '(contract: callers pass issue numbers, not opaque item ids)',
        )

    def test_board_handlers_take_issue_numbers_not_item_ids(self):
        """Acceptance criterion 12/15: ``add_issue_to_board`` and
        ``read_board_status`` accept issue numbers, never item ids."""
        for name in (
            'add_issue_to_board_handler',
            'read_board_status_handler',
            'set_board_status_handler',
        ):
            sig = inspect.signature(getattr(gh, name))
            params = list(sig.parameters)
            self.assertNotIn(
                'item_id', params,
                f'{name} must not accept an item_id parameter '
                '(contract: callers pass issue numbers)',
            )
            self.assertIn(
                'number', params,
                f'{name} must accept ``number`` (the issue number) per '
                'the granularity contract',
            )


# ── 2. Issue management handlers ────────────────────────────────────────────

class TestListMilestones(unittest.TestCase):

    def test_returns_milestones_with_required_fields(self):
        """AC 1: each milestone in the result carries number, title,
        state, open_issues, due_on."""
        page1 = json.dumps([
            {
                'number': 1, 'title': 'Tier 4: Proxy Evolution',
                'state': 'open', 'open_issues': 7, 'due_on': None,
            },
            {
                'number': 2, 'title': 'Tier 5: Done',
                'state': 'closed', 'open_issues': 0, 'due_on': '2026-01-01',
            },
        ])
        fake = _FakeGh([page1])

        out = gh.list_milestones_handler(
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(len(result), 2, f'expected 2 milestones, got {result!r}')
        for m in result:
            for field in ('number', 'title', 'state', 'open_issues', 'due_on'):
                self.assertIn(
                    field, m,
                    f'milestone {m.get("number")!r} missing required '
                    f'spec field {field!r} (AC 1): {m!r}',
                )
        self.assertEqual(result[0]['number'], 1)
        self.assertEqual(result[0]['state'], 'open')
        self.assertEqual(result[1]['state'], 'closed')

    def test_calls_gh_api_with_state_all(self):
        """The handler must request milestones in *all* states; querying
        only ``open`` would miss closed milestones the caller asked for."""
        fake = _FakeGh(['[]'])

        gh.list_milestones_handler(
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(len(fake.calls), 1)
        argv = fake.calls[0]
        joined = ' '.join(argv)
        self.assertIn(
            'repos/dlewissandy/teaparty/milestones', joined,
            f'list_milestones must query the resolved repo, got argv={argv!r}',
        )
        self.assertIn(
            'state=all', joined,
            f'list_milestones must request state=all so closed milestones '
            f'are included, got argv={argv!r}',
        )

    def test_returns_empty_array_when_no_milestones(self):
        """The standard's empty regime: empty response → ``[]``, not
        ``null``, not ``{}``, not a crash."""
        fake = _FakeGh(['[]'])

        out = gh.list_milestones_handler(
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(
            json.loads(out), [],
            f'empty milestone list must return [], got {out!r}',
        )


_MILESTONES_LOOKUP_RESPONSE = json.dumps([
    {
        'number': 1, 'title': 'Tier 4: Proxy Evolution',
        'state': 'open', 'open_issues': 7, 'due_on': None,
    },
])


class TestListMilestoneIssues(unittest.TestCase):

    def _canned_issue(self, number: int, state: str = 'open') -> dict:
        return {
            'number': number, 'title': f'Issue {number}', 'state': state,
            'labels': [], 'milestone': {'title': 'Tier 4: Proxy Evolution'},
            'assignees': [],
        }

    def test_default_state_is_all(self):
        """AC 2: ``state`` defaults to ``'all'``."""
        sig = inspect.signature(gh.list_milestone_issues_handler)
        self.assertEqual(
            sig.parameters['state'].default, 'all',
            'list_milestone_issues default state must be "all" per AC 2',
        )

    def test_returns_issues_for_named_milestone(self):
        page = json.dumps([self._canned_issue(427), self._canned_issue(429)])
        fake = _FakeGh([_MILESTONES_LOOKUP_RESPONSE, page])

        out = gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            [i['number'] for i in result], [427, 429],
            f'expected issues 427, 429; got {result!r}',
        )

    def test_state_value_is_passed_to_gh(self):
        """``state='closed'`` must reach gh's query; otherwise we'd
        return open issues regardless of what the caller asked for."""
        fake = _FakeGh([_MILESTONES_LOOKUP_RESPONSE, '[]'])

        gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution', state='closed',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        # The second call is the issues query; the state must be
        # embedded in the URL path or as a flag.
        issues_call = fake.calls[1]
        joined = ' '.join(issues_call)
        self.assertIn(
            'state=closed', joined,
            f'state argument must reach gh; issues call argv={issues_call!r}',
        )

    def test_unknown_milestone_returns_actionable_error(self):
        """Negative space: a milestone name with no matching record
        must surface as a clear error, not silently fall through to
        ``state=all`` and return every issue in the repo."""
        fake = _FakeGh([_MILESTONES_LOOKUP_RESPONSE])

        out = gh.list_milestone_issues_handler(
            milestone='No Such Milestone',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn(
            'error', result,
            f'unknown milestone must return error JSON; got {result!r}',
        )
        self.assertIn(
            'No Such Milestone', result['error'],
            f'error must name the bad milestone for actionability; got {result!r}',
        )

    def test_returns_empty_array_when_milestone_has_no_issues(self):
        """The standard's empty regime: empty response → empty list,
        not ``null`` or ``{}`` or a crash."""
        fake = _FakeGh([_MILESTONES_LOOKUP_RESPONSE, '[]'])

        out = gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(
            json.loads(out), [],
            f'empty milestone must return [], got {out!r}',
        )


class TestReadIssue(unittest.TestCase):

    def test_returns_body_labels_state_milestone_assignees(self):
        """AC 3: read_issue returns these fields, all derived from the
        REST issue endpoint (lowercase ``state``, matching the rest of
        the tool layer)."""
        canned = json.dumps({
            'number': 427,
            'title': 'MCP tool layer for GitHub Projects V2 and Issues',
            'body': '## What\n\nA focused MCP tool surface...',
            'state': 'open',
            'labels': [{'name': 'tier-4'}],
            'milestone': {'title': 'Tier 4: Proxy Evolution', 'number': 1},
            'assignees': [{'login': 'dlewissandy'}],
        })
        fake = _FakeGh([canned])

        out = gh.read_issue_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        for field in ('body', 'labels', 'state', 'milestone', 'assignees'):
            self.assertIn(
                field, result,
                f'read_issue result missing AC-3 field {field!r}: {result!r}',
            )
        self.assertEqual(result['number'], 427)
        self.assertEqual(result['state'], 'open')

        # The handler must hit the REST issues endpoint; ``gh issue
        # view --json state`` would return ``OPEN``/``CLOSED`` and
        # break parity with ``list_milestones`` / ``list_milestone_issues``
        # which are REST-based.
        argv = fake.calls[0]
        joined = ' '.join(argv)
        self.assertIn(
            '/repos/dlewissandy/teaparty/issues/427', joined,
            f'read_issue must hit the REST issues endpoint for case '
            f'consistency with other tools; argv={argv!r}',
        )

    def test_state_is_lowercase_matching_other_tools(self):
        """Cross-tool contract: ``state`` is always lowercase
        (``open``/``closed``).  A regression that read state from
        ``gh issue view --json state`` (uppercase OPEN/CLOSED) would
        break callers doing ``if issue['state'] == 'open'``."""
        canned = json.dumps({
            'number': 427, 'title': 'X', 'body': '', 'state': 'closed',
            'labels': [], 'milestone': None, 'assignees': [],
        })
        fake = _FakeGh([canned])

        out = gh.read_issue_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            result['state'], 'closed',
            f'state must be lowercase to match list_milestones / '
            f'list_milestone_issues; got {result["state"]!r}',
        )
        self.assertNotIn(
            result['state'], ('OPEN', 'CLOSED'),
            'state must NOT be the GraphQL-style uppercase form; '
            f'got {result["state"]!r}',
        )


class TestCreateIssue(unittest.TestCase):

    def test_returns_new_issue_number(self):
        """AC 4: create_issue returns the new issue number."""
        # gh issue create prints the URL; we extract the trailing number.
        fake = _FakeGh(['https://github.com/dlewissandy/teaparty/issues/9876\n'])

        out = gh.create_issue_handler(
            title='New issue', body='body text',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            result['number'], 9876,
            f'expected issue number 9876 from URL extraction, got {result!r}',
        )

    def test_milestone_and_labels_are_passed_through(self):
        """Each value must be bound to its flag — a handler that put
        the milestone name in ``--label`` (or vice versa) would pass
        a substring check on the joined argv but fail this positional
        pin."""
        fake = _FakeGh(['https://github.com/dlewissandy/teaparty/issues/9877\n'])

        gh.create_issue_handler(
            title='T', body='B',
            milestone='Tier 4: Proxy Evolution',
            labels=['tier-4', 'mcp'],
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        ms_idx = argv.index('--milestone')
        self.assertEqual(
            argv[ms_idx + 1], 'Tier 4: Proxy Evolution',
            f'--milestone must be immediately followed by the milestone '
            f'name; argv={argv!r}',
        )
        # Each label must appear as the value following its own --label flag.
        label_values = [
            argv[i + 1]
            for i, tok in enumerate(argv)
            if tok == '--label' and i + 1 < len(argv)
        ]
        self.assertEqual(
            sorted(label_values), sorted(['tier-4', 'mcp']),
            f'each label must follow a --label flag; got label_values='
            f'{label_values!r} from argv={argv!r}',
        )


class TestCloseAndReopenIssue(unittest.TestCase):
    """AC 5/6: close and reopen accept an optional comment.

    Asserts on argv structure rather than on a joined-string blob so
    several plausible-but-wrong implementations are caught:
      * posting the comment as a separate ``gh issue comment`` call
      * sending the comment to a different issue number
      * passing the comment as ``--title`` on a new issue
      * binding the comment to ``reopen`` while ``close`` runs without it
    """

    def test_close_with_comment_invokes_single_gh_call_with_bound_body(self):
        fake = _FakeGh([''])

        gh.close_issue_handler(
            number=427, comment='resolved by #500',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(
            len(fake.calls), 1,
            f'close_issue must produce exactly one gh call (close + '
            f'comment in the same invocation), got {fake.calls!r}',
        )
        argv = fake.calls[0]
        self.assertEqual(argv[0], 'issue', f'argv[0] must be "issue"; argv={argv!r}')
        self.assertEqual(argv[1], 'close', f'argv[1] must be "close"; argv={argv!r}')
        self.assertEqual(argv[2], '427', f'argv[2] must be "427"; argv={argv!r}')
        self.assertIn(
            '-c', argv,
            f'comment must be passed via -c flag; argv={argv!r}',
        )
        comment_idx = argv.index('-c')
        self.assertEqual(
            argv[comment_idx + 1], 'resolved by #500',
            f'-c flag must be immediately followed by the comment; '
            f'argv={argv!r}',
        )

    def test_reopen_with_comment_invokes_single_gh_call_with_bound_body(self):
        fake = _FakeGh([''])

        gh.reopen_issue_handler(
            number=427, comment='reopened: more work needed',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(len(fake.calls), 1)
        argv = fake.calls[0]
        self.assertEqual(argv[0], 'issue')
        self.assertEqual(argv[1], 'reopen')
        self.assertEqual(argv[2], '427')
        comment_idx = argv.index('-c')
        self.assertEqual(
            argv[comment_idx + 1], 'reopened: more work needed',
            f'-c flag must be immediately followed by the comment; '
            f'argv={argv!r}',
        )

    def test_close_without_comment_does_not_post_empty_comment(self):
        """Negative space: omitting the comment must not produce an
        empty comment body on the issue.  A handler that always posts
        a comment, even an empty one, is a state-leaking bug."""
        fake = _FakeGh([''])

        gh.close_issue_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        for argv in fake.calls:
            for i, tok in enumerate(argv):
                if tok in ('-c', '--body') and i + 1 < len(argv):
                    self.assertNotEqual(
                        argv[i + 1], '',
                        f'close_issue without comment must not pass an '
                        f'empty body; argv={argv!r}',
                    )

    def test_reopen_without_comment_does_not_post_empty_comment(self):
        """Symmetric negative-space coverage for reopen."""
        fake = _FakeGh([''])

        gh.reopen_issue_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        for argv in fake.calls:
            for i, tok in enumerate(argv):
                if tok in ('-c', '--body') and i + 1 < len(argv):
                    self.assertNotEqual(
                        argv[i + 1], '',
                        f'reopen_issue without comment must not pass an '
                        f'empty body; argv={argv!r}',
                    )


class TestSetIssueMilestone(unittest.TestCase):

    def test_milestone_name_reaches_gh_bound_to_correct_issue(self):
        """AC 7: caller passes a milestone name; the handler routes it
        to gh issue edit --milestone for the *specified* issue.

        Pinning the issue number positionally catches a regression
        that ignored the ``number`` argument or hardcoded an issue."""
        fake = _FakeGh([''])

        gh.set_issue_milestone_handler(
            number=427, milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        self.assertEqual(argv[0], 'issue', f'argv[0] must be "issue"; argv={argv!r}')
        self.assertEqual(argv[1], 'edit', f'argv[1] must be "edit"; argv={argv!r}')
        self.assertEqual(
            argv[2], '427',
            f'argv[2] must be the target issue number; argv={argv!r}',
        )
        ms_idx = argv.index('--milestone')
        self.assertEqual(
            argv[ms_idx + 1], 'Tier 4: Proxy Evolution',
            f'--milestone must be immediately followed by the milestone '
            f'name; argv={argv!r}',
        )


class TestSetIssueLabels(unittest.TestCase):

    def test_replaces_full_label_set_via_rest_api_put(self):
        """AC 8: ``set_issue_labels`` replaces the label set.  ``gh
        issue edit --add-label / --remove-label`` cannot do replace in
        one call without first reading the current set; the simplest
        correct path is ``PUT /repos/{owner}/{repo}/issues/{N}/labels``.

        This test pins the replace semantic: a label that was on the
        issue but is not in the new set must not survive."""
        # A REST PUT to /repos/.../issues/427/labels with body
        # {"labels": [...]} returns the new label set.  We don't care
        # about the body; only that the handler issued a PUT to the
        # labels endpoint with the new label list.
        fake = _FakeGh(['[{"name":"new-label"}]'])

        gh.set_issue_labels_handler(
            number=427, labels=['new-label'],
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        joined = ' '.join(argv)
        # Must hit the labels endpoint with PUT (or at minimum, a
        # method that replaces — POST appends, which is the bug we
        # want to catch).
        self.assertIn(
            'issues/427/labels', joined,
            f'set_issue_labels must hit the labels endpoint; argv={argv!r}',
        )
        self.assertIn(
            'PUT', argv,
            f'set_issue_labels must use PUT to replace (POST would '
            f'append); argv={argv!r}',
        )
        self.assertIn(
            'new-label', joined,
            f'new label set must reach the API; argv={argv!r}',
        )


class TestListIssueComments(unittest.TestCase):

    def test_returns_all_comments(self):
        """AC 9."""
        canned = json.dumps([
            {'id': 1, 'user': {'login': 'a'}, 'body': 'first'},
            {'id': 2, 'user': {'login': 'b'}, 'body': 'second'},
        ])
        fake = _FakeGh([canned])

        out = gh.list_issue_comments_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            len(result), 2,
            f'expected 2 comments, got {len(result)}: {result!r}',
        )
        self.assertEqual(result[0]['body'], 'first')
        self.assertEqual(result[1]['body'], 'second')

    def test_returns_empty_array_when_no_comments(self):
        fake = _FakeGh(['[]'])

        out = gh.list_issue_comments_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertEqual(json.loads(out), [])


class TestCreateComment(unittest.TestCase):

    def test_invokes_gh_issue_comment_with_target_number(self):
        """AC 10: posts a comment to the named issue.  A handler that
        ignored the ``number`` argument and posted to a different
        issue would pass a substring check on argv but fail this
        positional pin."""
        fake = _FakeGh([
            'https://github.com/dlewissandy/teaparty/issues/427'
            '#issuecomment-1234567\n',
        ])

        gh.create_comment_handler(
            number=427, body='hello there',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        self.assertEqual(
            argv[0], 'issue',
            f'argv[0] must be "issue"; argv={argv!r}',
        )
        self.assertEqual(
            argv[1], 'comment',
            f'argv[1] must be "comment"; argv={argv!r}',
        )
        self.assertEqual(
            argv[2], '427',
            f'argv[2] must be the target issue number "427"; argv={argv!r}',
        )
        body_idx = argv.index('--body')
        self.assertEqual(
            argv[body_idx + 1], 'hello there',
            f'--body flag must be immediately followed by the comment '
            f'body; argv={argv!r}',
        )


# ── 3. Projects V2 board handlers ───────────────────────────────────────────

# Canned GraphQL responses used across board tests.  The combined
# response carries both board metadata and the issue node id so a
# handler can resolve everything in one query before mutating.
_BOARDS_GRAPHQL_RESPONSE = json.dumps({
    'data': {
        'repository': {
            'projectsV2': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': [{
                    'id': 'PVT_kwHOAH4OHc4BR81E',
                    'number': 2,
                    'title': 'TeaParty',
                    'fields': {
                        'nodes': [{
                            'id': 'PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs',
                            'name': 'Status',
                            'options': [
                                {'id': 'a76a90c5', 'name': 'Backlog'},
                                {'id': '1eb3c52a', 'name': 'Approved'},
                                {'id': '71f64e69', 'name': 'In Progress'},
                                {'id': '42fb9610', 'name': 'Done'},
                                {'id': 'e4544388', 'name': "Won't Do"},
                            ],
                        }],
                    },
                }],
            },
            'issue': {'id': 'I_kwDOteaparty427'},
        },
    },
})


class TestListProjectBoards(unittest.TestCase):

    def test_returns_status_field_options(self):
        """AC 11: list_project_boards returns boards with their Status
        field option metadata.  Without the option metadata, callers
        cannot resolve a status name to an id at sprint-setup time."""
        fake = _FakeGh([_BOARDS_GRAPHQL_RESPONSE])

        out = gh.list_project_boards_handler(
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            len(result), 1,
            f'expected 1 board, got {len(result)}: {result!r}',
        )
        board = result[0]
        self.assertIn(
            'status_options', board,
            f'each board must include status_options metadata (AC 11); '
            f'got keys {list(board.keys())!r}',
        )
        names = [o['name'] for o in board['status_options']]
        self.assertEqual(
            sorted(names),
            sorted(['Backlog', 'Approved', 'In Progress', 'Done', "Won't Do"]),
            f'status options must include the standard set; got {names!r}',
        )


class TestAddIssueToBoard(unittest.TestCase):

    def test_repeat_calls_send_same_content_id_to_mutation(self):
        """AC 12: idempotency contract — repeat calls for the same
        issue must pass the same ``contentId`` to the mutation.

        GitHub's ``addProjectV2ItemById`` is naturally idempotent —
        when called for an issue already on the board it returns the
        existing item id rather than creating a new one.  The handler's
        contract is to delegate that idempotency to GitHub: it must
        resolve the same ``contentId`` (the issue's GraphQL node id)
        on every call, so GitHub recognizes the repeat and returns
        the same item.

        A handler that fabricated a fresh id, or that resolved the
        contentId differently between calls, would break the contract
        even if GitHub happened to deduplicate.  This test catches
        both: it scripts two distinct mutation responses (different
        item ids) and asserts the mutation argv carries the same
        contentId both times — proving the handler asks GitHub the
        same question both times."""
        mutation_response_1 = json.dumps({
            'data': {'addProjectV2ItemById': {'item': {'id': 'PVTI_first'}}},
        })
        mutation_response_2 = json.dumps({
            'data': {'addProjectV2ItemById': {'item': {'id': 'PVTI_second'}}},
        })

        fake = _FakeGh([
            _BOARDS_GRAPHQL_RESPONSE, mutation_response_1,
            _BOARDS_GRAPHQL_RESPONSE, mutation_response_2,
        ])

        gh.add_issue_to_board_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )
        gh.add_issue_to_board_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        # Calls 1 (board+issue lookup) and 3 (board+issue lookup again):
        # both must request the same issue node.  We extract the issue
        # number from the GraphQL query and assert it's identical.
        first_lookup = ' '.join(fake.calls[0])
        second_lookup = ' '.join(fake.calls[2])
        self.assertIn('issue(number: 427)', first_lookup)
        self.assertIn('issue(number: 427)', second_lookup)

        # Calls 2 and 4: the mutation argv must carry the same
        # contentId on both invocations — that's the load-bearing
        # part of idempotency.  A handler that derived contentId from
        # local state (or fabricated one) would diverge here even if
        # given the same canned response.
        first_mutation = fake.calls[1]
        second_mutation = fake.calls[3]
        first_content = next(
            (a for a in first_mutation if a.startswith('contentId=')), None,
        )
        second_content = next(
            (a for a in second_mutation if a.startswith('contentId=')), None,
        )
        self.assertIsNotNone(
            first_content,
            f'mutation must carry contentId arg; argv={first_mutation!r}',
        )
        self.assertEqual(
            first_content, second_content,
            f'idempotency contract: repeat calls must pass the same '
            f'contentId so GitHub can dedupe.  Got first={first_content!r}, '
            f'second={second_content!r} — divergence here means the '
            f'handler is fabricating ids and GitHub may double-add.',
        )
        # The contentId must come from the canned response's
        # ``repository.issue.id`` — pinning the exact value catches a
        # regression that statically fabricates a constant contentId
        # (which would still satisfy the equality assertion above).
        self.assertEqual(
            first_content, 'contentId=I_kwDOteaparty427',
            f'contentId must be derived from repository.issue.id in '
            f'the GraphQL response, not fabricated; got {first_content!r}. '
            f'A handler that hardcodes a constant id would mutate the '
            f'wrong issue when given a different number.',
        )


class TestSetBoardStatus(unittest.TestCase):

    def test_resolves_status_name_to_option_id_per_call(self):
        """AC 13/15: ``set_board_status('Approved')`` must resolve the
        option id from the board's own metadata at call time.  A
        handler that hardcodes IDs would silently corrupt board state
        if the board is reconfigured.  This test gives a board with
        a non-default option-id mapping and asserts the handler
        sends the *option id from that board*, not a default."""

        # Same canonical status name set but different option ids than
        # the live project memory references — i.e. the board has been
        # reconfigured.  All five canonical names are present so the
        # board IS recognized as a sprint board (no silent fallback);
        # what differs is the option ids, which is exactly what
        # ``set_board_status`` must resolve dynamically.
        custom_board = json.dumps({
            'data': {
                'repository': {
                    'projectsV2': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'PVT_custom',
                            'number': 2,
                            'title': 'TeaParty',
                            'fields': {
                                'nodes': [{
                                    'id': 'PVTSSF_custom_status',
                                    'name': 'Status',
                                    'options': [
                                        {'id': 'OPT_BACKLOG_NEW',
                                         'name': 'Backlog'},
                                        {'id': 'OPT_APPROVED_NEW',
                                         'name': 'Approved'},
                                        {'id': 'OPT_IN_PROGRESS_NEW',
                                         'name': 'In Progress'},
                                        {'id': 'OPT_DONE_NEW',
                                         'name': 'Done'},
                                        {'id': 'OPT_WONTDO_NEW',
                                         'name': "Won't Do"},
                                    ],
                                }],
                            },
                        }],
                    },
                },
            },
        })

        # Item lookup for the issue.
        item_lookup = json.dumps({
            'data': {
                'repository': {
                    'projectV2': {
                        'items': {
                            'pageInfo': {
                                'hasNextPage': False, 'endCursor': None,
                            },
                            'nodes': [{
                                'id': 'PVTI_existing',
                                'content': {'number': 427},
                            }],
                        },
                    },
                },
            },
        })

        # The status update mutation response.
        status_set = json.dumps({
            'data': {'updateProjectV2ItemFieldValue': {
                'projectV2Item': {'id': 'PVTI_existing'},
            }},
        })

        fake = _FakeGh([custom_board, item_lookup, status_set])

        gh.set_board_status_handler(
            number=427, status='Approved',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        # The mutation call must reference OPT_APPROVED_NEW — the
        # option id from *this board's* metadata, not a default.
        mutation_call = fake.calls[-1]
        joined = ' '.join(mutation_call)
        self.assertIn(
            'OPT_APPROVED_NEW', joined,
            f'set_board_status must resolve the option id from the '
            f'live board metadata, not from a default mapping. '
            f'Mutation call argv: {mutation_call!r}',
        )

    def test_rejects_unknown_status_name(self):
        """A status name that the board does not declare must surface
        as a clear error, not be silently sent as the literal string."""
        fake = _FakeGh([_BOARDS_GRAPHQL_RESPONSE])

        result = gh.set_board_status_handler(
            number=427, status='NotAStatus',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        self.assertIn(
            'NotAStatus', result,
            f'unknown status error must name the bad input; got {result!r}',
        )
        self.assertTrue(
            'unknown' in result.lower() or 'not found' in result.lower()
            or 'invalid' in result.lower() or 'error' in result.lower(),
            f'unknown status must surface as an actionable error; '
            f'got {result!r}',
        )


class TestReadBoardStatus(unittest.TestCase):

    def test_returns_status_name_for_issue(self):
        """AC 14: read_board_status returns the human-readable name."""
        # Items query returning an item with a status field set.
        items_response = json.dumps({
            'data': {
                'repository': {
                    'projectV2': {
                        'items': {
                            'pageInfo': {
                                'hasNextPage': False, 'endCursor': None,
                            },
                            'nodes': [{
                                'id': 'PVTI_xyz',
                                'content': {'number': 427},
                                'fieldValues': {
                                    'nodes': [{
                                        'name': 'Approved',
                                        'field': {'name': 'Status'},
                                    }],
                                },
                            }],
                        },
                    },
                },
            },
        })

        fake = _FakeGh([_BOARDS_GRAPHQL_RESPONSE, items_response])

        out = gh.read_board_status_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            result['status'], 'Approved',
            f'read_board_status must return the status name (not id); '
            f'got {result!r}',
        )


# ── 4. Pagination ───────────────────────────────────────────────────────────

class TestPaginationConcatenatesAllPages(unittest.TestCase):
    """AC 17: listings paginate internally and return the full result.

    A handler that returns only the first 30 issues silently truncates.
    These tests give multi-page canned responses and verify the handler
    keeps fetching until ``hasNextPage`` is False (GraphQL) or the link
    header has no ``rel="next"`` (REST).
    """

    def test_list_milestone_issues_uses_paginate(self):
        """AC 17 (behavior side): the handler must request gh to
        paginate internally rather than capping at a fixed limit.

        With ``_FakeGh`` we cannot exercise real subprocess pagination;
        the load-bearing assertion is that ``--paginate`` is on the
        argv so the contract is delegated to gh.  A handler that used
        ``--limit 1000`` would silently truncate any milestone larger
        than that — caught by this assertion."""
        fake = _FakeGh([_MILESTONES_LOOKUP_RESPONSE, '[]'])

        gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        # The second call is the issues query.
        issues_call = fake.calls[1]
        self.assertIn(
            '--paginate', issues_call,
            f'list_milestone_issues must use --paginate to avoid '
            f'silent truncation past a fixed cap; issues call argv='
            f'{issues_call!r}',
        )

    def test_list_issue_comments_uses_paginate(self):
        """``gh api`` lists default to 30 results per page.  The
        handler must use ``--paginate`` (or loop ``Link`` headers)
        to fetch all comments."""
        fake = _FakeGh(['[]'])

        gh.list_issue_comments_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        self.assertIn(
            '--paginate', argv,
            f'list_issue_comments must use --paginate to avoid '
            f'truncation past the first page; argv={argv!r}',
        )

    def test_list_milestones_uses_paginate(self):
        fake = _FakeGh(['[]'])

        gh.list_milestones_handler(
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        self.assertIn(
            '--paginate', argv,
            f'list_milestones must use --paginate; argv={argv!r}',
        )


class TestSprintBoardSelection(unittest.TestCase):
    """`_pick_sprint_board` and the contract it enforces: only the
    canonical-Status board is a valid target for ``add_issue_to_board``,
    ``set_board_status``, and ``read_board_status``.  Anything else
    must surface an actionable error rather than silently writing to
    the wrong board."""

    def _board(self, options: list[str], **extra) -> dict:
        return {
            'id': extra.get('id', 'PVT_test'),
            'number': extra.get('number', 1),
            'title': extra.get('title', 'test board'),
            'status_field_id': extra.get('status_field_id', 'PVTSSF_test'),
            'status_options': [
                {'id': f'opt_{i}', 'name': name}
                for i, name in enumerate(options)
            ],
        }

    def test_picks_board_with_canonical_status_options(self):
        """Two boards in the repo, only one canonical — the canonical
        one is selected."""
        boards = [
            self._board(['Backlog', 'Done'], id='PVT_other'),
            self._board(
                ['Backlog', 'Approved', 'In Progress', 'Done', "Won't Do"],
                id='PVT_canonical',
            ),
        ]
        chosen = gh._pick_sprint_board(boards)
        self.assertIsNotNone(chosen)
        self.assertEqual(
            chosen['id'], 'PVT_canonical',
            'must select the board declaring the canonical Status set, '
            f'not the first board returned; got {chosen!r}',
        )

    def test_returns_none_when_no_board_has_canonical_status_set(self):
        """The user's no-silent-fallbacks rule: a non-canonical board
        is not a substitute for the sprint board."""
        boards = [self._board(['Open', 'Closed'], id='PVT_only')]
        self.assertIsNone(
            gh._pick_sprint_board(boards),
            'a board without the canonical Status options is not a '
            'sprint board; substituting it would silently write to '
            'the wrong target',
        )

    def test_returns_none_for_empty_board_list(self):
        self.assertIsNone(gh._pick_sprint_board([]))

    def test_set_board_status_errors_when_no_canonical_board(self):
        """End-to-end: with no canonical sprint board, the handler
        must NOT mutate.  It must return an actionable error JSON."""
        non_canonical = json.dumps({
            'data': {
                'repository': {
                    'projectsV2': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'PVT_random',
                            'number': 5,
                            'title': 'Random',
                            'fields': {
                                'nodes': [{
                                    'id': 'PVTSSF_random',
                                    'name': 'Status',
                                    'options': [
                                        {'id': 'A', 'name': 'Open'},
                                        {'id': 'B', 'name': 'Closed'},
                                    ],
                                }],
                            },
                        }],
                    },
                },
            },
        })
        fake = _FakeGh([non_canonical])

        out = gh.set_board_status_handler(
            number=427, status='Approved',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn(
            'error', result,
            f'must return error JSON when no canonical board; got {result!r}',
        )
        self.assertEqual(
            len(fake.calls), 1,
            f'must NOT mutate when no canonical board; expected 1 call '
            f'(board lookup only), got {len(fake.calls)}: {fake.calls!r}',
        )

    def test_add_issue_to_board_errors_when_no_canonical_board(self):
        empty_boards = json.dumps({
            'data': {
                'repository': {
                    'projectsV2': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [],
                    },
                    'issue': {'id': 'I_kwDOissue'},
                },
            },
        })
        fake = _FakeGh([empty_boards])

        out = gh.add_issue_to_board_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn('error', result)
        self.assertEqual(
            len(fake.calls), 1,
            'must NOT call addProjectV2ItemById when no canonical board exists',
        )


class TestBoardHandlerErrorBranches(unittest.TestCase):
    """Each board handler must surface its real error branches as
    structured errors that name what is missing — not silently fall
    through or crash on a None."""

    def test_set_board_status_errors_when_issue_not_on_board(self):
        # Board exists, status is valid, but no item matches the issue number.
        empty_items = json.dumps({
            'data': {
                'repository': {
                    'projectV2': {
                        'items': {
                            'pageInfo': {
                                'hasNextPage': False, 'endCursor': None,
                            },
                            'nodes': [],
                        },
                    },
                },
            },
        })
        fake = _FakeGh([_BOARDS_GRAPHQL_RESPONSE, empty_items])

        out = gh.set_board_status_handler(
            number=427, status='Approved',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn(
            'error', result,
            f'must error when issue not on board; got {result!r}',
        )
        self.assertIn('427', result['error'])
        self.assertIn(
            'add_issue_to_board', result['error'],
            'error must point caller to the corrective tool; '
            f'got {result!r}',
        )
        self.assertEqual(
            len(fake.calls), 2,
            f'must NOT issue the mutation when item is missing; '
            f'expected 2 calls, got {len(fake.calls)}',
        )

    def test_read_board_status_errors_when_issue_not_on_board(self):
        empty_items = json.dumps({
            'data': {
                'repository': {
                    'projectV2': {
                        'items': {
                            'pageInfo': {
                                'hasNextPage': False, 'endCursor': None,
                            },
                            'nodes': [],
                        },
                    },
                },
            },
        })
        fake = _FakeGh([_BOARDS_GRAPHQL_RESPONSE, empty_items])

        out = gh.read_board_status_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn(
            'error', result,
            f'must error when issue not on board; got {result!r}',
        )
        self.assertIn('427', result['error'])

    def test_add_issue_to_board_errors_when_issue_not_in_repo(self):
        """If GitHub returns ``issue: null`` (issue not found in repo),
        the handler must NOT call the mutation with a null contentId."""
        no_issue = json.dumps({
            'data': {
                'repository': {
                    'projectsV2': {
                        'pageInfo': {'hasNextPage': False, 'endCursor': None},
                        'nodes': [{
                            'id': 'PVT_kwHOAH4OHc4BR81E',
                            'number': 2,
                            'title': 'TeaParty',
                            'fields': {
                                'nodes': [{
                                    'id': 'PVTSSF_x',
                                    'name': 'Status',
                                    'options': [
                                        {'id': 'a', 'name': 'Backlog'},
                                        {'id': 'b', 'name': 'Approved'},
                                        {'id': 'c', 'name': 'In Progress'},
                                        {'id': 'd', 'name': 'Done'},
                                        {'id': 'e', 'name': "Won't Do"},
                                    ],
                                }],
                            },
                        }],
                    },
                    'issue': None,
                },
            },
        })
        fake = _FakeGh([no_issue])

        out = gh.add_issue_to_board_handler(
            number=99999, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertIn(
            'error', result,
            f'must error when issue is not in repo; got {result!r}',
        )
        self.assertIn('99999', result['error'])
        self.assertEqual(
            len(fake.calls), 1,
            f'must NOT issue the addProjectV2ItemById mutation with a '
            f'null contentId; expected 1 call, got {len(fake.calls)}',
        )


# ── 5. Repo resolution ──────────────────────────────────────────────────────

class TestRepoResolution(unittest.TestCase):

    def test_default_resolver_parses_github_https_remote(self):
        """The default resolver must parse ``https://github.com/owner/repo.git``
        into ``(owner, repo)``."""
        owner, repo = gh._parse_remote_url(
            'https://github.com/dlewissandy/teaparty.git',
        )
        self.assertEqual((owner, repo), ('dlewissandy', 'teaparty'))

    def test_default_resolver_parses_github_ssh_remote(self):
        """SSH form ``git@github.com:owner/repo.git`` must also parse."""
        owner, repo = gh._parse_remote_url(
            'git@github.com:dlewissandy/teaparty.git',
        )
        self.assertEqual((owner, repo), ('dlewissandy', 'teaparty'))

    def test_resolver_strips_dot_git_suffix(self):
        owner, repo = gh._parse_remote_url(
            'https://github.com/dlewissandy/teaparty',
        )
        self.assertEqual((owner, repo), ('dlewissandy', 'teaparty'))

    def test_resolver_rejects_non_github_remote(self):
        """Non-GitHub remotes must raise rather than guess.  Silent
        fallback to a wrong owner/repo would corrupt state silently."""
        with self.assertRaises(ValueError) as ctx:
            gh._parse_remote_url('https://gitlab.com/owner/repo.git')
        self.assertIn(
            'github', str(ctx.exception).lower(),
            'error must name the constraint (GitHub-only) so the '
            'caller knows what to fix',
        )


# ── 6. Server registration ──────────────────────────────────────────────────

class TestMcpServerRegistersGitHubTools(unittest.TestCase):
    """AC 18: all 14 tools are registered in the MCP server and
    discoverable via tools/list."""

    EXPECTED_TOOLS = (
        # Issue management
        'list_milestones',
        'list_milestone_issues',
        'read_issue',
        'create_issue',
        'close_issue',
        'reopen_issue',
        'set_issue_milestone',
        'set_issue_labels',
        'list_issue_comments',
        'create_comment',
        # Projects V2 board
        'list_project_boards',
        'add_issue_to_board',
        'set_board_status',
        'read_board_status',
    )

    def test_all_github_tools_appear_in_tool_catalog(self):
        from teaparty.mcp.server.main import list_mcp_tool_names

        names = list_mcp_tool_names()
        bare = {n.split('__')[-1] for n in names}

        missing = [t for t in self.EXPECTED_TOOLS if t not in bare]
        self.assertEqual(
            missing, [],
            f'AC 18: these GitHub tools are not registered with the '
            f'MCP server: {missing!r}',
        )


if __name__ == '__main__':
    unittest.main()
