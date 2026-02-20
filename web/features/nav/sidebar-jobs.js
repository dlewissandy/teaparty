// Sidebar Jobs section: job conversations for the active workgroup.

import { bus } from '../../core/bus.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';

export function renderJobSection(store, container, workgroupId, filter) {
  const s = store.get();
  const tree = s.data.treeData[workgroupId];
  const jobs = tree?.jobs || [];
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const filtered = filterLower
    ? jobs.filter(j => jobDisplayName(j).toLowerCase().includes(filterLower))
    : jobs;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No jobs</span>';
    return;
  }

  container.innerHTML = filtered.map(job => {
    const name = jobDisplayName(job);
    const itemId = `job:${job.id}`;
    const isActive = selection === itemId;
    return `<button
      class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}"
      data-action="select-job"
      data-item-id="${escapeHtml(itemId)}"
      data-conversation-id="${escapeHtml(job.id)}"
      title="${escapeHtml(name)}"
    ><span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-job"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:conversation-selected', { workgroupId, conversationId });
    });
  });
}
