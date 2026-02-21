// Data loading and polling.
// Centralized data fetching that populates the store.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { connectSSE, disconnectSSE } from '../../core/sse.js';
import { normalizeWorkgroupFiles, parseAsUTC } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { senderLabel } from '../../components/shared/identity.js';
import { isShowAgentThoughts, savePreferences } from '../auth/auth.js';

let _store = null;
let _pollTimer = null;
let _pollErrors = 0;
let _usagePollCounter = 0;
let _invitePollCounter = 0;
let _notifPollCounter = 0;
let _treePollCounter = 0;

const _pendingRefreshes = new Map();
function _debouncedTreeRefresh(workgroupId, delayMs = 500) {
    if (_pendingRefreshes.has(workgroupId)) clearTimeout(_pendingRefreshes.get(workgroupId));
    _pendingRefreshes.set(workgroupId, setTimeout(async () => {
        _pendingRefreshes.delete(workgroupId);
        const wg = _store.get().data.treeData[workgroupId]?.workgroup;
        if (wg) { await refreshWorkgroupTree(wg); _store.notify('data.treeData'); }
    }, delayMs));
}

const POLL_INTERVAL = 4000;
const POLL_MAX = 60000;

export function initDataLoading(store) {
  _store = store;

  // Refresh data on bus events
  bus.on('data:refresh', () => {
    loadWorkgroups();
    const orgId = _store.get().nav?.activeOrgId;
    if (orgId) loadProjects(orgId);
  });
  bus.on('auth:signed-in', () => loadWorkgroups());
  bus.on('auth:signed-out', () => stopPolling());

  // Cross-member sync events
  bus.on('sync:tree-changed', ({ workgroupId }) => _debouncedTreeRefresh(workgroupId));
  bus.on('sync:agents-changed', ({ workgroupId }) => _debouncedTreeRefresh(workgroupId));
  bus.on('sync:workgroup-updated', ({ workgroupId }) => _debouncedTreeRefresh(workgroupId));
  bus.on('sync:members-changed', ({ workgroupId }) => _debouncedTreeRefresh(workgroupId));
  bus.on('sync:engagement-changed', () => {
    // Refresh all workgroups since engagement spans two
    const wgs = _store.get().data.workgroups || [];
    wgs.forEach(wg => _debouncedTreeRefresh(wg.id));
  });
  bus.on('sync:org-updated', () => loadOrganizations());
  bus.on('sync:project_created', ({ orgId }) => { if (orgId) loadProjects(orgId); });
  bus.on('sync:partnerships-changed', ({ orgId }) => {
    const activeOrg = (_store.get().data.organizations || []).find(o => o.id === orgId);
    if (activeOrg) loadPartnerships(orgId);
  });
  bus.on('sync:message-posted', ({ conversationId, workgroupId }) => {
    // If not the active conversation, refresh tree for unread indicators
    if (conversationId !== _store.get().nav.activeConversationId) {
      _debouncedTreeRefresh(workgroupId);
    }
  });

  // Visibility and network handlers
  document.addEventListener('visibilitychange', () => {
    if (!_store.get().auth.token) return;
    if (document.hidden) {
      stopPolling();
      disconnectSSE();
    } else {
      startPolling();
      const convId = _store.get().nav.activeConversationId;
      if (convId) connectSSE(convId);
    }
  });

  window.addEventListener('offline', () => {
    stopPolling();
    disconnectSSE();
  });

  window.addEventListener('online', () => {
    if (_store.get().auth.token) {
      startPolling();
      const convId = _store.get().nav.activeConversationId;
      if (convId) connectSSE(convId);
    }
  });
}

// ─── Organizations ────────────────────────────────────────────────────────────

export async function loadOrganizations() {
  try {
    const orgs = await api('/api/organizations');
    _store.update(s => { s.data.organizations = orgs; });
    _store.notify('data.organizations');
  } catch {
    _store.update(s => { s.data.organizations = []; });
  }
}

export async function createOrganization(name, description = '') {
  const org = await api('/api/organizations', { method: 'POST', body: { name, description } });
  _store.update(s => { s.data.organizations = [...s.data.organizations, org]; });
  _store.notify('data.organizations');
  return org;
}

