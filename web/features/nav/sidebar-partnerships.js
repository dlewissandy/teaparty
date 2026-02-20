// Sidebar Partners section: organizations that the active org has added as partners.
// Asymmetric: only shows partnerships where this org is the source.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';
import { loadPartnerships } from '../data/data-loading.js';

const removeSvg = `<svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

export function renderPartnerSection(store, container, orgId, filter) {
  const s = store.get();
  const currentUserId = s.auth.user?.id;
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  const isOwner = org?.owner_id === currentUserId;

  // Asymmetric: only show partnerships where this org is the source
  const partners = (s.data.partnerships || [])
    .filter(p => p.source_org_id === orgId && p.status === 'accepted')
    .map(p => ({
      orgId: p.target_org_id,
      orgName: p.target_org_name || '?',
      partnershipId: p.id,
    }));

  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const filtered = filterLower
    ? partners.filter(p => p.orgName.toLowerCase().includes(filterLower))
    : partners;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No partners</span>';
    return;
  }

  const html = filtered.map(p => {
    const color = avatarColor(p.orgName);
    const initials = initialsFromName(p.orgName);
    const isActive = selection === `partner:${p.partnershipId}`;

    const removeBtn = isOwner
      ? `<button class="sidebar-member-remove" data-action="revoke-partner" data-partnership-id="${escapeHtml(p.partnershipId)}" data-org-name="${escapeHtml(p.orgName)}" title="Remove partner" aria-label="Remove ${escapeHtml(p.orgName)}">${removeSvg}</button>`
      : '';

    return `<div class="sidebar-nav-item sidebar-partner-item${isActive ? ' active' : ''}">
      <button class="sidebar-partner-select" data-action="select-partner" data-partnership-id="${escapeHtml(p.partnershipId)}" data-partner-org-id="${escapeHtml(p.orgId)}" title="${escapeHtml(p.orgName)}">
        <span class="sidebar-partner-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
        <span class="sidebar-nav-label">${escapeHtml(p.orgName)}</span>
      </button>
      ${removeBtn}
    </div>`;
  }).join('');

  container.innerHTML = html;

  container.querySelectorAll('[data-action="select-partner"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const partnershipId = btn.dataset.partnershipId;
      const partnerOrgId = btn.dataset.partnerOrgId;
      store.update(s => { s.nav.sidebarSelection = `partner:${partnershipId}`; });
      bus.emit('nav:partner-selected', { partnershipId, partnerOrgId });
    });
  });

  container.querySelectorAll('[data-action="revoke-partner"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const partnershipId = btn.dataset.partnershipId;
      const name = btn.dataset.orgName;
      if (!confirm(`Remove partnership with ${name}?`)) return;
      try {
        await api(`/api/partnerships/${partnershipId}/revoke`, { method: 'POST' });
        flash(`Partnership with ${name} removed`, 'success');
        loadPartnerships(orgId);
      } catch (err) {
        flash(err.message || 'Failed to remove partnership', 'error');
      }
    });
  });
}
