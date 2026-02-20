// Sidebar engagements section: cross-org engagements for the active org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';

export function renderEngagementSection(store, container, orgId, filter) {
  const s = store.get();
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  // Collect engagements across all workgroups, dedup by engagement id
  const seen = new Set();
  const engagements = [];

  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree?.engagements) continue;
    for (const eng of tree.engagements) {
      if (seen.has(eng.id)) continue;
      seen.add(eng.id);
      // Resolve the conversation id for this workgroup's side of the engagement
      const convId = eng.source_workgroup_id === wg.id
        ? eng.source_conversation_id
        : eng.target_conversation_id;
      engagements.push({ eng, workgroupId: wg.id, convId: convId || '' });
    }
  }

  const filtered = filterLower
    ? engagements.filter(({ eng }) => eng.title.toLowerCase().includes(filterLower))
    : engagements;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No engagements</span>';
    return;
  }

  container.innerHTML = filtered.map(({ eng, workgroupId, convId }) => {
    const isActive = selection === `engagement:${eng.id}`;
    const status = eng.status || 'proposed';
    const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);

    return `<button
      class="sidebar-nav-item sidebar-engagement-item${isActive ? ' active' : ''}"
      data-action="open-engagement"
      data-workgroup-id="${escapeHtml(workgroupId)}"
      data-engagement-id="${escapeHtml(eng.id)}"
      data-conversation-id="${escapeHtml(convId)}"
      title="${escapeHtml(eng.title)}"
    >
      <span class="sidebar-nav-label">${escapeHtml(eng.title)}</span>
      <span class="sidebar-engagement-badge sidebar-engagement-badge--${escapeHtml(status)}" title="${statusLabel}">${escapeHtml(statusLabel)}</span>
    </button>`;
  }).join('');

  container.querySelectorAll('[data-action="open-engagement"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      const engagementId = btn.dataset.engagementId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => {
        s.nav.sidebarSelection = `engagement:${engagementId}`;
        if (conversationId) {
          s.nav.activeWorkgroupId = workgroupId;
          s.nav.activeConversationId = conversationId;
        }
      });
      bus.emit('nav:engagement-selected', { workgroupId, engagementId, conversationId });
    });
  });
}
