// Sidebar Jobs section: job conversations for the active workgroup.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

const removeSvg = `<svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

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
    return `<div class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}">
      <button class="sidebar-wg-select" data-action="select-job" data-item-id="${escapeHtml(itemId)}" data-conversation-id="${escapeHtml(job.id)}" title="${escapeHtml(name)}">
        <span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(name)}</span>
      </button>
      <button class="sidebar-member-remove" data-action="delete-job" data-conversation-id="${escapeHtml(job.id)}" data-workgroup-id="${escapeHtml(workgroupId)}" title="Delete job" aria-label="Delete ${escapeHtml(name)}">${removeSvg}</button>
    </div>`;
  }).join('');

  container.querySelectorAll('[data-action="select-job"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:conversation-selected', { workgroupId, conversationId });
    });
  });

  container.querySelectorAll('[data-action="delete-job"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const conversationId = btn.dataset.conversationId;
      const wgId = btn.dataset.workgroupId;
      if (!confirm('Delete this session?')) return;
      try {
        await api(`/api/workgroups/${wgId}/conversations/${conversationId}`, { method: 'DELETE' });
        btn.closest('.sidebar-nav-item')?.remove();
        if (store.get().nav.activeConversationId === conversationId) {
          store.update(st => {
            st.nav.activeConversationId = '';
            st.nav.sidebarSelection = '';
            st.conversation.messages = [];
          });
          store.notify('nav.activeConversationId');
        }
      } catch (err) {
        flash(err.message || 'Failed to delete session', 'error');
      }
    });
  });
}
