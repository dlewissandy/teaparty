// Sidebar Projects section: actual Project records from the API.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';

export function renderProjectSection(store, container, orgId, filter) {
  const s = store.get();
  const projects = (s.data.projects || []).filter(p => p.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const filtered = filterLower
    ? projects.filter(p => p.name.toLowerCase().includes(filterLower))
    : projects;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No projects</span>';
    return;
  }

  container.innerHTML = filtered.map(p => {
    const itemId = `project:${p.id}`;
    const isActive = selection === itemId;
    return `<button
      class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}"
      data-action="select-project"
      data-item-id="${escapeHtml(itemId)}"
      data-conversation-id="${escapeHtml(p.conversation_id || '')}"
      title="${escapeHtml(p.name)}"
    ><span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(p.name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-project"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      if (conversationId) {
        bus.emit('nav:conversation-selected', { workgroupId: null, conversationId });
      }
    });
  });
}
