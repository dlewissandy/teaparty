// Quick switcher: Cmd+K overlay for fast navigation across orgs, workgroups, and conversations.

import { bus } from '../../core/bus.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';

let _store = null;
let _selectedIndex = -1;
let _results = [];

export function initQuickSwitcher(store) {
  _store = store;

  // Keyboard shortcut to open
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openSwitcher();
    }
  });

  // Backdrop click closes
  const backdrop = document.querySelector('#quick-switcher .quick-switcher-backdrop');
  if (backdrop) backdrop.addEventListener('click', closeSwitcher);

  // Input handler
  const input = document.getElementById('quick-switcher-input');
  if (input) {
    input.addEventListener('input', () => renderResults(input.value.trim()));
    input.addEventListener('keydown', handleKeyNav);
  }

  // Bus-based open
  bus.on('nav:quick-switcher-open', openSwitcher);
}

function openSwitcher() {
  const el = document.getElementById('quick-switcher');
  if (!el) return;
  el.classList.remove('hidden');
  el.setAttribute('aria-hidden', 'false');
  _selectedIndex = -1;
  _results = [];
  const input = document.getElementById('quick-switcher-input');
  if (input) {
    input.value = '';
    input.focus();
  }
  renderResults('');
}

function closeSwitcher() {
  const el = document.getElementById('quick-switcher');
  if (!el) return;
  el.classList.add('hidden');
  el.setAttribute('aria-hidden', 'true');
  _selectedIndex = -1;
  _results = [];
}

function handleKeyNav(e) {
  if (e.key === 'Escape') {
    closeSwitcher();
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _selectedIndex = Math.min(_selectedIndex + 1, _results.length - 1);
    updateSelection();
    return;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    _selectedIndex = Math.max(_selectedIndex - 1, 0);
    updateSelection();
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    if (_selectedIndex >= 0 && _results[_selectedIndex]) {
      activateResult(_results[_selectedIndex]);
    }
  }
}

function updateSelection() {
  const container = document.getElementById('quick-switcher-results');
  if (!container) return;
  container.querySelectorAll('.qs-result-item').forEach((el, i) => {
    el.classList.toggle('selected', i === _selectedIndex);
    if (i === _selectedIndex) el.scrollIntoView({ block: 'nearest' });
  });
}

function buildResults(query) {
  const s = _store.get();
  const q = (query || '').toLowerCase();
  const results = [];

  for (const org of (s.data.organizations || [])) {
    for (const wg of (s.data.workgroups || []).filter(w => w.organization_id === org.id)) {
      const tree = s.data.treeData[wg.id];
      if (!tree) continue;

      // Job conversations
      for (const conv of (tree.jobs || [])) {
        if (conv.kind === 'admin') continue;
        const name = jobDisplayName(conv);
        if (!q || name.toLowerCase().includes(q) || wg.name.toLowerCase().includes(q)) {
          results.push({
            type: 'conversation',
            label: name,
            sublabel: `${org.name} / ${wg.name}`,
            workgroupId: wg.id,
            conversationId: conv.id,
          });
        }
      }

      // DM conversations
      for (const conv of (tree.directs || [])) {
        const name = conv.name || conv.topic || 'Direct message';
        if (!q || name.toLowerCase().includes(q)) {
          results.push({
            type: 'dm',
            label: name,
            sublabel: `${org.name} / ${wg.name}`,
            workgroupId: wg.id,
            conversationId: conv.id,
          });
        }
      }

      // Agents
      for (const agent of (tree.agents || [])) {
        if (!q || agent.name.toLowerCase().includes(q)) {
          results.push({
            type: 'agent',
            label: agent.name,
            sublabel: `${org.name} / ${wg.name}`,
            workgroupId: wg.id,
            agentId: agent.id,
          });
        }
      }
    }
  }

  return results;
}

function renderResults(query) {
  const container = document.getElementById('quick-switcher-results');
  if (!container) return;

  _results = buildResults(query);
  _selectedIndex = _results.length > 0 ? 0 : -1;

  if (!_results.length) {
    container.innerHTML = '<p class="qs-empty">No results</p>';
    return;
  }

  // Group by type
  const grouped = { conversation: [], dm: [], agent: [] };
  for (const r of _results) {
    (grouped[r.type] || grouped.conversation).push(r);
  }

  const labelMap = { conversation: 'Conversations', dm: 'Direct Messages', agent: 'Agents' };
  let globalIdx = 0;
  let html = '';

  for (const [type, items] of Object.entries(grouped)) {
    if (!items.length) continue;
    html += `<div class="qs-group-label">${escapeHtml(labelMap[type])}</div>`;
    for (const item of items) {
      const isSelected = globalIdx === _selectedIndex;
      html += `<button
        class="qs-result-item${isSelected ? ' selected' : ''}"
        data-result-index="${globalIdx}"
        role="option"
        aria-selected="${isSelected}"
      >
        <span class="qs-result-icon">${typeIcon(type)}</span>
        <span class="qs-result-body">
          <span class="qs-result-label">${escapeHtml(item.label)}</span>
          <span class="qs-result-sublabel">${escapeHtml(item.sublabel)}</span>
        </span>
      </button>`;
      globalIdx++;
    }
  }

  container.innerHTML = html;

  container.querySelectorAll('.qs-result-item').forEach(btn => {
    btn.addEventListener('mouseenter', () => {
      _selectedIndex = Number(btn.dataset.resultIndex);
      updateSelection();
    });
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.resultIndex);
      if (_results[idx]) activateResult(_results[idx]);
    });
  });
}

function activateResult(result) {
  closeSwitcher();
  if (result.type === 'conversation' || result.type === 'dm') {
    _store.update(s => {
      s.nav.activeWorkgroupId = result.workgroupId;
      s.nav.activeConversationId = result.conversationId;
    });
    bus.emit('nav:conversation-selected', {
      workgroupId: result.workgroupId,
      conversationId: result.conversationId,
    });
  } else if (result.type === 'agent') {
    bus.emit('nav:agent-dm', { workgroupId: result.workgroupId, agentId: result.agentId });
  }
}

function typeIcon(type) {
  if (type === 'conversation') {
    return `<svg viewBox="0 0 20 20" fill="none" width="14" height="14"><path d="M4 7h12M4 13h12M8 3l-2 14M14 3l-2 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
  }
  if (type === 'dm') {
    return `<svg viewBox="0 0 20 20" fill="none" width="14" height="14"><path d="M3.5 4.5h13a1 1 0 011 1v8a1 1 0 01-1 1H6l-3.5 2v-11a1 1 0 011-1Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  }
  if (type === 'agent') {
    return `<svg viewBox="0 0 20 20" fill="none" width="14" height="14"><rect x="4" y="6" width="12" height="10" rx="3" stroke="currentColor" stroke-width="1.4"/><path d="M10 3v3M7.5 11h.01M12.5 11h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
  }
  return '';
}