// ─── Partnerships ────────────────────────────────────────────────────────────

export async function loadPartnerships(orgId) {
  try {
    const partnerships = await api(`/api/organizations/${orgId}/partnerships`);
    _store.update(s => { s.data.partnerships = partnerships; });
    _store.notify('data.partnerships');
  } catch {
    _store.update(s => { s.data.partnerships = []; });
  }
}

// ─── Projects ─────────────────────────────────────────────────────────────────

export async function loadProjects(orgId) {
  try {
    const projects = await api(`/api/organizations/${orgId}/projects`);
    _store.update(s => { s.data.projects = projects; });
    _store.notify('data.projects');
  } catch {
    _store.update(s => { s.data.projects = []; });
  }
}

// ─── Workgroups ───────────────────────────────────────────────────────────────

export async function loadWorkgroups() {
  const s = _store.get();
  if (!s.auth.token) return;

  const workgroups = await api('/api/workgroups');
  _store.update(s => { s.data.workgroups = workgroups; });

  await Promise.all([loadOrganizations(), loadHomeSummary()]);

  _store.update(s => { s.data.treeData = {}; });
  await Promise.all(workgroups.map(wg => refreshWorkgroupTree(wg)));
  _store.notify('data.treeData');
  _store.notify('data.workgroups');
}

export async function refreshWorkgroupTree(workgroup) {
  const s = _store.get();
  const isOwner = workgroup.owner_id === s.auth.user?.id;

  const [conversations, members, agents, engagements, invites, jobs, agentTasks] = await Promise.all([
    api(`/api/workgroups/${workgroup.id}/conversations?include_archived=true`),
    api(`/api/workgroups/${workgroup.id}/members`),
    api(`/api/workgroups/${workgroup.id}/agents${isOwner ? '?include_hidden=true' : ''}`),
    api(`/api/workgroups/${workgroup.id}/engagements`).catch(() => []),
    isOwner ? api(`/api/workgroups/${workgroup.id}/invites`).catch(() => []) : Promise.resolve([]),
    api(`/api/workgroups/${workgroup.id}/jobs`).catch(() => []),
    api(`/api/workgroups/${workgroup.id}/agent-tasks`).catch(() => []),
  ]);

  const pendingInvites = (invites || []).filter(inv => inv.status === 'pending');

  const engagementConvIds = new Set(
    (engagements || []).flatMap(e =>
      [e.source_conversation_id, e.target_conversation_id].filter(Boolean)
    )
  );
  const taskConvIds = new Set(
    (agentTasks || []).map(t => t.conversation_id).filter(Boolean)
  );

  const treeEntry = {
    workgroup,
    jobs: conversations.filter(c =>
      (c.kind === 'job' || (c.kind === 'admin' && isOwner))
      && !engagementConvIds.has(c.id) && !taskConvIds.has(c.id)
    ),
    directs: conversations.filter(c => c.kind === 'direct' && !taskConvIds.has(c.id)),
    members,
    agents,
    engagements: engagements || [],
    engagementConversations: conversations.filter(c =>
      c.kind === 'engagement' || engagementConvIds.has(c.id)
    ),
    invites: pendingInvites,
    jobRecords: jobs || [],
    agentTasks: agentTasks || [],
    taskConversations: conversations.filter(c => taskConvIds.has(c.id)),
  };

  _store.update(s => { s.data.treeData[workgroup.id] = treeEntry; });
}

// ─── Home Summary ─────────────────────────────────────────────────────────────

export async function loadHomeSummary() {
  try {
    const summary = await api('/api/home/summary');
    _store.update(s => { s.data.homeSummary = summary; });
  } catch {
    _store.update(s => { s.data.homeSummary = null; });
  }
}

// ─── Templates ────────────────────────────────────────────────────────────────

export async function loadWorkgroupTemplates() {
  try {
    const templates = await api('/api/workgroup-templates');
    _store.update(s => { s.data.templates = templates; });
  } catch {
    _store.update(s => { s.data.templates = []; });
  }
}

// ─── Invites ──────────────────────────────────────────────────────────────────

export async function loadMyInvites() {
  try {
    const invites = await api('/api/org-invites/mine');
    _store.update(s => { s.data.invites = invites; });
  } catch {
    _store.update(s => { s.data.invites = []; });
  }
}

