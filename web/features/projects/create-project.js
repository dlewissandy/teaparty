// Create Project: inline form above composer for creating new projects.
// Listens for nav:create-project, renders workgroup pills, submits to projects API.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

const ELS = {};

export function initCreateProject(store) {
  _store = store;

  ELS.form = document.getElementById('create-project-form');
  ELS.prompt = document.getElementById('create-project-prompt');
  ELS.model = document.getElementById('create-project-model');
  ELS.turns = document.getElementById('create-project-turns');
  ELS.perms = document.getElementById('create-project-perms');
  ELS.cost = document.getElementById('create-project-cost');
  ELS.time = document.getElementById('create-project-time');
  ELS.tokens = document.getElementById('create-project-tokens');
  ELS.pills = document.getElementById('create-project-wg-pills');
  ELS.submit = document.getElementById('create-project-submit');
  ELS.cancel = document.getElementById('create-project-cancel');

  if (!ELS.form) return;

  bus.on('nav:create-project', ({ orgId }) => showForm(orgId));

  ELS.cancel.addEventListener('click', hideForm);
  ELS.submit.addEventListener('click', handleSubmit);
  ELS.prompt.addEventListener('input', updateSubmitState);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isVisible()) hideForm();
  });

  // Auto-hide when navigating to a conversation
  store.on('nav.activeConversationId', () => {
    if (isVisible()) hideForm();
  });
}

// -- State --

let _orgId = '';
let _selectedWgIds = new Set();

function orgWorkgroups() {
  return (_store.get().data.workgroups || [])
    .filter(wg => wg.organization_id === _orgId && wg.name !== 'Administration');
}

function isVisible() {
  return ELS.form.classList.contains('visible');
}

// -- Show / Hide --

function showForm(orgId) {
  _orgId = orgId;

  // Populate workgroup pills (Administration is never project-eligible)
  const workgroups = orgWorkgroups();
  _selectedWgIds = new Set(workgroups.map(wg => wg.id));
  renderPills(workgroups);

  // Reset fields
  ELS.prompt.value = '';
  ELS.model.value = 'claude-sonnet-4-6';
  ELS.turns.value = '30';
  ELS.perms.value = 'plan';
  ELS.cost.value = '';
  ELS.time.value = '';
  ELS.tokens.value = '';
  updateSubmitState();

  // Animate in
  ELS.form.classList.remove('hidden');
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      ELS.form.classList.add('visible');
      ELS.prompt.focus();
    });
  });
}

function hideForm() {
  ELS.form.classList.remove('visible');

  const onEnd = () => {
    ELS.form.removeEventListener('transitionend', onEnd);
    clearTimeout(fallback);
    ELS.form.classList.add('hidden');
  };

  const fallback = setTimeout(onEnd, 400);
  ELS.form.addEventListener('transitionend', onEnd, { once: true });
}

// -- Workgroup pills --

function renderPills(workgroups) {
  ELS.pills.innerHTML = workgroups.map(wg => {
    const selected = _selectedWgIds.has(wg.id);
    return `<span class="tool-chip${selected ? ' active' : ''}" data-wg-id="${escapeHtml(wg.id)}" role="button" tabindex="0" aria-pressed="${selected}">
      ${escapeHtml(wg.name)}
    </span>`;
  }).join('');

  ELS.pills.querySelectorAll('.tool-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const wgId = chip.dataset.wgId;
      if (_selectedWgIds.has(wgId)) {
        if (_selectedWgIds.size <= 1) return; // keep at least one
        _selectedWgIds.delete(wgId);
      } else {
        _selectedWgIds.add(wgId);
      }
      renderPills(orgWorkgroups());
    });
  });
}

// -- Submit --

function updateSubmitState() {
  ELS.submit.disabled = !ELS.prompt.value.trim();
}

async function handleSubmit() {
  const prompt = ELS.prompt.value.trim();
  if (!prompt) return;

  const body = {
    prompt,
    model: ELS.model.value,
    max_turns: parseInt(ELS.turns.value, 10),
    permission_mode: ELS.perms.value,
    workgroup_ids: [..._selectedWgIds],
  };

  // Only include budget fields if set
  const cost = parseFloat(ELS.cost.value);
  if (!isNaN(cost) && cost > 0) body.max_cost_usd = cost;

  const time = parseInt(ELS.time.value, 10);
  if (!isNaN(time) && time > 0) body.max_time_seconds = time * 60; // minutes → seconds

  const tokens = parseInt(ELS.tokens.value, 10);
  if (!isNaN(tokens) && tokens > 0) body.max_tokens = tokens;

  ELS.submit.disabled = true;
  try {
    const project = await api(`/api/organizations/${_orgId}/projects`, {
      method: 'POST',
      body,
    });

    hideForm();
    flash('Project started', 'success');
    bus.emit('data:refresh');

    if (project.conversation_id) {
      const wgId = body.workgroup_ids[0];
      bus.emit('nav:conversation-selected', {
        workgroupId: wgId,
        conversationId: project.conversation_id,
      });
    }
  } catch (err) {
    flash(err.message || 'Failed to create project', 'error');
    updateSubmitState();
  }
}
