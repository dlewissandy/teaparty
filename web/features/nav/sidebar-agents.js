// Sidebar Agents section: agents for the active org or workgroup.
// When scopeWgId is provided, shows agents for that workgroup only.
// Otherwise shows all agents across all workgroups in the org,
// plus any unassigned agents (those whose workgroup was deleted).

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';

const removeSvg = `<svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

export function renderAgentSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const workgroups = scopeWgId
    ? (s.data.workgroups || []).filter(w => w.id === scopeWgId)
    : (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const currentUserId = s.auth.user?.id;
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  const isOwner = org?.owner_id === currentUserId;

  const agentMap = new Map();
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const agent of (tree.agents || [])) {
      if (agentMap.has(agent.id)) continue;
      agentMap.set(agent.id, { agent, workgroupId: wg.id });
    }
  }

  // Include unassigned agents (no workgroup) for this org
  if (!scopeWgId) {
    const unassigned = (s.data.unassignedAgents || {})[orgId] || [];
    for (const agent of unassigned) {
      if (agentMap.has(agent.id)) continue;
      agentMap.set(agent.id, { agent, workgroupId: '' });
    }
  }

  const agents = Array.from(agentMap.values());
  agents.sort((a, b) => a.agent.name.localeCompare(b.agent.name));
  const filtered = filterLower
    ? agents.filter(({ agent }) => agent.name.toLowerCase().includes(filterLower))
    : agents;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No agents</span>';
    return;
  }

  container.innerHTML = filtered.map(({ agent, workgroupId }) => {
    const itemId = `agent:${agent.id}`;
    const isActive = selection === itemId;
    const avatarSvg = generateBotSvg(agent.name);
    const removeBtn = (isOwner && !agent.is_lead)
      ? `<button class="sidebar-member-remove" data-action="delete-agent" data-workgroup-id="${escapeHtml(workgroupId)}" data-org-id="${escapeHtml(orgId)}" data-agent-id="${escapeHtml(agent.id)}" data-agent-name="${escapeHtml(agent.name)}" title="${workgroupId ? 'Remove from workgroup' : 'Delete agent'}" aria-label="Remove ${escapeHtml(agent.name)}">${removeSvg}</button>`
      : '';
    return `<div class="sidebar-nav-item sidebar-agent-item${isActive ? ' active' : ''}">
      <button class="sidebar-agent-select" data-action="select-agent" data-item-id="${escapeHtml(itemId)}" data-workgroup-id="${escapeHtml(workgroupId)}" data-agent-id="${escapeHtml(agent.id)}" draggable="true" title="${escapeHtml(agent.name)}">
        <span class="sidebar-agent-avatar-wrap">${avatarSvg}</span>
        <span class="sidebar-nav-label">${escapeHtml(agent.name)}</span>
      </button>
      ${removeBtn}
    </div>`;
  }).join('');

  container.querySelectorAll('[data-action="select-agent"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:agent-selected', {
        agentId: btn.dataset.agentId,
        workgroupId: btn.dataset.workgroupId,
      });
    });
    btn.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/x-teaparty-agent', JSON.stringify({
        agentId: btn.dataset.agentId,
        workgroupId: btn.dataset.workgroupId,
      }));
      e.dataTransfer.effectAllowed = 'move';
      btn.closest('.sidebar-agent-item')?.classList.add('dragging');
    });
    btn.addEventListener('dragend', () => btn.closest('.sidebar-agent-item')?.classList.remove('dragging'));
  });

  container.querySelectorAll('[data-action="delete-agent"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const workgroupId = btn.dataset.workgroupId;
      const agentId = btn.dataset.agentId;
      const name = btn.dataset.agentName;
      const action = workgroupId ? 'Remove' : 'Delete';
      if (!confirm(`${action} agent "${name}"?`)) return;
      try {
        if (workgroupId) {
          await api(`/api/workgroups/${workgroupId}/agents/${agentId}`, { method: 'DELETE' });
        } else {
          const oId = btn.dataset.orgId;
          await api(`/api/organizations/${oId}/agents/${agentId}`, { method: 'DELETE' });
        }
        flash(`Agent "${name}" ${workgroupId ? 'removed' : 'deleted'}`, 'success');
        btn.closest('.sidebar-nav-item')?.remove();
      } catch (err) {
        flash(err.message || 'Failed to delete agent', 'error');
      }
    });
  });
}
