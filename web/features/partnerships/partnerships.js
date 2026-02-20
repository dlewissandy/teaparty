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

export async function partnershipRevoke(partnershipId) {
  try {
    await api(`/api/partnerships/${partnershipId}/revoke`, { method: 'POST' });
    flash('Partnership revoked', 'success');
    bus.emit('data:refresh');
  } catch (e) { flash(e.message || 'Failed', 'error'); }
}

export function openAddPartnerForm(orgId) {
  bus.emit('settings:open', {
    title: 'Add Partner',
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Target Organization ID</span>
        <input name="target_org_id" type="text" placeholder="Organization to add as partner" required />
      </label>
      <label class="settings-field">
        <span class="settings-label">Message</span>
        <textarea name="message" rows="3" placeholder="Optional note"></textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-action="settings-cancel">Cancel</button>
        <button type="submit" class="btn-primary">Add Partner</button>
      </div>
    `,
    onSubmit: async (formData) => {
      await api(`/api/partnerships`, {
        method: 'POST',
        body: {
          source_org_id: orgId,
          target_org_id: formData.get('target_org_id'),
          message: formData.get('message') || '',
        },
      });
      flash('Partner added', 'success');
      bus.emit('data:refresh');
    },
  });
}

export function partnershipStatusBadge(status) {
  const classes = {
    accepted: 'badge-success',
    active: 'badge-active',
    revoked: 'badge-muted',
  };
  const cls = classes[status] || 'badge-muted';
  return `<span class="status-badge ${cls}">${escapeHtml(status)}</span>`;
}
