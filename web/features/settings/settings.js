// Unified settings modal.
// Ported from modules/settings-modal.js to use the reactive store.

import { flash } from '../../components/shared/flash.js';
import { bus } from '../../core/bus.js';

let _store = null;
let _submitHandler = null;

export function initSettings(store) {
  _store = store;

  // Close button
  const closeBtn = document.getElementById('settings-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => closeSettingsModal());
  }

  // Backdrop click to close
  const modal = document.getElementById('settings-modal');
  if (modal) {
    modal.querySelector('.modal-backdrop')?.addEventListener('click', () => {
      requestSettingsClose({ saveIfDirty: false });
    });
  }

  // Escape key to close
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _store.get().ui.settingsOpen) {
      requestSettingsClose({ saveIfDirty: false });
    }
  });

  // Listen for settings open requests from bus
  bus.on('settings:open', (detail) => {
    openSettingsModal(detail);
  });
}

export function openSettingsModal({ title, subtitle = '', formHtml, onSubmit, onRender = null }) {
  const modal = document.getElementById('settings-modal');
  const form = document.getElementById('settings-form');
  const titleEl = document.getElementById('settings-title');
  const subtitleEl = document.getElementById('settings-subtitle');

  if (titleEl) titleEl.textContent = title;
  if (subtitleEl) {
    subtitleEl.textContent = subtitle;
    subtitleEl.classList.toggle('hidden', !subtitle);
  }

  if (!form || !modal) return;
  form.innerHTML = formHtml;
  _submitHandler = onSubmit;

  form.onsubmit = async (event) => {
    event.preventDefault();
    await submitSettingsForm(form);
  };

  const cancel = form.querySelector("[data-action='settings-cancel']");
  if (cancel) {
    cancel.addEventListener('click', () => closeSettingsModal());
  }

  if (onRender) onRender(form);

  modal.classList.remove('hidden');
  _store.update(s => { s.ui.settingsOpen = true; });

  const firstInput = form.querySelector('input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
  if (firstInput) firstInput.focus();
}

export function closeSettingsModal() {
  const modal = document.getElementById('settings-modal');
  const form = document.getElementById('settings-form');

  if (modal) modal.classList.add('hidden');
  _store.update(s => { s.ui.settingsOpen = false; });
  _submitHandler = null;

  if (form) {
    form.onsubmit = null;
    form.innerHTML = '';
  }

  const titleEl = document.getElementById('settings-title');
  const subtitleEl = document.getElementById('settings-subtitle');
  if (titleEl) titleEl.textContent = 'Settings';
  if (subtitleEl) { subtitleEl.textContent = ''; subtitleEl.classList.add('hidden'); }
}

function settingsFormIsDirty(form) {
  const fields = form.querySelectorAll('input, textarea, select');
  for (const field of fields) {
    if (field.disabled) continue;
    if (field instanceof HTMLInputElement && (field.type === 'checkbox' || field.type === 'radio')) {
      if (field.checked !== field.defaultChecked) return true;
      continue;
    }
    if (field.value !== field.defaultValue) return true;
  }
  return false;
}

async function submitSettingsForm(form) {
  if (!_submitHandler) { closeSettingsModal(); return; }

  const submitButton = form.querySelector("button[type='submit']");
  const originalLabel = submitButton?.textContent || '';
  if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Saving...'; }

  try {
    await _submitHandler(new FormData(form));
    closeSettingsModal();
  } catch (error) {
    flash(error.message || 'Failed to save settings', 'error');
    if (submitButton) { submitButton.disabled = false; submitButton.textContent = originalLabel; }
  }
}

export async function requestSettingsClose({ saveIfDirty = false } = {}) {
  if (!_store.get().ui.settingsOpen) return;
  const form = document.getElementById('settings-form');
  if (saveIfDirty && _submitHandler && form && settingsFormIsDirty(form)) {
    await submitSettingsForm(form);
    return;
  }
  closeSettingsModal();
}
