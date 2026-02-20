// Badge and status indicator helpers.
// All render* functions return HTML strings (for innerHTML injection).
// updateBellBadge() operates on the live DOM.

import { escapeHtml } from '../../core/utils.js';

// ---- Status dots ----

/**
 * A small coloured dot indicating workgroup/org activity state.
 * @param {'active'|'idle'|'offline'|string} status
 * @param {string} [title]
 * @returns {string} HTML
 */
export function renderStatusDot(status, title = '') {
  const t = title ? ` title="${escapeHtml(title)}"` : '';
  return `<span class="status-dot ${escapeHtml(status)}"${t}></span>`;
}

/**
 * A small dot indicating an unread conversation.
 * @returns {string} HTML
 */
export function renderUnreadDot() {
  return `<span class="unread-dot"></span>`;
}

// ---- Count badges ----

/**
 * Numeric badge used on org/workgroup rows (jobs, attention, workgroup count).
 * @param {number} count
 * @param {'attention'|'secondary'|''} [variant]
 * @returns {string} HTML, or empty string when count is 0
 */
export function renderOrgBadge(count, variant = '') {
  if (!count) return '';
  const cls = variant ? `org-badge ${variant}` : 'org-badge';
  return `<span class="${cls}">${count}</span>`;
}

/**
 * Workgroup job-count badge in the nav tree.
 * @param {number} jobCount
 * @returns {string} HTML, or empty string when count is 0
 */
export function renderWgJobCountBadge(jobCount) {
  if (!jobCount) return '';
  return `<span class="wg-job-count-badge">${jobCount} job${jobCount !== 1 ? 's' : ''}</span>`;
}

/**
 * Unread-count badge on a nav group row (org, agent, workgroup).
 * @param {number} count
 * @returns {string} HTML, or empty string when count is 0
 */
export function renderGroupUnreadBadge(count) {
  if (!count) return '';
  return `<span class="org-group-count">${count}</span>`;
}

/**
 * Per-org notification badge (unread cross-org notifications).
 * @param {number} count
 * @returns {string} HTML, or empty string when count is 0
 */
export function renderNotificationBadge(count) {
  if (!count) return '';
  const label = `${count} unread notification${count !== 1 ? 's' : ''}`;
  return `<span class="notification-badge org-notif-badge" title="${escapeHtml(label)}">${count}</span>`;
}

// ---- Status / task badges ----

/**
 * Status pill used on tasks, jobs, engagements, and invite rows.
 * @param {string} status - e.g. 'open', 'in_progress', 'done', 'requested'
 * @param {string} [label] - display text; defaults to status
 * @returns {string} HTML
 */
export function renderTaskBadge(status, label) {
  const text = label !== undefined ? label : status;
  return `<span class="task-badge ${escapeHtml(status)}">${escapeHtml(text)}</span>`;
}

/**
 * Engagement link badge shown inline on job rows.
 * @param {string} label
 * @returns {string} HTML
 */
export function renderEngagementBadge(label) {
  return `<span class="engagement-badge" title="${escapeHtml(label)}">[eng: ${escapeHtml(label)}]</span>`;
}

/**
 * Lead-agent star badge.
 * @returns {string} HTML
 */
export function renderLeadBadge() {
  return `<span class="agent-lead-badge" title="Lead agent">&#x2605;</span>`;
}

/**
 * "[synced]" label prepended to system messages.
 * @returns {string} HTML
 */
export function renderSyncedBadge() {
  return `<span class="synced-badge">[synced]</span>`;
}

// ---- Bell badge (live DOM) ----

/**
 * Update the notification bell badge in the header.
 * Pulses when the count increases.
 * @param {number} count - total unread notification count
 */
export function updateBellBadge(count) {
  const badge = document.getElementById('notif-bell-badge');
  if (!badge) return;

  if (count > 0) {
    const prev = badge.classList.contains('hidden') ? 0 : (parseInt(badge.textContent, 10) || 0);
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.classList.remove('hidden');
    if (count > prev) {
      badge.classList.remove('pulse');
      void badge.offsetWidth; // reflow to restart CSS animation
      badge.classList.add('pulse');
    }
  } else {
    badge.classList.add('hidden');
  }

  _updateBellAriaLabel(count);
}

function _updateBellAriaLabel(count) {
  const label = count === 1 ? '1 unread notification' : `${count} unread notifications`;
  const bellBtn = document.getElementById('notif-bell-btn');
  if (bellBtn) bellBtn.setAttribute('aria-label', `Notifications (${label})`);
  const bottomNotif = document.getElementById('bottom-nav-notif');
  if (bottomNotif) bottomNotif.setAttribute('aria-label', `Notifications (${label})`);
}
