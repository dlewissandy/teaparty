// Sidebar Partners section: organizations partnered with the active org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';

export function renderPartnerSection(store, container, orgId, filter) {
  const s = store.get();
  const partnerships = (s.data.partnerships || []).filter(
    p => (p.source_org_id === orgId || p.target_org_id === orgId) && p.status === 'accepted'
  );

  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  // For each partnership, show the *other* org
  const partners = partnerships.map(p => {
    const isSource = p.source_org_id === orgId;
    return {
      orgId: isSource ? p.target_org_id : p.source_org_id,
      orgName: isSource ? p.target_org_name : p.source_org_name,
      partnershipId: p.id,
    };
  });

  const filtered = filterLower
    ? partners.filter(p => p.orgName.toLowerCase().includes(filterLower))
    : partners;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No partners</span>';
    return;
  }

  container.innerHTML = filtered.map(p => {
    const color = avatarColor(p.orgName);
    const initials = initialsFromName(p.orgName);
    const isActive = selection === `partner:${p.partnershipId}`;
    return `<button
      class="sidebar-nav-item sidebar-partner-item${isActive ? ' active' : ''}"
      data-action="select-partner"
      data-partnership-id="${escapeHtml(p.partnershipId)}"
      data-partner-org-id="${escapeHtml(p.orgId)}"
      title="${escapeHtml(p.orgName)}"
    ><span class="sidebar-partner-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span><span class="sidebar-nav-label">${escapeHtml(p.orgName)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-partner"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const partnershipId = btn.dataset.partnershipId;
      const partnerOrgId = btn.dataset.partnerOrgId;
      store.update(s => { s.nav.sidebarSelection = `partner:${partnershipId}`; });
      bus.emit('nav:partner-selected', { partnershipId, partnerOrgId });
    });
  });
}