// ─── Messages ─────────────────────────────────────────────────────────────────

export async function loadMessages() {
  const s = _store.get();
  if (!s.nav.activeConversationId) {
    _store.update(s => { s.conversation.messages = []; });
    _store.notify('conversation.messages');
    return [];
  }

  const messages = await api(`/api/conversations/${s.nav.activeConversationId}/messages`);

  if (isShowAgentThoughts()) {
    const agentMsgIds = messages.filter(m => m.sender_type === 'agent').map(m => m.id);
    if (agentMsgIds.length) {
      try {
        const idsParam = `?message_ids=${agentMsgIds.join(',')}`;
        const thoughts = await api(`/api/conversations/${s.nav.activeConversationId}/thoughts${idsParam}`, { retries: 0, timeout: 8000 });
        _store.update(s => { Object.assign(s.conversation.thoughtsByMessageId, thoughts); });
      } catch { /* skip */ }
    }
  }

  _store.update(s => { s.conversation.messages = messages; });
  _store.notify('conversation.messages');
  return messages;
}

export async function loadConversationUsage(conversationId) {
  if (!conversationId) {
    _store.update(s => { s.conversation.usage = null; });
    return;
  }
  try {
    const data = await api(`/api/conversations/${conversationId}/usage`);
    _store.update(s => { s.conversation.usage = data; });
    _store.notify('conversation.usage');
  } catch {
    _store.update(s => { s.conversation.usage = null; });
  }
}

export async function loadTeamRoster(conversationId) {
  try {
    const roster = await api(`/api/conversations/${conversationId}/participants`, { retries: 0, timeout: 8000 });
    _store.update(s => { s.conversation.teamRoster = roster || []; });
    _store.notify('conversation.teamRoster');
    // Re-render messages so agent names resolve from roster
    _store.notify('conversation.messages');
  } catch {
    _store.update(s => { s.conversation.teamRoster = []; });
  }
}

// ─── Conversation Selection ───────────────────────────────────────────────────

export async function selectConversation(workgroupId, conversationId) {
  _store.update(s => {
    s.nav.activeWorkgroupId = workgroupId;
    s.nav.activeConversationId = conversationId;
  });
  _store.notify('nav.activeConversationId');
  _store.notify('nav.activeWorkgroupId');

  // Mark as read
  const prefs = _store.get().auth.user?.preferences || {};
  const lastRead = { ...(prefs.conversationLastRead || {}), [conversationId]: new Date().toISOString() };
  savePreferences({ conversationLastRead: lastRead });

  // Show chat view
  const chatView = document.getElementById('chat-view');
  const homeView = document.getElementById('home-view');
  const profileView = document.getElementById('agent-profile-view');
  const directoryView = document.getElementById('directory-view');
  if (chatView) chatView.classList.remove('hidden');
  if (homeView) homeView.classList.add('hidden');
  if (profileView) profileView.classList.add('hidden');
  if (directoryView) directoryView.classList.add('hidden');

  connectSSE(conversationId);
  await loadMessages();
  loadConversationUsage(conversationId);
  loadTeamRoster(conversationId);
}

export async function openAgentConversation(workgroupId, agentId) {
  const conversation = await api(`/api/workgroups/${workgroupId}/agents/${agentId}/direct-conversation`, { method: 'POST' });
  await refreshWorkgroupTree(_store.get().data.treeData[workgroupId]?.workgroup || { id: workgroupId });
  await selectConversation(workgroupId, conversation.id);
}

export async function openMemberConversation(workgroupId, memberUserId) {
  const conversation = await api(`/api/workgroups/${workgroupId}/members/${memberUserId}/direct-conversation`, { method: 'POST' });
  await refreshWorkgroupTree(_store.get().data.treeData[workgroupId]?.workgroup || { id: workgroupId });
  await selectConversation(workgroupId, conversation.id);
}

// ─── Polling ──────────────────────────────────────────────────────────────────

