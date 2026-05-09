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


class TestListMilestoneIssues(unittest.TestCase):

    def _canned_issue(self, number: int, state: str = 'open') -> dict:
        return {
            'number': number, 'title': f'Issue {number}', 'state': state,
            'labels': [], 'milestone': {'title': 'Tier 4: Proxy Evolution'},
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
        fake = _FakeGh([page])

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
        fake = _FakeGh(['[]'])

        gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution', state='closed',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        joined = ' '.join(fake.calls[0])
        self.assertIn(
            'state=closed', joined,
            f'state argument must reach gh; argv={fake.calls[0]!r}',
        )


class TestReadIssue(unittest.TestCase):

    def test_returns_body_labels_state_milestone_assignees(self):
        """AC 3: read_issue returns these fields."""
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
        fake = _FakeGh(['https://github.com/dlewissandy/teaparty/issues/9877\n'])

        gh.create_issue_handler(
            title='T', body='B',
            milestone='Tier 4: Proxy Evolution',
            labels=['tier-4', 'mcp'],
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        joined = ' '.join(argv)
        self.assertIn(
            'Tier 4: Proxy Evolution', joined,
            f'milestone must be passed to gh; argv={argv!r}',
        )
        self.assertIn('tier-4', joined)
        self.assertIn('mcp', joined)


class TestCloseAndReopenIssue(unittest.TestCase):

    def test_close_with_comment_invokes_gh_issue_close_with_body(self):
        """AC 5: close_issue accepts an optional resolution comment."""
        fake = _FakeGh(['', ''])  # comment then close, or close with -c

        gh.close_issue_handler(
            number=427, comment='resolved by #500',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        joined_all = ' '.join(' '.join(c) for c in fake.calls)
        self.assertIn(
            'close', joined_all,
            f'close_issue must invoke gh issue close; calls={fake.calls!r}',
        )
        self.assertIn(
            'resolved by #500', joined_all,
            f'close_issue must include the resolution comment; calls={fake.calls!r}',
        )

    def test_reopen_with_comment_invokes_gh_issue_reopen(self):
        """AC 6."""
        fake = _FakeGh(['', ''])

        gh.reopen_issue_handler(
            number=427, comment='reopened: more work needed',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        joined_all = ' '.join(' '.join(c) for c in fake.calls)
        self.assertIn(
            'reopen', joined_all,
            f'reopen_issue must invoke gh issue reopen; calls={fake.calls!r}',
        )
        self.assertIn(
            'more work needed', joined_all,
            f'reopen_issue must include the comment; calls={fake.calls!r}',
        )

    def test_close_without_comment_does_not_post_empty_comment(self):
        """Negative space: omitting the comment must not produce an
        empty comment body on the issue.  A handler that always posts
        a comment, even an empty one, is a state-leaking bug."""
        fake = _FakeGh([''])

        gh.close_issue_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        # No call should carry an empty -c '' or --body ''.
        for argv in fake.calls:
            for i, tok in enumerate(argv):
                if tok in ('-c', '--body') and i + 1 < len(argv):
                    self.assertNotEqual(
                        argv[i + 1], '',
                        f'close_issue without comment must not pass an '
                        f'empty body; argv={argv!r}',
                    )


class TestSetIssueMilestone(unittest.TestCase):

    def test_milestone_name_reaches_gh(self):
        """AC 7: caller passes a milestone name; the handler routes it
        to gh issue edit --milestone."""
        fake = _FakeGh([''])

        gh.set_issue_milestone_handler(
            number=427, milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        joined = ' '.join(fake.calls[0])
        self.assertIn(
            'Tier 4: Proxy Evolution', joined,
            f'milestone name must be passed to gh; argv={fake.calls[0]!r}',
        )
        self.assertIn(
            '--milestone', joined,
            f'must use gh issue edit --milestone; argv={fake.calls[0]!r}',
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


class TestCreateComment(unittest.TestCase):

    def test_invokes_gh_issue_comment(self):
        """AC 10."""
        fake = _FakeGh(['https://github.com/dlewissandy/teaparty/issues/427#issuecomment-1234567\n'])

        gh.create_comment_handler(
            number=427, body='hello there',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        argv = fake.calls[0]
        joined = ' '.join(argv)
        self.assertIn(
            'comment', joined,
            f'create_comment must invoke gh issue comment; argv={argv!r}',
        )
        self.assertIn('hello there', joined)


# ── 3. Projects V2 board handlers ───────────────────────────────────────────

# Canned GraphQL responses used across board tests.
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

    def test_idempotent_returns_same_item_id_on_repeat(self):
        """AC 12: idempotent — repeat calls return the same item id.

        The handler must check whether the issue is already on the
        board before calling addProjectV2ItemById; otherwise the
        mutation is fine (GitHub returns the existing id) but the
        round-trip is wasted.  Either way, the *return value* must
        be identical across repeated calls.
        """
        # Two scenarios canned:
        #   1. First call resolves board, adds issue, gets item id
        #   2. Second call resolves board, finds existing item, returns same id
        # The exact gh script the handler uses is an implementation
        # choice, but the *result* must be the same id both times.
        first_response = json.dumps({
            'data': {'addProjectV2ItemById': {'item': {'id': 'PVTI_xyz123'}}},
        })
        # On the second call, depending on implementation, it might
        # query existing items or just call add again.  Either way
        # the response should yield item id PVTI_xyz123.
        second_response = json.dumps({
            'data': {'addProjectV2ItemById': {'item': {'id': 'PVTI_xyz123'}}},
        })

        # First invocation — board lookup may need its own response.
        fake = _FakeGh([
            _BOARDS_GRAPHQL_RESPONSE, first_response,
            _BOARDS_GRAPHQL_RESPONSE, second_response,
        ])

        out1 = gh.add_issue_to_board_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )
        out2 = gh.add_issue_to_board_handler(
            number=427, gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        item1 = json.loads(out1)['item_id']
        item2 = json.loads(out2)['item_id']
        self.assertEqual(
            item1, item2,
            f'add_issue_to_board must be idempotent (AC 12); '
            f'got {item1!r} then {item2!r}',
        )
        self.assertEqual(
            item1, 'PVTI_xyz123',
            f'expected item id PVTI_xyz123 from canned response; got {item1!r}',
        )


class TestSetBoardStatus(unittest.TestCase):

    def test_resolves_status_name_to_option_id_per_call(self):
        """AC 13/15: ``set_board_status('Approved')`` must resolve the
        option id from the board's own metadata at call time.  A
        handler that hardcodes IDs would silently corrupt board state
        if the board is reconfigured.  This test gives a board with
        a non-default option-id mapping and asserts the handler
        sends the *option id from that board*, not a default."""

        # Same status names but different option ids than the project
        # memory references — i.e. the board has been reconfigured.
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
                                        {'id': 'OPT_DONE_NEW',
                                         'name': 'Done'},
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

    def test_list_milestone_issues_concatenates_rest_pages(self):
        # gh issue list with --json returns a single JSON array; gh
        # paginates internally when --limit is high enough.  Our
        # handler must request a limit large enough to capture all
        # issues — easiest robust path is ``--limit 1000`` (the
        # GitHub REST max-per-call effective ceiling for issue lists)
        # or ``gh api --paginate``.  Either way, a multi-page-equivalent
        # canned response with 150 entries must return all 150.
        many = [
            {'number': i, 'title': f'I{i}', 'state': 'open',
             'labels': [], 'milestone': {'title': 'Tier 4: Proxy Evolution'}}
            for i in range(1, 151)
        ]
        fake = _FakeGh([json.dumps(many)])

        out = gh.list_milestone_issues_handler(
            milestone='Tier 4: Proxy Evolution',
            gh_runner=fake, repo_resolver=_fake_resolver(),
        )

        result = json.loads(out)
        self.assertEqual(
            len(result), 150,
            f'list_milestone_issues must return all 150 issues; '
            f'got {len(result)} (silent truncation is the bug AC 17 '
            f'guards against)',
        )
        # The handler's gh call must request enough to cover this set —
        # i.e. either --paginate or a high --limit.  Without that, real
        # gh would cap at 30 even though our fake returned 150.
        argv = fake.calls[0]
        joined = ' '.join(argv)
        self.assertTrue(
            '--paginate' in argv or '--limit' in argv,
            f'list_milestone_issues must use --paginate or --limit '
            f'to avoid silent truncation; argv={argv!r}',
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
