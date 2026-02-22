// Sidebar Agents section: agents for the active org or workgroup.
// When scopeWgId is provided, shows agents for that workgroup only.
// Otherwise shows all agents across all workgroups in the org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg } from '../../components/shared/avatar.js';

export function renderAgentSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const workgroups = scopeWgId
    ? (s.data.workgroups || []).filter(w => w.id === scopeWgId)
    : (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const agentMap = new Map();
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const agent of (tree.agents || [])) {
      if (agentMap.has(agent.id)) continue;
      agentMap.set(agent.id, { agent, workgroupId: wg.id });
    }
  }

  const agents = Array.from(agentMap.values());
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
    return `<button
      class="sidebar-nav-item sidebar-agent-item${isActive ? ' active' : ''}"
      data-action="select-agent"
      data-item-id="${escapeHtml(itemId)}"
      data-workgroup-id="${escapeHtml(workgroupId)}"
      data-agent-id="${escapeHtml(agent.id)}"
      draggable="true"
      title="${escapeHtml(agent.name)}"
    >
      <span class="sidebar-agent-avatar-wrap">${avatarSvg}</span>
      <span class="sidebar-nav-label">${escapeHtml(agent.name)}</span>
    </button>`;
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
      btn.classList.add('dragging');
    });
    btn.addEventListener('dragend', () => btn.classList.remove('dragging'));
  });
}
