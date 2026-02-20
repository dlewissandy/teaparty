// Notification system: SSE stream, polling, bell badge, panel, toasts.
// Ported from modules/notifications.js to use the reactive store.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { loadMyInvites } from '../data/data-loading.js';

let _store = null;
let _notifications = [];
let _unreadCount = 0;
let _pollTimer = null;
let _eventSource = null;
let _panelOpen = false;

export function initNotifications(store) {
  _store = store;

  // Bell button
  const bellBtn = document.getElementById('org-rail-bell');
  if (bellBtn) {
    bellBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePanel();
    });
  }

  // Panel close button
  const closeBtn = document.getElementById('notif-panel-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => closePanel());
  }

  // Close panel on outside click
  document.addEventListener('click', (e) => {
    const panel = document.getElementById('notification-panel');
    if (_panelOpen && panel && !panel.contains(e.target)) {
      closePanel();
    }
  });

  // React to auth changes
  bus.on('auth:signed-in', () => {
    startPolling();
    connectSSE();
  });
  bus.on('auth:signed-out', () => {
    stopPolling();
    disconnectSSE();
    _unreadCount = 0;
    _notifications = [];
    updateBadge();
  });
}

function updateBadge() {
  const badge = document.getElementById('notif-badge');
  if (!badge) return;
  const inviteCount = (_store?.get().data.invites || []).length;
  const total = _unreadCount + inviteCount;
  if (total > 0) {
    badge.textContent = total > 99 ? '99+' : String(total);
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

async function pollCounts() {
  if (!_store.get().auth.token) return;
  try {
    const result = await api('/api/notifications/counts', { retries: 0, timeout: 10000 });
    _unreadCount = result.unread || 0;
    updateBadge();
  } catch { /* skip */ }
}

export function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(pollCounts, 30000);
  pollCounts();
}

export function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

export function connectSSE() {
  disconnectSSE();
  const token = _store.get().auth.token;
  if (!token) return;
  const url = `/api/notifications/stream?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  _eventSource = es;

  es.onmessage = (evt) => {
    try {
      const event = JSON.parse(evt.data);
      if (event.type === 'notification') {
        _unreadCount += 1;
        updateBadge();
        showToast(event);
      } else if (event.type === 'member_removed') {
        flash('You have been removed from a workgroup', 'info');
        bus.emit('data:refresh');
      }
    } catch { /* ignore */ }
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) disconnectSSE();
  };
}

export function disconnectSSE() {
  if (_eventSource) { _eventSource.close(); _eventSource = null; }
}

function showToast(event) {
  const summary = event.summary || event.message || 'New notification';
  flash(summary, 'info');
}

async function togglePanel() {
  if (_panelOpen) { closePanel(); return; }
  openPanel();
}

async function openPanel() {
  _panelOpen = true;
  const panel = document.getElementById('notification-panel');
  if (panel) panel.classList.remove('hidden');

  // Load notifications and invites in parallel
  try {
    const [data] = await Promise.all([
      api('/api/notifications?limit=50'),
      loadMyInvites(),
    ]);
    _notifications = data || [];
    renderPanel();
  } catch {
    _notifications = [];
    renderPanel();
  }
}

function closePanel() {
  _panelOpen = false;
  const panel = document.getElementById('notification-panel');
  if (panel) panel.classList.add('hidden');
}

function renderPanel() {
  const list = document.getElementById('notification-list');
  if (!list) return;

  const invites = _store.get().data.invites || [];
  let html = '';

  // Pending invites section
  if (invites.length) {
    html += `<div class="notif-section-label">Pending Invites</div>`;
    html += invites.map(inv => `
      <div class="notif-invite-item" data-wg-id="${escapeHtml(inv.workgroup_id)}" data-token="${escapeHtml(inv.token)}">
        <div class="notif-invite-body">
          <div class="notif-invite-message"><strong>${escapeHtml(inv.invited_by_name || 'Someone')}</strong> invited you to <strong>${escapeHtml(inv.workgroup_name || 'a workgroup')}</strong></div>
          <div class="notification-time">${formatRelativeTime(inv.created_at)}</div>
        </div>
        <div class="notif-invite-actions">
          <button class="notif-invite-accept" data-action="accept">Accept</button>
          <button class="notif-invite-decline" data-action="decline">Decline</button>
        </div>
      </div>
    `).join('');
  }

  // Regular notifications
  if (_notifications.length) {
    if (invites.length) html += `<div class="notif-section-label">Notifications</div>`;
    html += _notifications.map(n => {
      const unread = !n.is_read ? 'unread' : '';
      const time = formatRelativeTime(n.created_at);
      return `
        <div class="notification-item ${unread}" data-notif-id="${escapeHtml(n.id)}"
             ${n.source_conversation_id ? `data-conversation="${escapeHtml(n.source_conversation_id)}"` : ''}>
          <div class="notification-body">
            <div class="notification-message">${escapeHtml(n.message || n.summary || '')}</div>
            <div class="notification-time">${escapeHtml(time)}</div>
          </div>
          ${!n.is_read ? '<span class="notification-dot"></span>' : ''}
        </div>
      `;
    }).join('');
  }

  if (!html) {
    list.innerHTML = '<p class="meta notification-empty">No notifications yet.</p>';
    return;
  }

  list.innerHTML = html;

  // Wire invite accept/decline buttons
  list.querySelectorAll('.notif-invite-item').forEach(item => {
    const wgId = item.dataset.wgId;
    const token = item.dataset.token;
    item.querySelector('[data-action="accept"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        await api(`/api/workgroups/${wgId}/invites/${token}/accept`, { method: 'POST' });
        flash('Invite accepted!', 'success');
        await loadMyInvites();
        renderPanel();
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to accept invite', 'error');
      }
    });
    item.querySelector('[data-action="decline"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        await api(`/api/workgroups/${wgId}/invites/${token}/decline`, { method: 'POST' });
        flash('Invite declined', 'info');
        await loadMyInvites();
        renderPanel();
      } catch (err) {
        flash(err.message || 'Failed to decline invite', 'error');
      }
    });
  });

  // Click to mark read + navigate (regular notifications)
  list.querySelectorAll('.notification-item').forEach(item => {
    item.addEventListener('click', async () => {
      const notifId = item.dataset.notifId;
      const convId = item.dataset.conversation;
      if (notifId) {
        try {
          await api(`/api/notifications/${notifId}/read`, { method: 'POST' });
          item.classList.remove('unread');
          item.querySelector('.notification-dot')?.remove();
          _unreadCount = Math.max(0, _unreadCount - 1);
          updateBadge();
        } catch { /* skip */ }
      }
      if (convId) {
        closePanel();
        bus.emit('nav:open-conversation', { conversationId: convId });
      }
    });
  });
}

function formatRelativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return Math.floor(diff / 86400000) + 'd ago';
}

export function getUnreadCount() { return _unreadCount; }
