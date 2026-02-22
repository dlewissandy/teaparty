// Organization settings: inline configuration view for org properties.
// Renders inside #org-settings-view in main-content.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';

let _store = null;
let _pendingIconDataUrl = null;  // staged icon before save

export function initOrgSettings(store) {
  _store = store;

  bus.on('nav:org-config', ({ orgId }) => {
    showOrgSettings(orgId);
  });
}

function showOrgSettings(orgId) {
  const s = _store.get();
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  if (!org) return;

  const isOwner = org.owner_id === s.auth.user?.id;
  if (!isOwner) {
    flash('Only the organization owner can edit settings', 'error');
    return;
  }

  _pendingIconDataUrl = null;
  showOrgSettingsView();
  renderSettings(org);
}

function showOrgSettingsView() {
  const views = ['chat-view', 'home-view', 'org-dashboard-view', 'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view', 'directory-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('org-settings-view')?.classList.remove('hidden');
}

function renderSettings(org) {
  const container = document.getElementById('org-settings-content');
  if (!container) return;

  const serviceDesc = org.service_description || '';
  const isDiscoverable = org.is_discoverable !== false;
  const isAccepting = org.is_accepting_engagements || false;
  const baseFee = org.engagement_base_fee ?? 0;
  const markupPct = org.engagement_markup_pct ?? 5;
  const iconUrl = org.icon_url || '';
  const color = avatarColor(org.name);
  const initials = initialsFromName(org.name);

  const avatarInner = iconUrl
    ? `<img src="${escapeHtml(iconUrl)}" alt="" class="org-cfg-avatar-img" />`
    : `<span class="org-cfg-avatar-initials" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>`;

  container.innerHTML = `
    <form id="org-settings-form" class="org-cfg">

      <!-- Hero identity -->
      <div class="org-cfg-hero">
        <button type="button" class="org-cfg-avatar" id="org-cfg-avatar-btn" title="Change icon">
          ${avatarInner}
          <span class="org-cfg-avatar-overlay">
            <svg viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M4 16l1.5-4.5L14 3l3 3-8.5 8.5L4 16z" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/><path d="M11 6l3 3" stroke="#fff" stroke-width="1.5"/></svg>
          </span>
          <input type="file" id="org-cfg-icon-input" accept="image/*" class="sr-only" />
        </button>
        <div class="org-cfg-hero-text">
          <h3 class="org-cfg-name">${escapeHtml(org.name)}</h3>
          <p class="org-cfg-meta">Organization Settings</p>
        </div>
      </div>

      <!-- Directory Presence -->
      <div class="org-cfg-card">
        <div class="org-cfg-card-header">
          <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M4 4h12a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z" stroke="currentColor" stroke-width="1.3"/><path d="M7 4v12" stroke="currentColor" stroke-width="1.3"/><path d="M10 8h4M10 11h3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          <h4 class="org-cfg-card-title">Directory Presence</h4>
        </div>

        <label class="org-cfg-field">
          <span class="org-cfg-label">Directory Blurb</span>
          <textarea name="service_description" rows="3" placeholder="Describe your organization's services...">${escapeHtml(serviceDesc)}</textarea>
        </label>

        <div class="org-cfg-toggle-row">
          <div>
            <span class="org-cfg-toggle-label">Discoverable in directory</span>
            <span class="org-cfg-toggle-hint">Others can find your organization in the directory</span>
          </div>
          <label class="org-cfg-toggle">
            <input type="checkbox" name="is_discoverable" ${isDiscoverable ? 'checked' : ''} />
            <span class="org-cfg-toggle-track"></span>
            <span class="org-cfg-toggle-thumb"></span>
          </label>
        </div>
      </div>

      <!-- Engagements -->
      <div class="org-cfg-card">
        <div class="org-cfg-card-header">
          <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M5 4h10a1 1 0 011 1v8a1 1 0 01-1 1h-3l-2 3-2-3H5a1 1 0 01-1-1V5a1 1 0 011-1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M7 8h6M7 11h3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          <h4 class="org-cfg-card-title">Engagements</h4>
        </div>

        <div class="org-cfg-toggle-row">
          <div>
            <span class="org-cfg-toggle-label">Accept engagement proposals</span>
            <span class="org-cfg-toggle-hint">Other organizations can propose engagements to your workgroups</span>
          </div>
          <label class="org-cfg-toggle">
            <input type="checkbox" name="is_accepting_engagements" ${isAccepting ? 'checked' : ''} />
            <span class="org-cfg-toggle-track"></span>
            <span class="org-cfg-toggle-thumb"></span>
          </label>
        </div>
      </div>

      <!-- Billing Model -->
      <div class="org-cfg-card">
        <div class="org-cfg-card-header">
          <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.3"/><path d="M10 5.5v9M7.5 7.5c0-1.1 1.1-2 2.5-2s2.5.9 2.5 2-1.1 2-2.5 2-2.5.9-2.5 2 1.1 2 2.5 2 2.5-.9 2.5-2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
          <h4 class="org-cfg-card-title">Billing Model</h4>
        </div>
        <p class="org-cfg-card-desc">How engagements are priced when other organizations hire your services.</p>

        <div class="org-cfg-billing-grid">
          <label class="org-cfg-field">
            <span class="org-cfg-label">Base Fee</span>
            <div class="org-cfg-input-with-unit">
              <input type="number" name="engagement_base_fee" value="${baseFee}" min="0" step="1" placeholder="0" />
              <span class="org-cfg-input-unit">credits</span>
            </div>
          </label>
          <label class="org-cfg-field">
            <span class="org-cfg-label">Token Markup</span>
            <div class="org-cfg-input-with-unit">
              <input type="number" name="engagement_markup_pct" value="${markupPct}" min="0" max="100" step="0.1" placeholder="5" />
              <span class="org-cfg-input-unit">%</span>
            </div>
          </label>
        </div>

        <div class="org-cfg-formula" id="billing-formula">
          <span class="org-cfg-formula-label">Price formula</span>
          <span class="org-cfg-formula-expr"><span id="billing-base">${baseFee}</span> + tokens &times; <span id="billing-multiplier">${(1 + markupPct / 100).toFixed(4)}</span></span>
        </div>
      </div>

      <!-- Actions -->
      <div class="org-cfg-actions">
        <button type="button" class="btn btn-ghost" id="org-settings-cancel">Cancel</button>
        <button type="submit" class="btn btn-primary" id="org-settings-save">Save Changes</button>
      </div>
    </form>
  `;

  wireFormEvents(org);
}

function wireFormEvents(org) {
  const form = document.getElementById('org-settings-form');
  if (!form) return;

  // Icon upload
  const avatarBtn = document.getElementById('org-cfg-avatar-btn');
  const fileInput = document.getElementById('org-cfg-icon-input');

  avatarBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    fileInput?.click();
  });

  fileInput?.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    if (!file) return;

    // Validate type and size (max 512KB)
    if (!file.type.startsWith('image/')) {
      flash('Please select an image file', 'error');
      return;
    }
    if (file.size > 512 * 1024) {
      flash('Image must be under 512KB', 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      _pendingIconDataUrl = reader.result;
      // Update preview
      const btn = document.getElementById('org-cfg-avatar-btn');
      if (btn) {
        const existing = btn.querySelector('.org-cfg-avatar-img, .org-cfg-avatar-initials');
        if (existing) {
          const img = document.createElement('img');
          img.src = _pendingIconDataUrl;
          img.alt = '';
          img.className = 'org-cfg-avatar-img';
          existing.replaceWith(img);
        }
      }
    };
    reader.readAsDataURL(file);
  });

  // Live billing preview
  const feeInput = form.querySelector('[name="engagement_base_fee"]');
  const markupInput = form.querySelector('[name="engagement_markup_pct"]');
  const baseSpan = document.getElementById('billing-base');
  const multSpan = document.getElementById('billing-multiplier');

  function updatePreview() {
    const fee = parseFloat(feeInput?.value) || 0;
    const pct = parseFloat(markupInput?.value) || 0;
    if (baseSpan) baseSpan.textContent = fee;
    if (multSpan) multSpan.textContent = (1 + pct / 100).toFixed(4);
  }

  feeInput?.addEventListener('input', updatePreview);
  markupInput?.addEventListener('input', updatePreview);

  // Cancel
  document.getElementById('org-settings-cancel')?.addEventListener('click', () => {
    _pendingIconDataUrl = null;
    bus.emit('nav:org-selected', { orgId: org.id });
  });

  // Submit
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const saveBtn = document.getElementById('org-settings-save');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    const formData = new FormData(form);
    const body = {
      service_description: formData.get('service_description') || '',
      is_discoverable: formData.has('is_discoverable'),
      is_accepting_engagements: formData.has('is_accepting_engagements'),
      engagement_base_fee: parseFloat(formData.get('engagement_base_fee')) || 0,
      engagement_markup_pct: parseFloat(formData.get('engagement_markup_pct')) || 0,
    };

    if (_pendingIconDataUrl !== null) {
      body.icon_url = _pendingIconDataUrl;
    }

    try {
      await api(`/api/organizations/${org.id}`, { method: 'PATCH', body });
      _pendingIconDataUrl = null;
      flash('Settings saved', 'success');
      bus.emit('data:refresh');
      bus.emit('nav:org-selected', { orgId: org.id });
    } catch (err) {
      flash(err.message || 'Failed to save settings', 'error');
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Changes'; }
    }
  });
}
