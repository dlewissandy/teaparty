// Sidebar Projects section: job conversations across all workgroups in the org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';

export function renderProjectSection(store, container, orgId, filter) {
  const s = store.get();
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const projects = [];
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const job of (tree.jobs || [])) {
      projects.push({ job, workgroupId: wg.id, workgroupName: wg.name });
    }
  }

  const filtered = filterLower
    ? projects.filter(({ job }) => (job.title || job.id).toLowerCase().includes(filterLower))
    : projects;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No projects</span>';
    return;
  }

  container.innerHTML = filtered.map(({ job, workgroupId }) => {
    const name = job.title || 'Untitled';
    const itemId = `project:${job.id}`;
    const isActive = selection === itemId;
    return `<button
      class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}"
      data-action="select-project"
      data-item-id="${escapeHtml(itemId)}"
      data-workgroup-id="${escapeHtml(workgroupId)}"
      data-conversation-id="${escapeHtml(job.id)}"
      title="${escapeHtml(name)}"
    ><span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-project"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const workgroupId = btn.dataset.workgroupId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:conversation-selected', { workgroupId, conversationId });
    });
  });
}
