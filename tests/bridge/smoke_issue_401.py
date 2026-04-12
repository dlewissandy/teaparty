"""Issue #401: headless browser smoke test.

Verifies that the anchor refactor actually works in a real rendered DOM,
not just in the static HTML source. Scope:

1. Home page renders ``<a class="org-card">`` and ``<a class="pc-header">``
   anchors with real ``href`` attributes.
2. ``pc-esc-item`` row body is an inner anchor with computed
   ``display: contents`` so the flex layout is preserved.
3. Attention-dot slot is exactly one element (anchor when escalation,
   placeholder anchor otherwise).
4. Plain click on a navigating anchor replaces the current page.
5. Ctrl/Meta+click on the same anchor opens the target URL in a new tab
   (browser-native gesture preserved).
6. Config page renders the breadcrumb "Home" as
   ``<a href="index.html">``, ``itemCard`` entries as
   ``<a class="item-link">`` with ``display: contents``, and zero
   rendered elements carry ``onclick`` handlers that assign to
   ``location.href``.
7. Artifacts page does not render ``.artifact-job-link`` as a ``<div>``.

This smoke test requires Playwright and a running bridge server. It is
**not** part of the default ``uv run pytest`` suite — run it manually::

    uv run python -m teaparty.bridge --teaparty-home ./.teaparty --port 8099 &
    uv run --with playwright python tests/bridge/smoke_issue_401.py
    kill %1

Exits non-zero on any failure.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8099'


def check_home(page) -> list[str]:
    errors: list[str] = []
    page.goto(BASE + '/')
    page.wait_for_selector('a.org-card', timeout=5000)
    page.wait_for_selector('a.pc-header', timeout=5000)

    org_cards = page.locator('a.org-card').all()
    if len(org_cards) < 2:
        errors.append(f'home: expected >=2 org-cards, got {len(org_cards)}')
    for oc in org_cards:
        href = oc.get_attribute('href')
        if not href or href.startswith('javascript:'):
            errors.append(f'home: org-card has no real href: {href!r}')

    pc_headers = page.locator('a.pc-header').all()
    for ph in pc_headers:
        href = ph.get_attribute('href')
        if not href or 'config.html?project=' not in href:
            errors.append(f'home: pc-header href wrong: {href!r}')

    has_open_page = page.evaluate('typeof openPage')
    if has_open_page != 'undefined':
        errors.append(f'home: openPage helper still defined (typeof={has_open_page})')

    blanks = page.locator('a[target="_blank"]').all()
    for b in blanks:
        href = b.get_attribute('href') or ''
        errors.append(f'home: found target=_blank on {href!r}')

    esc_items = page.locator('.pc-esc-item').all()
    for item in esc_items:
        body_anchors = item.locator('a[href^="chat.html?conv="]').all()
        if not body_anchors:
            errors.append('home pc-esc-item: no chat.html body anchor found')
        dots = item.locator('a.attention-dot, a[style*="width:6px"]').all()
        if len(dots) != 1:
            errors.append(
                f'home pc-esc-item: expected exactly 1 dot-slot anchor, got {len(dots)}'
            )
        if body_anchors:
            disp = body_anchors[0].evaluate('el => getComputedStyle(el).display')
            if disp != 'contents':
                errors.append(
                    f'home pc-esc-item body anchor display={disp}, expected contents'
                )

    if org_cards:
        first = org_cards[0]
        href = first.get_attribute('href')
        with page.expect_navigation(timeout=5000):
            first.click()
        if page.url.rstrip('/').split('/')[-1] != href:
            errors.append(
                f'home→org-card: expected navigation to {href!r}, landed on {page.url}'
            )

    return errors


def check_config(page) -> list[str]:
    errors: list[str] = []
    page.goto(BASE + '/config.html')
    page.wait_for_selector('.item', timeout=5000)

    home_crumbs = page.locator('.breadcrumb-bar a[href="index.html"]').all()
    if not home_crumbs:
        errors.append('config: breadcrumb Home is not an <a href="index.html">')

    item_links = page.locator('a.item-link').all()
    for link in item_links:
        href = link.get_attribute('href') or ''
        if not href.startswith('artifacts.html?file='):
            errors.append(f'config: item-link href unexpected: {href!r}')

    for link in item_links[:3]:
        disp = link.evaluate('el => getComputedStyle(el).display')
        if disp != 'contents':
            errors.append(f'config: item-link display={disp}, expected contents')

    bad = page.eval_on_selector_all(
        '[onclick]',
        'els => els.filter(e => /location\\s*\\.\\s*href/.test(e.getAttribute("onclick") || "")).length',
    )
    if bad:
        errors.append(f'config: {bad} rendered elements use onclick=location.href')

    if home_crumbs:
        with page.expect_navigation(timeout=5000):
            home_crumbs[0].click()
        if 'index.html' not in page.url and not page.url.endswith('/'):
            errors.append(f'config Home breadcrumb: expected index.html, got {page.url}')

    return errors


def check_artifacts(page) -> list[str]:
    errors: list[str] = []
    page.goto(BASE + '/artifacts.html')
    page.wait_for_load_state('domcontentloaded', timeout=5000)
    if page.locator('div.artifact-job-link').all():
        errors.append('artifacts: artifact-job-link still rendered as <div>')
    return errors


def check_modifier_click(page, browser_context) -> list[str]:
    """Ctrl/Meta+click on an anchor must open a new tab with the target URL."""
    errors: list[str] = []
    page.goto(BASE + '/')
    page.wait_for_selector('a.org-card', timeout=5000)
    target_href = page.locator('a.org-card').first.get_attribute('href')

    for modifier in (['Control'], ['Meta']):
        try:
            with browser_context.expect_page(timeout=3000) as new_page_info:
                page.locator('a.org-card').first.click(modifiers=modifier)
            new_page = new_page_info.value
            new_page.wait_for_load_state('domcontentloaded')
            new_page.wait_for_url(lambda u: 'about:blank' not in u, timeout=5000)
            if target_href and target_href in new_page.url:
                new_page.close()
                return []
            errors.append(
                f'{modifier}+click: new tab url={new_page.url} (expected href={target_href})'
            )
            new_page.close()
        except Exception as e:
            errors.append(f'{modifier}+click failed: {e}')
    return errors


def main() -> int:
    all_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context()
            all_errors += check_home(ctx.new_page())
            all_errors += check_config(ctx.new_page())
            all_errors += check_artifacts(ctx.new_page())

            ctx2 = browser.new_context()
            all_errors += check_modifier_click(ctx2.new_page(), ctx2)
        finally:
            browser.close()

    if all_errors:
        print('SMOKE TEST FAILURES:')
        for e in all_errors:
            print(f'  - {e}')
        return 1
    print('SMOKE TEST OK: anchors render, plain-click navigates, Ctrl/Meta-click opens new tab.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
