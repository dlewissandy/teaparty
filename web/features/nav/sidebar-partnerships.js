// Sidebar Partners section: organizations partnered with the active org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';

export function renderPartnerSection(store, container, orgId, filter) {
  const s = store.get();
  const allForOrg = (s.data.partnerships || []).filter(
    p => p.source_org_id === orgId || p.target_org_id === orgId
  );
  const accepted = allForOrg.filter(p => p.status === 'accepted');
  const pending = allForOrg.filter(p => p.status === 'proposed');

  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  function toPartner(p) {
    const isSource = p.source_org_id === orgId;
    return {
      orgId: isSource ? p.target_org_id : p.source_org_id,
      orgName: isSource ? (p.target_org_name || '?') : (p.source_org_name || '?'),
      partnershipId: p.id,
    };
  }

  const partners = accepted.map(toPartner);
  const pendingPartners = pending.map(toPartner);

  const filtered = filterLower
    ? partners.filter(p => p.orgName.toLowerCase().includes(filterLower))
    : partners;
  const filteredPending = filterLower
    ? pendingPartners.filter(p => p.orgName.toLowerCase().includes(filterLower))
    : pendingPartners;

  if (!filtered.length && !filteredPending.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No partners</span>';
    return;
  }

  let html = filtered.map(p => {
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

  if (filteredPending.length) {
    html += `<div class="sidebar-pending-label">Pending</div>`;
    html += filteredPending.map(p => {
      const color = avatarColor(p.orgName);
      const initials = initialsFromName(p.orgName);
      const isActive = selection === `partner:${p.partnershipId}`;
      return `<button
        class="sidebar-nav-item sidebar-partner-item sidebar-pending-item${isActive ? ' active' : ''}"
        data-action="select-partner"
        data-partnership-id="${escapeHtml(p.partnershipId)}"
        data-partner-org-id="${escapeHtml(p.orgId)}"
        title="${escapeHtml(p.orgName)} (pending)"
      ><span class="sidebar-partner-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span><span class="sidebar-nav-label">${escapeHtml(p.orgName)}</span><span class="sidebar-pending-badge">Pending</span></button>`;
    }).join('');
  }

  container.innerHTML = html;

  container.querySelectorAll('[data-action="select-partner"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const partnershipId = btn.dataset.partnershipId;
      const partnerOrgId = btn.dataset.partnerOrgId;
      store.update(s => { s.nav.sidebarSelection = `partner:${partnershipId}`; });
      bus.emit('nav:partner-selected', { partnershipId, partnerOrgId });
    });
  });
}