export function startPolling() {
  if (_pollTimer) clearTimeout(_pollTimer);
  _pollErrors = 0;

  async function pollOnce() {
    const s = _store.get();
    if (!s.auth.token) {
      _pollTimer = setTimeout(pollOnce, POLL_INTERVAL);
      return;
    }

    try {
      // Agent tick
      try { await api('/api/agents/tick', { method: 'POST', retries: 0, timeout: 10000 }); }
      catch { /* tick failure must not block polling */ }

      // Poll messages
      if (s.nav.activeConversationId) {
        const existing = s.conversation.messages.filter(m => !m.id.startsWith('local-'));
        const sinceId = existing.length ? existing[existing.length - 1].id : '';
        const url = sinceId
          ? `/api/conversations/${s.nav.activeConversationId}/messages?since_id=${encodeURIComponent(sinceId)}`
          : `/api/conversations/${s.nav.activeConversationId}/messages`;

        const newMsgs = await api(url, { retries: 0, timeout: 10000 });
        if (newMsgs.length) {
          const existingIds = new Set(s.conversation.messages.map(m => m.id));
          const optimistic = s.conversation.messages.filter(m => m.id.startsWith('local-'));
          const merged = [...existing, ...newMsgs.filter(m => !existingIds.has(m.id)), ...optimistic];
          _store.update(st => { st.conversation.messages = merged; });
          _store.notify('conversation.messages');
        }

        // Usage and workflow every ~32s
        _usagePollCounter++;
        if (_usagePollCounter >= 8) {
          _usagePollCounter = 0;
          loadConversationUsage(s.nav.activeConversationId);
        }

        // Keep lastRead current
        const latestMsg = s.conversation.messages[s.conversation.messages.length - 1];
        if (latestMsg && latestMsg.sender_user_id !== s.auth.user?.id) {
          const prefs = s.auth.user?.preferences || {};
          const curRead = prefs.conversationLastRead?.[s.nav.activeConversationId];
          const msgTime = parseAsUTC(latestMsg.created_at);
          if (!curRead || msgTime > parseAsUTC(curRead)) {
            const lastRead = { ...(prefs.conversationLastRead || {}), [s.nav.activeConversationId]: new Date().toISOString() };
            savePreferences({ conversationLastRead: lastRead });
          }
        }
      }

      // Refresh tree conversations periodically
      _treePollCounter++;
      if (_treePollCounter >= 4) {
        _treePollCounter = 0;
        const wgs = _store.get().data.workgroups;
        await Promise.all(wgs.map(async wg => {
          try {
            const convs = await api(`/api/workgroups/${wg.id}/conversations?include_archived=true`);
            const data = _store.get().data.treeData[wg.id];
            if (data) {
              const isOwner = data.workgroup?.owner_id === _store.get().auth.user?.id;
              const engagementConvIds = new Set(
                (data.engagements || []).flatMap(e => [e.source_conversation_id, e.target_conversation_id].filter(Boolean))
              );
              const taskConvIds = new Set((data.agentTasks || []).map(t => t.conversation_id).filter(Boolean));
              _store.update(s => {
                const d = s.data.treeData[wg.id];
                if (d) {
                  d.jobs = convs.filter(c => (c.kind === 'job' || (c.kind === 'admin' && isOwner)) && !engagementConvIds.has(c.id) && !taskConvIds.has(c.id));
                  d.directs = convs.filter(c => c.kind === 'direct' && !taskConvIds.has(c.id));
                  d.engagementConversations = convs.filter(c => c.kind === 'engagement' || engagementConvIds.has(c.id));
                }
              });
            }
          } catch { /* skip */ }
        }));
        _store.notify('data.treeData');
      }

      // Invites every ~32s
      _invitePollCounter++;
      if (_invitePollCounter >= 8) {
        _invitePollCounter = 0;
        await loadMyInvites();
      }

      _pollErrors = 0;
      _pollTimer = setTimeout(pollOnce, POLL_INTERVAL);
    } catch (error) {
      console.error('Poll error:', error);
      if (error?.status === 401) return;
      _pollErrors++;
      const backoff = Math.min(POLL_MAX, POLL_INTERVAL * Math.pow(2, _pollErrors));
      _pollTimer = setTimeout(pollOnce, backoff);
    }
  }

  _pollTimer = setTimeout(pollOnce, POLL_INTERVAL);
}

export function stopPolling() {
  if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
}
