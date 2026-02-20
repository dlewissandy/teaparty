// Sidebar DMs section: direct message conversations for the active org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg, generateHumanSvg } from '../../components/shared/avatar.js';

export function renderDMSection(store, container, orgId, filter) {
  const s = store.get();
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const user = s.auth.user;
  const activeConvId = s.nav.activeConversationId;

  // Collect all DM conversations, dedup by conversation id
  const seen = new Set();
  const dms = [];

  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree?.directs) continue;

    for (const conv of tree.directs) {
      if (seen.has(conv.id)) continue;
      seen.add(conv.id);

      // Determine display name and avatar
      let name = conv.name || conv.topic || 'Direct message';
      let isAgent = false;
      let avatarHtml = '';

      // Try to resolve the other party
      if (conv.participant_user_id && conv.participant_user_id !== user?.id) {
        // Human DM
        const member = (tree.members || []).find(m => m.user_id === conv.participant_user_id);
        if (member) {
          name = member.name || member.email || name;
          avatarHtml = member.picture
            ? `<img src="${escapeHtml(member.picture)}" alt="" class="sidebar-dm-avatar" />`
            : generateHumanSvg(name);
        } else {
          avatarHtml = generateHumanSvg(name);
        }
      } else if (conv.participant_agent_id) {
        // Agent DM
        isAgent = true;
        const agent = (tree.agents || []).find(a => a.id === conv.participant_agent_id);
        if (agent) {
          name = agent.name || name;
          avatarHtml = agent.icon
            ? `<img src="${escapeHtml(agent.icon)}" alt="" class="sidebar-dm-avatar" />`
            : generateBotSvg(name);
        } else {
          avatarHtml = generateBotSvg(name);
        }
      } else {
        avatarHtml = generateHumanSvg(name);
      }

      const unread = isConversationUnread(conv, user);
      dms.push({ conv, name, isAgent, avatarHtml, unread, workgroupId: wg.id });
    }
  }

  const filtered = filterLower
    ? dms.filter(({ name }) => name.toLowerCase().includes(filterLower))
    : dms;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No direct messages</span>';
    return;
  }

  container.innerHTML = filtered.map(({ conv, name, avatarHtml, unread, workgroupId }) => {
    const isActive = conv.id === activeConvId;
    return `<button
      class="sidebar-nav-item sidebar-dm-item${isActive ? ' active' : ''}"
      data-action="open-dm"
      data-workgroup-id="${escapeHtml(workgroupId)}"
      data-conversation-id="${escapeHtml(conv.id)}"
      title="${escapeHtml(name)}"
    >
      <span class="sidebar-dm-avatar-wrap">${avatarHtml}</span>
      <span class="sidebar-nav-label">${escapeHtml(name)}</span>
      ${unread ? '<span class="sidebar-unread-dot" aria-hidden="true"></span>' : ''}
    </button>`;
  }).join('');

  container.querySelectorAll('[data-action="open-dm"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => {
        s.nav.activeWorkgroupId = workgroupId;
        s.nav.activeConversationId = conversationId;
      });
      bus.emit('nav:conversation-selected', { workgroupId, conversationId });
    });
  });
}

function isConversationUnread(conversation, user) {
  if (!conversation.latest_message_at) return false;
  const prefs = user?.preferences || {};
  const lastRead = prefs.conversationLastRead?.[conversation.id];
  if (!lastRead) return true;
  const latestMs = new Date(conversation.latest_message_at + (conversation.latest_message_at.match(/Z|[+-]\d{2}/) ? '' : 'Z')).getTime();
  const readMs = new Date(lastRead + (lastRead.match(/Z|[+-]\d{2}/) ? '' : 'Z')).getTime();
  return latestMs > readMs;
}
