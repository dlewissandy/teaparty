// Chat header: conversation name, breadcrumb context, and icon button wiring.

import { escapeHtml, jobDisplayName } from '../../core/utils.js';
import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { flash } from '../../components/shared/flash.js';
import { agentName, memberName } from '../../components/shared/identity.js';

let _store = null;

// ─── Label helpers ─────────────────────────────────────────────────────────

function conversationLabel(store, workgroupId, conversationId) {
  const s = store.get();
  const data = s.data.treeData[workgroupId];
  if (!data) return 'Conversation';

  const jobConv = data.jobs?.find(c => c.id === conversationId);
  if (jobConv) {
    if (jobConv.kind === 'admin') {
      if (data.workgroup.name === 'Administration' && !data.workgroup.organization_id) {
        return 'System Administration';
      }
      if (data.workgroup.name === 'Administration' && data.workgroup.organization_name) {
        return `Org Admin - ${data.workgroup.organization_name}`;
      }
      return `Admin - ${data.workgroup.name}`;
    }
    return jobDisplayName(jobConv);
  }

  const direct = data.directs?.find(c => c.id === conversationId);
  if (direct) {
    if (direct.topic.startsWith('dma:')) {
      const agentId = direct.topic.split(':')[2] || '';
      return agentName(workgroupId, agentId);
    }
    const parts = direct.topic.split(':');
    const userId = s.auth.user?.id;
    const otherUserId = parts.find(p => p !== 'dm' && p !== userId) || '';
    return memberName(workgroupId, otherUserId);
  }

  return 'Conversation';
}

function conversationContextLabel(store, workgroupId, conversationId) {
  const s = store.get();
  const data = s.data.treeData[workgroupId];
  if (!data) return '';

  const wgName = data.workgroup?.name || '';
  const orgName = data.workgroup?.organization_name || '';

  // Check if it's admin
  const jobConv = data.jobs?.find(c => c.id === conversationId);
  if (jobConv?.kind === 'admin') {
    if (orgName) return `${orgName} \u203A Administration`;
    return 'Administration';
  }

  if (orgName) return `${orgName} \u203A ${wgName}`;
  return wgName;
}

/** Determine if the active conversation is for a job (to show job-specific menu items). */
function getActiveConvKind(store) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;
  if (!wgId || !convId) return null;
  const data = s.data.treeData[wgId];
  const job = data?.jobs?.find(c => c.id === convId);
  return job?.kind || null;
}

function getActiveJobRecord(store) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;
  if (!wgId || !convId) return null;
  const data = s.data.treeData[wgId];
  return data?.jobRecords?.find(j => j.conversation_id === convId) || null;
}

// ─── Render ────────────────────────────────────────────────────────────────

function updateHeader(store) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;

  const titleEl = document.getElementById('chat-title');
  const contextEl = document.getElementById('chat-context');

  if (!wgId || !convId) {
    if (titleEl) titleEl.textContent = '\u00A0';
    if (contextEl) contextEl.textContent = '';
    return;
  }

  const label = conversationLabel(store, wgId, convId);
  const context = conversationContextLabel(store, wgId, convId);

  if (titleEl) titleEl.textContent = label;
  if (contextEl) contextEl.textContent = context;

  // Job-specific menu items
  const jobRecord = getActiveJobRecord(store);
  const isJob = Boolean(jobRecord);
  const canComplete = isJob && jobRecord.status !== 'completed' && jobRecord.status !== 'cancelled';

  const completeBtn = document.getElementById('job-complete-btn');
  const deleteBtn = document.getElementById('job-delete-btn');
  if (completeBtn) completeBtn.classList.toggle('hidden', !canComplete);
  if (deleteBtn) deleteBtn.classList.toggle('hidden', !isJob);
}

// ─── Menu actions ──────────────────────────────────────────────────────────

