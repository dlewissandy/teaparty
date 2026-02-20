// Engagement lifecycle UI.
// Ported from modules/engagements.js and engagement-view.js.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

export function initEngagements(store) {
  _store = store;
}

// Engagement lifecycle actions
export async function engagementRespond(engagementId, accept) {
  try {
    const action = accept ? 'accept' : 'decline';
    await api(`/api/engagements/${engagementId}/${action}`, { method: 'POST' });
    flash(`Engagement ${action}ed`, 'success');
    bus.emit('data:refresh');
  } catch (e) {
    flash(e.message || 'Failed to respond to engagement', 'error');
  }
}

export async function engagementComplete(engagementId) {
  try {
    await api(`/api/engagements/${engagementId}/complete`, { method: 'POST' });
    flash('Engagement completed', 'success');
    bus.emit('data:refresh');
  } catch (e) {
    flash(e.message || 'Failed to complete engagement', 'error');
  }
}

export async function engagementReview(engagementId, rating, feedback) {
  try {
    await api(`/api/engagements/${engagementId}/review`, {
      method: 'POST',
      body: { rating, feedback },
    });
    flash('Review submitted', 'success');
    bus.emit('data:refresh');
  } catch (e) {
    flash(e.message || 'Failed to submit review', 'error');
  }
}

export async function engagementCancel(engagementId) {
  try {
    await api(`/api/engagements/${engagementId}/cancel`, { method: 'POST' });
    flash('Engagement cancelled', 'success');
    bus.emit('data:refresh');
  } catch (e) {
    flash(e.message || 'Failed to cancel engagement', 'error');
  }
}

export async function loadEngagementJobs(engagementId) {
  try {
    return await api(`/api/engagements/${engagementId}/jobs`);
  } catch { return []; }
}

export function openEngagementCreationForm(workgroupId) {
  bus.emit('settings:open', {
    title: 'Create Engagement',
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Title</span>
        <input name="title" type="text" placeholder="Engagement title" required />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="3" placeholder="What do you need?"></textarea>
      </label>
      <label class="settings-field">
        <span class="settings-label">Target Workgroup ID</span>
        <input name="target_workgroup_id" type="text" placeholder="Workgroup to engage" required />
      </label>
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-action="settings-cancel">Cancel</button>
        <button type="submit" class="btn-primary">Create</button>
      </div>
    `,
    onSubmit: async (formData) => {
      await api(`/api/workgroups/${workgroupId}/engagements`, {
        method: 'POST',
        body: {
          title: formData.get('title'),
          description: formData.get('description'),
          target_workgroup_id: formData.get('target_workgroup_id'),
        },
      });
      flash('Engagement created', 'success');
      bus.emit('data:refresh');
    },
  });
}

// Render engagement status badge
export function engagementStatusBadge(status) {
  const classes = {
    proposed: 'badge-info',
    negotiating: 'badge-warning',
    accepted: 'badge-info',
    in_progress: 'badge-active',
    completed: 'badge-success',
    reviewed: 'badge-success',
    cancelled: 'badge-muted',
    declined: 'badge-muted',
  };
  const cls = classes[status] || 'badge-muted';
  return `<span class="status-badge ${cls}">${escapeHtml(status)}</span>`;
}
