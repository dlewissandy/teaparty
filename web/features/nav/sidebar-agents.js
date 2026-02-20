// Sidebar Agents section: agents for the active org or workgroup.
// When scopeWgId is provided, shows all agents for that workgroup.
// Otherwise shows org-level coordinator agents (from the Administration workgroup).

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg } from '../../components/shared/avatar.js';

const ORG_AGENT_NAMES = new Set(['engagements-lead', 'projects-lead']);

export function renderAgentSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const workgroups = scopeWgId
    ? (s.data.workgroups || []).filter(w => w.id === scopeWgId)
    : (s.data.workgroups || []).filter(w => w.organization_id === orgId && w.name === 'Administration');
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;
  const thinkingMap = s.conversation.thinkingByConversation || {};

  const agentMap = new Map();
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const agent of (tree.agents || [])) {
      // In workgroup mode show all agents; in org mode show only org-level coordinators
      if (!scopeWgId && !ORG_AGENT_NAMES.has(agent.name)) continue;
      if (agentMap.has(agent.id)) continue;

      // Check if this agent is thinking
      const agentTaskConvIds = (tree.agentTasks || [])
        .filter(t => t.agent_id === agent.id && t.conversation_id)
        .map(t => t.conversation_id);
      const agentDirect = (tree.directs || []).find(c => c.sender_agent_id === agent.id || c.target_agent_id === agent.id);
      const allAgentConvIds = agentDirect
        ? [...agentTaskConvIds, agentDirect.id]
        : agentTaskConvIds;
      const isThinking = allAgentConvIds.some(cid => thinkingMap[cid]);

      agentMap.set(agent.id, { agent, workgroupId: wg.id, isThinking });
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

  container.innerHTML = filtered.map(({ agent, workgroupId, isThinking }) => {
    const itemId = `agent:${agent.id}`;
    const isActive = selection === itemId;
    const avatarSvg = generateBotSvg(agent.name);
    const presenceClass = isThinking ? 'thinking' : 'idle';
    const presenceTitle = isThinking ? 'Thinking...' : 'Idle';

    return `<button
      class="sidebar-nav-item sidebar-agent-item${isActive ? ' active' : ''}"
      data-action="select-agent"
      data-item-id="${escapeHtml(itemId)}"
      data-workgroup-id="${escapeHtml(workgroupId)}"
      data-agent-id="${escapeHtml(agent.id)}"
      title="${escapeHtml(agent.name)}"
    >
      <span class="sidebar-agent-avatar-wrap">${avatarSvg}</span>
      <span class="sidebar-nav-label">${escapeHtml(agent.name)}</span>
      <span class="sidebar-presence-dot ${presenceClass}" title="${presenceTitle}" aria-hidden="true"></span>
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
  });
}