async function handleMenuAction(store, action) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;

  if (action === 'chat-copy') {
    const messages = s.conversation.messages || [];
    if (!messages.length) { flash('No messages to copy', 'info'); return; }
    const lines = messages.map(m => {
      const data = store.get().data.treeData[wgId];
      const agent = m.sender_agent_id ? data?.agents?.find(a => a.id === m.sender_agent_id) : null;
      const member = m.sender_user_id ? data?.members?.find(mb => mb.user_id === m.sender_user_id) : null;
      const sender = agent?.name || member?.name || member?.email || (m.sender_type === 'system' ? 'System' : 'Unknown');
      const time = new Date(m.created_at).toLocaleString();
      return `${sender} (${time}):\n${m.content}`;
    });
    try {
      await navigator.clipboard.writeText(lines.join('\n\n'));
      flash('Chat copied to clipboard', 'success');
    } catch {
      flash('Failed to copy to clipboard', 'error');
    }
    return;
  }

  if (action === 'chat-archive' || action === 'chat-unarchive') {
    const archiving = action === 'chat-archive';
    try {
      await api(`/api/workgroups/${wgId}/conversations/${convId}`, {
        method: 'PATCH',
        body: { is_archived: archiving },
      });
      flash(archiving ? 'Archived' : 'Unarchived', 'success');
      bus.emit('chat:conversation-updated', { wgId, convId });
    } catch (err) {
      flash(err.message || 'Failed to update archive status', 'error');
    }
    return;
  }

  if (action === 'chat-clear-history') {
    const confirmed = window.confirm('Clear all messages in this conversation? This cannot be undone.');
    if (!confirmed) return;
    try {
      const result = await api(`/api/workgroups/${wgId}/conversations/${convId}/messages`, {
        method: 'DELETE',
      });
      store.update(st => {
        st.conversation.messages = [];
        delete st.conversation.thinkingByConversation[convId];
      });
      store.notify('conversation.messages');
      const deleted = Number(result?.deleted_messages || 0);
      flash(deleted > 0 ? `Cleared ${deleted} message${deleted === 1 ? '' : 's'}` : 'History already empty', 'success');
    } catch (err) {
      flash(err.message || 'Failed to clear history', 'error');
    }
    return;
  }

  if (action === 'job-complete') {
    const jobRecord = getActiveJobRecord(store);
    if (!jobRecord) return;
    try {
      await api(`/api/jobs/${jobRecord.id}`, {
        method: 'PATCH',
        body: { status: 'completed' },
      });
      store.update(st => { delete st.conversation.thinkingByConversation[convId]; });
      flash('Job completed', 'success');
      bus.emit('chat:conversation-updated', { wgId, convId });
    } catch (err) {
      flash(err.message || 'Failed to complete job', 'error');
    }
    return;
  }

  if (action === 'job-delete') {
    const jobRecord = getActiveJobRecord(store);
    if (!jobRecord) return;
    const confirmed = window.confirm('Delete this job and its conversation? This cannot be undone.');
    if (!confirmed) return;
    try {
      await api(`/api/jobs/${jobRecord.id}`, { method: 'DELETE' });
      store.update(st => { delete st.conversation.thinkingByConversation[convId]; });
      flash('Job deleted', 'success');
      bus.emit('chat:conversation-deleted', { wgId, convId });
      store.update(st => {
        st.nav.activeConversationId = '';
        st.nav.activeWorkgroupId = '';
        st.conversation.messages = [];
      });
      store.notify('nav.activeConversationId');
    } catch (err) {
      flash(err.message || 'Failed to delete job', 'error');
    }
    return;
  }
}

// ─── Init ──────────────────────────────────────────────────────────────────

export function initChatHeader(store) {
  _store = store;

  // Subscribe to conversation changes
  store.on('nav.activeConversationId', () => updateHeader(store));
  store.on('data.treeData', () => updateHeader(store));

  // Files button: toggle right panel to files tab
  document.getElementById('btn-toggle-files')?.addEventListener('click', () => {
    const s = store.get();
    if (s.panels.rightPanelOpen && s.panels.rightPanelTab === 'files') {
      store.update(st => { st.panels.rightPanelOpen = false; });
    } else {
      store.update(st => {
        st.panels.rightPanelOpen = true;
        st.panels.rightPanelTab = 'files';
      });
    }
    store.notify('panels.rightPanelOpen');
  });

  // Info button: toggle right panel to info tab
  document.getElementById('btn-toggle-info')?.addEventListener('click', () => {
    const s = store.get();
    if (s.panels.rightPanelOpen && s.panels.rightPanelTab === 'info') {
      store.update(st => { st.panels.rightPanelOpen = false; });
    } else {
      store.update(st => {
        st.panels.rightPanelOpen = true;
        st.panels.rightPanelTab = 'info';
      });
    }
    store.notify('panels.rightPanelOpen');
  });

  // Chat menu toggle
  const chatMenuBtn = document.getElementById('chat-menu-btn');
  const chatMenuDropdown = document.getElementById('chat-menu-dropdown');

  chatMenuBtn?.addEventListener('click', e => {
    e.stopPropagation();
    const opening = chatMenuDropdown?.classList.contains('hidden');
    chatMenuDropdown?.classList.toggle('hidden');

    if (opening && chatMenuDropdown) {
      // Update archive button label
      const archiveBtn = document.getElementById('chat-archive-btn');
      if (archiveBtn) {
        const s = store.get();
        const wgId = s.nav.activeWorkgroupId;
        const convId = s.nav.activeConversationId;
        const data = s.data.treeData[wgId];
        const conv = data?.jobs?.find(c => c.id === convId) || data?.directs?.find(c => c.id === convId);
        const isArchived = Boolean(conv?.is_archived);
        archiveBtn.textContent = isArchived ? 'Unarchive' : 'Archive';
        archiveBtn.dataset.action = isArchived ? 'chat-unarchive' : 'chat-archive';
      }

      updateHeader(store);
    }
  });

  // Chat menu action handler
  chatMenuDropdown?.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    chatMenuDropdown.classList.add('hidden');
    await handleMenuAction(store, btn.dataset.action);
  });

  // Close dropdown on outside click
  document.addEventListener('click', e => {
    if (!chatMenuDropdown) return;
    if (!chatMenuDropdown.contains(e.target) && !chatMenuBtn?.contains(e.target)) {
      chatMenuDropdown.classList.add('hidden');
    }
  });

  updateHeader(store);
}
