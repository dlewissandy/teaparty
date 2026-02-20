// Partnership management.
// Ported from modules/partnerships.js.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

export function initPartnerships(store) {
  _store = store;
}

export async function partnershipAccept(partnershipId) {
  try {
    await api(`/api/partnerships/${partnershipId}/accept`, { method: 'POST' });
    flash('Partnership accepted', 'success');
    bus.emit('data:refresh');
  } catch (e) { flash(e.message || 'Failed', 'error'); }
}

export async function partnershipDecline(partnershipId) {
  try {
    await api(`/api/partnerships/${partnershipId}/decline`, { method: 'POST' });
    flash('Partnership declined', 'success');
    bus.emit('data:refresh');
  } catch (e) { flash(e.message || 'Failed', 'error'); }
}

export async function partnershipRevoke(partnershipId) {
  try {
    await api(`/api/partnerships/${partnershipId}/revoke`, { method: 'POST' });
    flash('Partnership revoked', 'success');
    bus.emit('data:refresh');
  } catch (e) { flash(e.message || 'Failed', 'error'); }
}

export async function partnershipWithdraw(partnershipId) {
  try {
    await api(`/api/partnerships/${partnershipId}/withdraw`, { method: 'POST' });
    flash('Partnership withdrawn', 'success');
    bus.emit('data:refresh');
  } catch (e) { flash(e.message || 'Failed', 'error'); }
}

export function openProposePartnershipForm(orgId) {
  bus.emit('settings:open', {
    title: 'Propose Partnership',
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Target Organization ID</span>
        <input name="target_org_id" type="text" placeholder="Organization to partner with" required />
      </label>
      <label class="settings-field">
        <span class="settings-label">Message</span>
        <textarea name="message" rows="3" placeholder="Why do you want to partner?"></textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-action="settings-cancel">Cancel</button>
        <button type="submit" class="btn-primary">Propose</button>
      </div>
    `,
    onSubmit: async (formData) => {
      await api(`/api/organizations/${orgId}/partnerships`, {
        method: 'POST',
        body: {
          target_organization_id: formData.get('target_org_id'),
          message: formData.get('message'),
        },
      });
      flash('Partnership proposed', 'success');
      bus.emit('data:refresh');
    },
  });
}

export function partnershipStatusBadge(status) {
  const classes = {
    proposed: 'badge-info',
    accepted: 'badge-success',
    active: 'badge-active',
    revoked: 'badge-muted',
    declined: 'badge-muted',
  };
  const cls = classes[status] || 'badge-muted';
  return `<span class="status-badge ${cls}">${escapeHtml(status)}</span>`;
}
