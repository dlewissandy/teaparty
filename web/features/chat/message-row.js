// Creates and updates a single message row DOM element.

import { escapeHtml, parseFileContext, linkifyUrls, highlightMentions, parseAsUTC } from '../../core/utils.js';
import { generateBotSvg, generateHumanSvg } from '../../components/shared/avatar.js';
import { agentName, memberName, senderLabel } from '../../components/shared/identity.js';

/** Resolve avatar HTML for a message sender. */
function resolveAvatarHtml(store, message) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const wgData = s.data.treeData[wgId];

  if (message.sender_type === 'agent' && message.sender_agent_id && wgData) {
    const agent = wgData.agents?.find(a => a.id === message.sender_agent_id);
    if (agent?.icon) {
      return `<div class="message-avatar avatar avatar-agent"><img src="${escapeHtml(agent.icon)}" alt="" /></div>`;
    }
    const name = agent?.name || agentName(wgId, message.sender_agent_id);
    return `<div class="message-avatar avatar avatar-agent">${generateBotSvg(name)}</div>`;
  }

  if (message.sender_type === 'user' && message.sender_user_id && wgData) {
    const member = wgData.members?.find(m => m.user_id === message.sender_user_id);
    if (member?.picture) {
      return `<div class="message-avatar avatar avatar-human"><img src="${escapeHtml(member.picture)}" alt="" /></div>`;
    }
    const name = member?.name || member?.email || memberName(wgId, message.sender_user_id);
    return `<div class="message-avatar avatar avatar-human">${generateHumanSvg(name)}</div>`;
  }

  if (message.sender_type === 'system') {
    return `<div class="message-avatar avatar avatar-system"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#8da3a6"/><text x="16" y="16" text-anchor="middle" dominant-baseline="central" fill="#fff" font-family="sans-serif" font-weight="700" font-size="10">SYS</text></svg></div>`;
  }

  // Fallback
  const label = senderLabel(wgId, message);
  if (message.sender_type === 'agent') {
    return `<div class="message-avatar avatar avatar-agent">${generateBotSvg(label)}</div>`;
  }
  return `<div class="message-avatar avatar avatar-human">${generateHumanSvg(label)}</div>`;
}

/** Resolve sender display name with appropriate class. */
function resolveSenderHtml(store, message) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const label = senderLabel(wgId, message);

  if (message.sender_type === 'agent') {
    return `<span class="message-sender agent-name">${escapeHtml(label)}</span>`;
  }
  if (message.sender_type === 'system') {
    return `<span class="message-sender system-name">${escapeHtml(label)}</span>`;
  }
  return `<span class="message-sender human-name">${escapeHtml(label)}</span>`;
}

/** Format timestamp to short local time string. */
function formatTime(isoString) {
  const date = parseAsUTC(isoString);
  if (isNaN(date.getTime())) return '';
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/** Render markdown to sanitized HTML, with @mention highlighting. */
function renderMarkdown(text) {
  if (typeof window.marked !== 'undefined' && typeof window.DOMPurify !== 'undefined') {
    const raw = window.marked.parse(text);
    const clean = window.DOMPurify.sanitize(raw, {
      ADD_TAGS: ['iframe'],
      ADD_ATTR: ['target', 'rel', 'class'],
    });
    return highlightMentions(clean);
  }
  // Fallback when CDN libs aren't loaded
  return highlightMentions(linkifyUrls(escapeHtml(text)));
}

/** Build message content HTML with file context and markdown rendering. */
function buildContentHtml(content) {
  const fc = parseFileContext(content);
  if (fc) {
    const fileToggle = `<div class="message-file-context" onclick="this.classList.toggle('expanded')"><span class="message-file-context-toggle">\u{1F4CE} ${escapeHtml(fc.path)}</span><pre class="message-file-context-content">${escapeHtml(fc.fileContent)}</pre></div>`;
    return fileToggle + renderMarkdown(fc.message);
  }
  return renderMarkdown(content);
}

/** Determine CSS row classes for a message. */
function rowClasses(message, isGrouped) {
  let cls = 'message-row';
  if (message.sender_type === 'system') {
    cls += ' system';
    if (message.content.startsWith('[Tool]')) cls += ' team-tool-use';
    else if (message.content.startsWith('[System]') || message.content.startsWith('[Job')) cls += ' team-system';
  } else if (message.sender_type === 'agent') {
    cls += ' agent';
  } else {
    cls += ' user';
  }
  if (isGrouped) cls += ' message-grouped';
  return cls;
}

/**
 * Create a message article element from scratch.
 * @param {object} store
 * @param {object} message
 * @param {boolean} isGrouped - collapse header (avatar + name) for consecutive same-sender messages
 * @param {boolean} isNew - add entry animation class
 * @returns {HTMLElement}
 */
export function createMessageElement(store, message, isGrouped = false, isNew = false) {
  const article = document.createElement('article');
  article.dataset.msgId = message.id;

  const classes = rowClasses(message, isGrouped);
  if (isNew) article.classList.add('message-new');
  article.className = (isNew ? classes + ' message-new' : classes);

  const avatarHtml = resolveAvatarHtml(store, message);
  const senderHtml = resolveSenderHtml(store, message);
  const timeStr = formatTime(message.created_at);
  const contentHtml = buildContentHtml(message.content);

  article.innerHTML = `
    ${avatarHtml}
    <div class="message-body">
      <div class="message-meta">
        ${senderHtml}
        <time class="message-timestamp" datetime="${escapeHtml(message.created_at || '')}">${escapeHtml(timeStr)}</time>
      </div>
      <div class="message-text">${contentHtml}</div>
    </div>
  `;

  return article;
}

/**
 * Update an existing message element in-place.
 * @param {object} store
 * @param {HTMLElement} el
 * @param {object} message
 * @param {boolean} isGrouped
 */
export function updateMessageElement(store, el, message, isGrouped = false) {
  // Update classes (grouped state may change)
  const classes = rowClasses(message, isGrouped);
  // Preserve animation class if present
  const isNew = el.classList.contains('message-new');
  el.className = isNew ? classes + ' message-new' : classes;

  // Update avatar
  const avatarSlot = el.querySelector('.message-avatar');
  if (avatarSlot) {
    const newAvatarHtml = resolveAvatarHtml(store, message);
    const temp = document.createElement('div');
    temp.innerHTML = newAvatarHtml;
    const newAvatar = temp.firstElementChild;
    if (newAvatar) el.replaceChild(newAvatar, avatarSlot);
  }

  // Update sender name
  const senderEl = el.querySelector('.message-sender');
  if (senderEl) {
    const s = store.get();
    const wgId = s.nav.activeWorkgroupId;
    const label = senderLabel(wgId, message);
    senderEl.textContent = label;
  }

  // Update time
  const timeEl = el.querySelector('.message-timestamp');
  if (timeEl) {
    timeEl.textContent = formatTime(message.created_at);
    timeEl.setAttribute('datetime', message.created_at || '');
  }

  // Update content
  const textEl = el.querySelector('.message-text');
  if (textEl) {
    textEl.innerHTML = buildContentHtml(message.content);
  }
}
