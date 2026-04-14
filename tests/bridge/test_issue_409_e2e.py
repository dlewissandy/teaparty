"""Issue #409 — end-to-end HTTP verification of project onboarding.

These tests drive the real aiohttp handlers in
``teaparty/bridge/server.py::TeaPartyBridge._handle_projects_create`` and
``_handle_projects_add`` through a live ``TestClient``, posting JSON on the
wire, so a regression that detaches the bridge endpoint from the unified
onboarding sequence cannot pass silently.

The finding from the Round 1 audit was that ``_scaffold_project_lead`` and
telemetry lived only in the MCP handler layer, so the bridge's dashboard
path silently produced incomplete projects. These tests lock that shut:
they hit the HTTP endpoint and then read the filesystem.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from types import MethodType
from typing import Any

import yaml

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from teaparty.bridge.server import TeaPartyBridge

SENTINEL = '⚠ No description — ask the project lead'


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-409-e2e-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _make_home(tmp: str) -> str:
    home = os.path.join(tmp, '.teaparty')
    mgmt = os.path.join(home, 'management')
    os.makedirs(mgmt, exist_ok=True)
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Management Team',
            'lead': 'office-manager',
            'humans': {'decider': 'alice'},
            'projects': [],
            'members': {'agents': ['office-manager'], 'skills': [], 'workgroups': []},
        }, f, sort_keys=False)
    return home


class _MiniBridge:
    """Minimal bridge mock that binds the real project-handler methods.

    ``_serialize_management_team`` is stubbed to a no-op because the test
    only cares about the side-effects the handler produces on disk and the
    ``ok: true`` envelope — the serialization is tested elsewhere.
    """

    def __init__(self, teaparty_home: str):
        self.teaparty_home = teaparty_home

    _handle_projects_add: Any = None
    _handle_projects_create: Any = None

    def _serialize_management_team(self, team, discovered_skills=None):
        return {'projects': [p['name'] for p in team.projects]}


async def _build_app(home: str) -> tuple[web.Application, _MiniBridge]:
    mini = _MiniBridge(home)
    mini._handle_projects_add = MethodType(
        TeaPartyBridge._handle_projects_add, mini,
    )
    mini._handle_projects_create = MethodType(
        TeaPartyBridge._handle_projects_create, mini,
    )
    app = web.Application()
    app.router.add_post('/api/projects/add', mini._handle_projects_add)
    app.router.add_post('/api/projects/create', mini._handle_projects_create)
    return app, mini


class TestBridgeCreateProjectE2E(unittest.IsolatedAsyncioTestCase):
    """POST /api/projects/create drives the full onboarding sequence."""

    async def asyncSetUp(self):
        self.tmp = _make_tmp(self)
        self.home = _make_home(self.tmp)
        app, _ = await _build_app(self.home)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_full_onboarding_via_http(self):
        proj_path = os.path.join(self.tmp, 'my-project')
        resp = await self.client.post(
            '/api/projects/create',
            json={
                'name': 'My Project',
                'path': proj_path,
                'decider': 'alice',
            },
        )
        self.assertEqual(resp.status, 200, await resp.text())
        body = await resp.json()
        self.assertTrue(body.get('ok'), body)
        self.assertIn(
            'my-project',
            body['management_team']['projects'],
            "bridge response must report the normalized project name",
        )

        # 1. project.yaml normalized name + lead + sentinel + Configuration
        py = os.path.join(proj_path, '.teaparty', 'project', 'project.yaml')
        with open(py) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'my-project')
        self.assertEqual(data['lead'], 'my-project-lead')
        self.assertEqual(data['description'], SENTINEL)
        self.assertIn('Configuration', data['workgroups'])

        # 2. .gitignore written
        with open(os.path.join(proj_path, '.gitignore')) as f:
            gi = f.read()
        self.assertIn('.teaparty/jobs/', gi)
        self.assertIn('*.db', gi)

        # 3. Initial commit present with exact message and required files
        subject = subprocess.run(
            ['git', 'log', '-1', '--format=%s'],
            cwd=proj_path, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(subject, 'chore: add TeaParty project configuration')
        tree = subprocess.run(
            ['git', 'ls-tree', '-r', '--name-only', 'HEAD'],
            cwd=proj_path, check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        self.assertIn('.gitignore', tree)
        self.assertIn('.teaparty/project/project.yaml', tree)

        # 4. Working tree clean — nothing left unstaged
        status = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=proj_path, check=True, capture_output=True, text=True,
        ).stdout
        self.assertEqual(
            status, '',
            f"bridge path must leave the working tree clean; got:\n{status!r}",
        )

        # 5. {name}-lead agent scaffolded in management catalog
        lead_dir = os.path.join(
            self.home, 'management', 'agents', 'my-project-lead',
        )
        for fname in ('agent.md', 'settings.yaml', 'pins.yaml'):
            self.assertTrue(
                os.path.isfile(os.path.join(lead_dir, fname)),
                f"bridge onboarding must scaffold {fname} in the management "
                f"catalog (audit round-1 finding); missing from {lead_dir}",
            )

        # 6. agent.md frontmatter has the spec-mandated fields
        with open(os.path.join(lead_dir, 'agent.md')) as f:
            content = f.read()
        import re
        m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
        self.assertIsNotNone(m)
        fm = yaml.safe_load(m.group(1))
        self.assertEqual(fm['model'], 'sonnet')
        self.assertEqual(fm['maxTurns'], 30)

    async def test_browser_minimal_payload_triggers_create_fallback(self):
        """Replay the exact payload the dashboard modal sends.

        ``index.html::showProjectModal`` POSTs ``{name, path}`` with no
        description or decider to /api/projects/add first, and on the
        ``'does not exist'`` error falls back to /api/projects/create.
        This test drives that full flow on a fresh path and then checks:

        - The second POST succeeds.
        - The returned management_team lists the normalized slug (so
          ``fetchAll()`` on the client will re-render it).
        - project.yaml uses the description sentinel because the frontend
          didn't send one.
        - The lead agent is scaffolded even though ``decider`` is empty.
        """
        proj_path = os.path.join(self.tmp, 'delta')
        payload = {'name': 'Delta', 'path': proj_path}

        # Step 1: frontend tries /add first
        resp_add = await self.client.post('/api/projects/add', json=payload)
        self.assertEqual(resp_add.status, 409)
        data_add = await resp_add.json()
        self.assertIn(
            'does not exist', data_add['error'],
            "the frontend fallback logic pattern-matches on 'does not "
            "exist'; the error string must still contain that phrase",
        )

        # Step 2: frontend falls back to /create
        resp_create = await self.client.post('/api/projects/create', json=payload)
        self.assertEqual(resp_create.status, 200, await resp_create.text())
        data_create = await resp_create.json()
        self.assertTrue(data_create['ok'])
        self.assertIn(
            'delta', data_create['management_team']['projects'],
            "the bridge response must include the normalized slug so the "
            "dashboard fetchAll() re-render shows the new project",
        )

        # Sentinel applied because frontend sent no description
        with open(os.path.join(proj_path, '.teaparty', 'project', 'project.yaml')) as f:
            pdata = yaml.safe_load(f)
        self.assertEqual(pdata['description'], SENTINEL)

        # No decider was sent; the project must inherit the management
        # team's decider — the human who runs this instance and therefore
        # actually initiated the project creation.
        self.assertEqual(
            pdata['humans']['decider'], 'alice',
            "dashboard flow with no decider must default to the management "
            "team's decider; agents can never be deciders",
        )

        # Lead agent scaffolded; body names the resolved decider
        lead_md = os.path.join(
            self.home, 'management', 'agents', 'delta-lead', 'agent.md',
        )
        self.assertTrue(os.path.isfile(lead_md))
        with open(lead_md) as f:
            self.assertIn(
                '**alice**', f.read(),
                "the lead agent prompt must name the resolved human decider",
            )

    async def test_duplicate_name_via_http_normalized(self):
        """A second POST with a differently-cased name hits the same slug."""
        proj1 = os.path.join(self.tmp, 'alpha')
        resp1 = await self.client.post(
            '/api/projects/create',
            json={'name': 'Alpha', 'path': proj1, 'decider': 'alice'},
        )
        self.assertEqual(resp1.status, 200)

        proj2 = os.path.join(self.tmp, 'alpha2')
        resp2 = await self.client.post(
            '/api/projects/create',
            json={'name': 'ALPHA', 'path': proj2, 'decider': 'alice'},
        )
        self.assertEqual(
            resp2.status, 409,
            "second create with the same normalized name must be rejected",
        )
        body = await resp2.json()
        self.assertIn('already exists', body['error'].lower())


class TestBridgeAddProjectE2E(unittest.IsolatedAsyncioTestCase):
    """POST /api/projects/add drives the full onboarding sequence."""

    async def asyncSetUp(self):
        self.tmp = _make_tmp(self)
        self.home = _make_home(self.tmp)
        app, _ = await _build_app(self.home)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_add_with_existing_git_repo(self):
        proj_path = os.path.join(self.tmp, 'beta')
        os.makedirs(proj_path)
        # Pre-existing git repo with one commit and a prior .gitignore.
        subprocess.run(['git', 'init'], cwd=proj_path, check=True, capture_output=True)
        with open(os.path.join(proj_path, '.gitignore'), 'w') as f:
            f.write('node_modules/\n')
        subprocess.run(
            ['git', '-c', 'user.email=t@t.x', '-c', 'user.name=t',
             'add', '.gitignore'],
            cwd=proj_path, check=True, capture_output=True,
        )
        subprocess.run(
            ['git', '-c', 'user.email=t@t.x', '-c', 'user.name=t',
             'commit', '-m', 'initial'],
            cwd=proj_path, check=True, capture_output=True,
        )

        resp = await self.client.post(
            '/api/projects/add',
            json={
                'name': 'PyBayes ',
                'path': proj_path,
                'description': 'Bayesian library',
                'decider': 'alice',
            },
        )
        self.assertEqual(resp.status, 200, await resp.text())
        body = await resp.json()
        self.assertIn('pybayes', body['management_team']['projects'])

        # .gitignore preserved + stanza appended
        with open(os.path.join(proj_path, '.gitignore')) as f:
            gi = f.read()
        self.assertIn('node_modules/', gi)
        self.assertIn('.teaparty/jobs/', gi)

        # project.yaml has normalized name and supplied description
        with open(os.path.join(proj_path, '.teaparty', 'project', 'project.yaml')) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'pybayes')
        self.assertEqual(data['lead'], 'pybayes-lead')
        self.assertEqual(data['description'], 'Bayesian library')
        self.assertIn('Configuration', data['workgroups'])

        # Lead agent scaffolded
        self.assertTrue(os.path.isfile(os.path.join(
            self.home, 'management', 'agents', 'pybayes-lead', 'agent.md',
        )))

        # Initial commit added on top of the pre-existing one
        log = subprocess.run(
            ['git', 'log', '--format=%s'],
            cwd=proj_path, check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        self.assertEqual(log[0], 'chore: add TeaParty project configuration')
        self.assertEqual(log[1], 'initial')


class TestMcpHandlerEndToEnd(unittest.TestCase):
    """Drive the MCP handler entry points (the tool-call path used by agents).

    ``AddProject`` / ``CreateProject`` tools defined in
    ``teaparty/mcp/server/main.py`` call these handlers directly. This test
    bypasses the FastMCP registration machinery (it would require starting
    a real MCP server) and instead calls the same callables the tool
    wrappers call, so the assurance still covers the handler layer end to end.
    """

    def test_create_project_handler_produces_full_state(self):
        tmp = tempfile.mkdtemp(prefix='teaparty-409-mcp-')
        self.addCleanup(shutil.rmtree, tmp, True)
        home = _make_home(tmp)
        proj_path = os.path.join(tmp, 'gamma')

        from teaparty.mcp.tools.config_crud import create_project_handler
        result = json.loads(create_project_handler(
            name='Gamma Project',
            path=proj_path,
            decider='alice',
            teaparty_home=home,
        ))
        self.assertTrue(result.get('success'), result)

        # Normalized name present in the response message
        self.assertIn('gamma-project', result.get('message', ''))

        # Full state on disk
        with open(os.path.join(proj_path, '.teaparty', 'project', 'project.yaml')) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'gamma-project')
        self.assertEqual(data['lead'], 'gamma-project-lead')
        self.assertIn('Configuration', data['workgroups'])

        self.assertTrue(os.path.isfile(
            os.path.join(home, 'management', 'agents',
                         'gamma-project-lead', 'agent.md'),
        ))

        subject = subprocess.run(
            ['git', 'log', '-1', '--format=%s'],
            cwd=proj_path, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(subject, 'chore: add TeaParty project configuration')


if __name__ == '__main__':
    unittest.main()
