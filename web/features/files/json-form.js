// JSON form editor.
// Ported from modules/json-forms.js, adapted to work with an explicit container
// argument instead of a global qs("file-panel-form") reference.

import { escapeHtml, isDataUrl, normalizeWorkgroupFiles } from '../../core/utils.js';

// ---- Public API ----

/**
 * Render a generic JSON value as an editable form into `container`.
 * @param {HTMLElement} container
 * @param {*} data
 * @param {boolean} readonly
 * @param {Set|null} lockedKeys - top-level keys that should be read-only
 */
export function renderJsonForm(container, data, readonly, lockedKeys) {
  container.innerHTML = '';
  if (data !== null && typeof data === 'object') {
    const isArray = Array.isArray(data);
    const section = buildCollapsibleSection('root', data, readonly, [], isArray, lockedKeys);
    section.open = true;
    section.classList.add('json-root');
    container.appendChild(section);
  } else {
    const field = renderJsonFormField('value', data, readonly, []);
    if (field) container.appendChild(field);
  }
}

/**
 * Render a specialized agent config form into `container`.
 * @param {HTMLElement} container
 * @param {object} data
 * @param {boolean} readonly
 */
export function renderAgentConfigForm(container, data, readonly) {
  container.innerHTML = '';

  // ---- Hero header ----
  const hero = document.createElement('div');
  hero.className = 'cfg-agent-hero';

  const avatarEl = document.createElement('div');
  avatarEl.className = 'cfg-agent-avatar';
  if (data.image && isDataUrl(data.image)) {
    avatarEl.innerHTML = `<img src="${escapeHtml(data.image)}" alt="" class="cfg-agent-avatar-img">`;
  } else {
    avatarEl.innerHTML = _generateBotSvg(data.name || 'Agent');
  }

  const heroText = document.createElement('div');
  heroText.className = 'cfg-agent-hero-text';
  heroText.innerHTML = `<h3 class="cfg-agent-name">${escapeHtml(data.name || 'Agent')}</h3>` +
    `<p class="cfg-agent-meta">Agent Configuration</p>`;

  hero.appendChild(avatarEl);
  hero.appendChild(heroText);
  container.appendChild(hero);

  // ---- Root section (required for collectJsonFromForm compatibility) ----
  const details = document.createElement('details');
  details.className = 'json-section json-root cfg-agent-root';
  details.open = true;
  details.dataset.key = 'root';
  details.dataset.type = 'object';
  details.dataset.formType = 'agent';

  // Hidden summary — visually invisible but required by collectJsonFromForm
  const summary = document.createElement('summary');
  summary.className = 'json-section-summary cfg-agent-summary-hidden';
  summary.textContent = 'root';
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'json-section-body cfg-agent-body';

  const knownKeys = new Set();

  // Helper to emit a field wrapper (direct child of body for collection)
  const emit = (el) => body.appendChild(el);

  // ---- Card 1: Identity ----
  const identityCard = _buildCard(
    'Identity',
    '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><circle cx="10" cy="7" r="3.5" stroke="currentColor" stroke-width="1.3"/><path d="M3 17c0-3.866 3.134-7 7-7s7 3.134 7 7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
  );
  body.appendChild(identityCard);

  // Hidden id
  knownKeys.add('id');
  if ('id' in data) emit(buildHiddenField('id', data.id));

  // name input
  knownKeys.add('name');
  if ('name' in data) {
    const nameField = _buildAgentTextField('name', 'Name', data.name, readonly, 'Agent name');
    identityCard.querySelector('.cfg-agent-card-body').appendChild(nameField);
    emit(_buildProxyField('name'));
  }

  // description textarea
  knownKeys.add('description');
  if ('description' in data) {
    const descField = _buildAgentTextareaField('description', 'Description', data.description, readonly, 'When to use this agent…', 3);
    identityCard.querySelector('.cfg-agent-card-body').appendChild(descField);
    emit(_buildProxyField('description'));
  }

  // prompt textarea
  knownKeys.add('prompt');
  if ('prompt' in data) {
    const promptField = _buildAgentTextareaField('prompt', 'Prompt', data.prompt, readonly, 'Agent behavior instructions…', 7);
    identityCard.querySelector('.cfg-agent-card-body').appendChild(promptField);
    emit(_buildProxyField('prompt'));
  }

  // ---- Card 2: Configuration ----
  const configCard = _buildCard(
    'Configuration',
    '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><circle cx="10" cy="10" r="2" fill="currentColor"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>'
  );
  body.appendChild(configCard);
  const configBody = configCard.querySelector('.cfg-agent-card-body');

  knownKeys.add('model');
  if ('model' in data) {
    configBody.appendChild(_buildAgentSelectField('model', 'Model', data.model, [
      { value: 'sonnet', label: 'Claude Sonnet (default)' },
      { value: 'opus',   label: 'Claude Opus (most capable)' },
      { value: 'haiku',  label: 'Claude Haiku (fastest)' },
    ], readonly));
    emit(_buildProxyField('model'));
  }

  knownKeys.add('permission_mode');
  if ('permission_mode' in data) {
    configBody.appendChild(_buildAgentSelectField('permission_mode', 'Permission Mode', data.permission_mode, [
      { value: 'default',     label: 'Default (ask before changes)' },
      { value: 'acceptEdits', label: 'Accept Edits (auto-approve edits)' },
      { value: 'dontAsk',    label: 'Don\'t Ask (fully autonomous)' },
      { value: 'plan',       label: 'Plan (read-only planning)' },
    ], readonly));
    emit(_buildProxyField('permission_mode'));
  }

  knownKeys.add('memory');
  if ('memory' in data) {
    configBody.appendChild(_buildAgentSelectField('memory', 'Memory', data.memory, [
      { value: '',        label: 'None' },
      { value: 'user',    label: 'User (per-user memory)' },
      { value: 'project', label: 'Project (shared project memory)' },
      { value: 'local',   label: 'Local (local memory only)' },
    ], readonly));
    emit(_buildProxyField('memory'));
  }

  // ---- Card 3: Behavior ----
  const behaviorCard = _buildCard(
    'Behavior',
    '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M10 3L3 7v6l7 4 7-4V7L10 3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M10 3v14M3 7l7 4 7-4" stroke="currentColor" stroke-width="1.3"/></svg>'
  );
  body.appendChild(behaviorCard);
  const behaviorBody = behaviorCard.querySelector('.cfg-agent-card-body');

  knownKeys.add('background');
  if ('background' in data) {
    behaviorBody.appendChild(_buildAgentToggleRow(
      'background', 'Run in Background',
      'Agent operates asynchronously without holding the conversation',
      data.background, readonly
    ));
    emit(_buildProxyField('background'));
  }

  knownKeys.add('isolation');
  if ('isolation' in data) {
    behaviorBody.appendChild(_buildAgentToggleRow(
      'isolation', 'Isolated Worktree',
      'Agent runs in a separate git worktree to avoid conflicts',
      data.isolation, readonly
    ));
    emit(_buildProxyField('isolation'));
  }

  // ---- Card 4: Tools ----
  if ('tools' in data && Array.isArray(data.tools)) {
    knownKeys.add('tools');

    const toolsCard = _buildCard(
      'Tools',
      '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M4 16l3.5-3.5M13.5 3a2.5 2.5 0 010 5H11L8.5 5.5A2.5 2.5 0 0113.5 3z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 4l4 4-4.5 4.5a1.5 1.5 0 002 2L10 10l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    );
    body.appendChild(toolsCard);
    const toolsCardBody = toolsCard.querySelector('.cfg-agent-card-body');

    // The tool section is a direct json-section child for collection
    const toolSection = document.createElement('details');
    toolSection.className = 'json-section cfg-agent-tool-section';
    toolSection.open = true;
    toolSection.dataset.key = 'tools';
    toolSection.dataset.type = 'array';

    const toolSummary = document.createElement('summary');
    toolSummary.className = 'json-section-summary cfg-agent-summary-hidden';
    toolSummary.textContent = `tools (${data.tools.length} items)`;
    toolSection.appendChild(toolSummary);

    const toolBody = document.createElement('div');
    toolBody.className = 'json-section-body cfg-agent-tools-body';
    toolSection.appendChild(toolBody);

    const currentTools = [...data.tools];

    // Pill list lives visually in the card body
    const pillContainer = document.createElement('div');
    pillContainer.className = 'cfg-agent-pill-list';
    toolsCardBody.appendChild(pillContainer);

    function rebuildToolPills() {
      // Sync hidden inputs in the json-section-body (for collection)
      toolBody.innerHTML = '';
      currentTools.forEach((tool, i) => {
        const inp = document.createElement('input');
        inp.type = 'hidden';
        inp.dataset.type = 'string';
        inp.dataset.key = String(i);
        inp.value = tool;
        // Wrap in a div with data-key for collectJsonValue
        const wrap = document.createElement('div');
        wrap.dataset.key = String(i);
        wrap.appendChild(inp);
        toolBody.appendChild(wrap);
      });

      // Rebuild visual pills
      pillContainer.innerHTML = '';
      currentTools.forEach((tool, i) => {
        const pill = document.createElement('span');
        pill.className = 'cfg-agent-pill';

        const txt = document.createElement('span');
        txt.className = 'cfg-agent-pill-text';
        txt.textContent = tool;
        pill.appendChild(txt);

        if (!readonly) {
          const removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'cfg-agent-pill-remove';
          removeBtn.setAttribute('aria-label', `Remove ${tool}`);
          removeBtn.innerHTML = '<svg viewBox="0 0 10 10" width="10" height="10"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
          removeBtn.addEventListener('click', () => {
            currentTools.splice(i, 1);
            rebuildToolPills();
          });
          pill.appendChild(removeBtn);
        }

        pillContainer.appendChild(pill);
      });

      if (!readonly) {
        const addRow = document.createElement('div');
        addRow.className = 'cfg-agent-add-row';

        const addInput = document.createElement('input');
        addInput.type = 'text';
        addInput.className = 'cfg-agent-add-input';
        addInput.placeholder = 'Add tool…';

        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'cfg-agent-add-btn';
        addBtn.textContent = 'Add';
        addBtn.addEventListener('click', () => {
          const name = addInput.value.trim();
          if (!name || currentTools.includes(name)) { addInput.value = ''; return; }
          currentTools.push(name);
          addInput.value = '';
          rebuildToolPills();
        });
        addInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); addBtn.click(); }
        });

        addRow.appendChild(addInput);
        addRow.appendChild(addBtn);
        pillContainer.appendChild(addRow);
      }

      toolSummary.textContent = `tools (${currentTools.length} items)`;
    }

    rebuildToolPills();
    emit(toolSection);
  }

  // ---- Card 5: Hooks ----
  if ('hooks' in data && typeof data.hooks === 'object') {
    knownKeys.add('hooks');

    const hooksCard = _buildCard(
      'Hooks',
      '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M10 3v7l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.3"/></svg>'
    );
    body.appendChild(hooksCard);
    const hooksCardBody = hooksCard.querySelector('.cfg-agent-card-body');

    // Build the collapsible section and place it in the card body (visible).
    // We also emit it to the main body for collectJsonValue compatibility.
    // Since a DOM node can only have one parent, we emit it AFTER the card
    // (the card is already appended to body; hooksSection goes in as a direct
    // body child for collection and the card holds the visual reference only).
    const hooksSection = buildCollapsibleSection('hooks', data.hooks, readonly, ['hooks'], false, null);
    hooksSection.classList.add('cfg-agent-hooks-section');
    // Place visually inside the card
    hooksCardBody.appendChild(hooksSection);
    // The hooksSection is inside the card which is inside the body — collectAgentConfigForm
    // queries it by data-key="hooks" anywhere inside root, so this is fine.
    // No need for a separate emit.
    knownKeys.add('hooks'); // already added above, idempotent on Set
  }

  // ---- Hidden image field ----
  knownKeys.add('image');
  if ('image' in data) emit(buildHiddenField('image', data.image));

  // ---- Fallback: unknown keys ----
  for (const [k, v] of Object.entries(data)) {
    if (!knownKeys.has(k)) {
      emit(renderJsonFormField(k, v, readonly, [k]));
    }
  }

  details.appendChild(body);
  container.appendChild(details);
}

/**
 * Collect agent config form data by querying data-key inputs directly.
 * Used when the form has data-form-type="agent".
 * @param {HTMLElement} container - the #file-form element
 * @returns {object|null}
 */
export function collectAgentConfigForm(container) {
  const root = container.querySelector('.json-section[data-form-type="agent"]');
  if (!root) return null;

  const result = {};

  // Collect scalar fields — data-key is on the input/textarea/select itself
  const scalars = ['name', 'description', 'prompt', 'model', 'permission_mode', 'memory'];
  for (const key of scalars) {
    const el = root.querySelector(`input[data-key="${key}"], textarea[data-key="${key}"], select[data-key="${key}"]`);
    if (el) result[key] = el.value;
  }

  // Collect boolean toggles — data-key is on the checkbox itself
  const booleans = ['background', 'isolation'];
  for (const key of booleans) {
    const el = root.querySelector(`input[type="checkbox"][data-key="${key}"]`);
    if (el) result[key] = el.checked;
  }

  // Collect hidden string fields — data-key is on the hidden input itself
  // (wrapped in a .cfg-hidden-field div with matching data-key on the wrapper too)
  const hiddens = ['id', 'image'];
  for (const key of hiddens) {
    const el = root.querySelector(`input[type="hidden"][data-key="${key}"]`);
    if (el && el.value !== '') result[key] = el.value;
  }

  // Collect tools array from the json-section
  const toolSection = root.querySelector('.json-section[data-key="tools"]');
  if (toolSection) {
    const toolBody = toolSection.querySelector(':scope > .json-section-body');
    if (toolBody) {
      const tools = [];
      for (const child of toolBody.children) {
        const inp = child.querySelector('input');
        if (inp) tools.push(inp.value);
      }
      result.tools = tools;
    }
  }

  // Collect hooks from the nested json-section
  const hooksSection = root.querySelector('.json-section[data-key="hooks"]');
  if (hooksSection) {
    result.hooks = collectJsonValue(hooksSection);
  }

  // Collect any unknown fallback fields from the body's direct children
  // (only applies to keys emitted by the generic renderJsonFormField fallback)
  const body = root.querySelector(':scope > .json-section-body');
  if (body) {
    for (const child of body.children) {
      const key = child.dataset.key;
      // Skip: no key, already collected, proxy fields, cards, and handled sections
      if (!key || key in result) continue;
      if (child.classList.contains('cfg-agent-proxy-field')) continue;
      if (child.classList.contains('cfg-agent-card')) continue;
      if (child.classList.contains('cfg-hidden-field')) continue;
      if (child.classList.contains('json-section')) continue;
      // Generic collection for unexpected scalar fields
      const inp = child.querySelector('input,textarea,select');
      if (inp && inp.dataset.type === 'boolean') {
        result[key] = inp.checked;
      } else if (inp) {
        result[key] = inp.value;
      }
    }
  }

  return result;
}

// ---- Agent form helpers (private) ----

/** Build a visual card with a header icon, title, and body container. */
function _buildCard(title, iconSvg) {
  const card = document.createElement('div');
  card.className = 'cfg-agent-card';

  const cardHeader = document.createElement('div');
  cardHeader.className = 'cfg-agent-card-header';

  const iconEl = document.createElement('span');
  iconEl.className = 'cfg-agent-card-icon';
  iconEl.innerHTML = iconSvg;

  const titleEl = document.createElement('h4');
  titleEl.className = 'cfg-agent-card-title';
  titleEl.textContent = title;

  cardHeader.appendChild(iconEl);
  cardHeader.appendChild(titleEl);
  card.appendChild(cardHeader);

  const cardBody = document.createElement('div');
  cardBody.className = 'cfg-agent-card-body';
  card.appendChild(cardBody);

  return card;
}

/** Build a label+input text field for the agent form. */
function _buildAgentTextField(key, label, value, readonly, placeholder) {
  const field = document.createElement('div');
  field.className = 'cfg-agent-field';

  const lbl = document.createElement('label');
  lbl.className = 'cfg-agent-label';
  lbl.setAttribute('for', `agent-field-${key}`);
  lbl.textContent = label;

  const input = document.createElement('input');
  input.type = 'text';
  input.id = `agent-field-${key}`;
  input.className = 'cfg-agent-input';
  input.value = value ?? '';
  input.placeholder = placeholder || '';
  input.dataset.key = key;
  input.dataset.type = 'string';
  if (readonly) input.disabled = true;

  field.appendChild(lbl);
  field.appendChild(input);
  return field;
}

/** Build a label+textarea field for the agent form. */
function _buildAgentTextareaField(key, label, value, readonly, placeholder, rows) {
  const field = document.createElement('div');
  field.className = 'cfg-agent-field';

  const lbl = document.createElement('label');
  lbl.className = 'cfg-agent-label';
  lbl.setAttribute('for', `agent-field-${key}`);
  lbl.textContent = label;

  const ta = document.createElement('textarea');
  ta.id = `agent-field-${key}`;
  ta.className = 'cfg-agent-textarea';
  ta.value = value ?? '';
  ta.rows = rows || 3;
  ta.placeholder = placeholder || '';
  ta.dataset.key = key;
  ta.dataset.type = 'string';
  if (readonly) ta.disabled = true;

  field.appendChild(lbl);
  field.appendChild(ta);
  return field;
}

/** Build a label+select dropdown field for the agent form. */
function _buildAgentSelectField(key, label, value, options, readonly) {
  const field = document.createElement('div');
  field.className = 'cfg-agent-field';

  const lbl = document.createElement('label');
  lbl.className = 'cfg-agent-label';
  lbl.setAttribute('for', `agent-field-${key}`);
  lbl.textContent = label;

  const selectWrap = document.createElement('div');
  selectWrap.className = 'cfg-agent-select-wrap';

  const select = document.createElement('select');
  select.id = `agent-field-${key}`;
  select.className = 'cfg-agent-select';
  select.dataset.key = key;
  select.dataset.type = 'string';
  if (readonly) select.disabled = true;

  for (const opt of options) {
    const o = document.createElement('option');
    o.value = opt.value;
    o.textContent = opt.label;
    if ((value ?? '') === opt.value) o.selected = true;
    select.appendChild(o);
  }

  const chevron = document.createElement('span');
  chevron.className = 'cfg-agent-select-chevron';
  chevron.innerHTML = '<svg viewBox="0 0 12 8" width="12" height="8" fill="none"><path d="M1 1l5 5 5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  selectWrap.appendChild(select);
  selectWrap.appendChild(chevron);

  field.appendChild(lbl);
  field.appendChild(selectWrap);
  return field;
}

/** Build a toggle switch row for a boolean field. */
function _buildAgentToggleRow(key, label, hint, value, readonly) {
  const row = document.createElement('div');
  row.className = 'cfg-agent-toggle-row';

  const textBlock = document.createElement('div');
  textBlock.className = 'cfg-agent-toggle-text';

  const labelEl = document.createElement('span');
  labelEl.className = 'cfg-agent-toggle-label';
  labelEl.textContent = label;

  const hintEl = document.createElement('span');
  hintEl.className = 'cfg-agent-toggle-hint';
  hintEl.textContent = hint;

  textBlock.appendChild(labelEl);
  textBlock.appendChild(hintEl);

  const toggleLabel = document.createElement('label');
  toggleLabel.className = 'cfg-agent-toggle';

  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = !!value;
  checkbox.dataset.key = key;
  checkbox.dataset.type = 'boolean';
  if (readonly) checkbox.disabled = true;

  const track = document.createElement('span');
  track.className = 'cfg-agent-toggle-track';

  const thumb = document.createElement('span');
  thumb.className = 'cfg-agent-toggle-thumb';

  toggleLabel.appendChild(checkbox);
  toggleLabel.appendChild(track);
  toggleLabel.appendChild(thumb);

  row.appendChild(textBlock);
  row.appendChild(toggleLabel);
  return row;
}

/**
 * Build a proxy field element that carries a data-key for collectJsonFromForm
 * but has no visible content. Used when the real input lives inside a card.
 * The collector will find the input via child.querySelector('input,select,textarea').
 */
function _buildProxyField(key) {
  const wrap = document.createElement('div');
  wrap.className = 'cfg-agent-proxy-field';
  wrap.dataset.key = key;
  // No input — collectAgentConfigForm handles collection directly
  return wrap;
}

/**
 * Render a specialized workgroup config form into `container`.
 * @param {HTMLElement} container
 * @param {object} data
 * @param {boolean} readonly
 * @param {Set|null} lockedKeys
 * @param {object} store - reactive store (for stats)
 * @param {string} workgroupId
 */
export function renderWorkgroupConfigForm(container, data, readonly, lockedKeys, store, workgroupId) {
  container.innerHTML = '';

  const wgName = data.name || 'Workgroup';

  // Hero header
  const hero = document.createElement('div');
  hero.className = 'cfg-wg-hero';

  const icon = document.createElement('div');
  icon.className = 'cfg-wg-icon';
  let hash = 0;
  for (let i = 0; i < wgName.length; i++) hash = wgName.charCodeAt(i) + ((hash << 5) - hash);
  icon.style.background = `hsl(${((hash % 360) + 360) % 360}, 55%, 48%)`;
  icon.textContent = wgName.charAt(0).toUpperCase();

  const heroText = document.createElement('div');
  heroText.className = 'cfg-wg-hero-text';
  heroText.innerHTML = `<h3>${escapeHtml(wgName)}</h3>` +
    (data.service_description ? `<div class="meta">${escapeHtml(data.service_description)}</div>` : '');

  hero.appendChild(icon);
  hero.appendChild(heroText);
  container.appendChild(hero);

  // Stats strip
  if (store && workgroupId) {
    const s = store.get();
    const wgData = s.data?.treeData?.[workgroupId];
    if (wgData) {
      const memberCount = (wgData.members || []).length;
      const agentCount = (wgData.agents || []).filter(a => a.description !== '__system_admin_agent__').length;
      const fileCount = normalizeWorkgroupFiles(wgData.workgroup?.files).length;
      const jobCount = (wgData.jobs || []).filter(t => t.kind === 'job').length;

      const stats = document.createElement('div');
      stats.className = 'cfg-wg-stats';
      [
        [memberCount, 'Users'],
        [agentCount, 'Agents'],
        [fileCount, 'Files'],
        [jobCount, 'Jobs'],
      ].forEach(([val, label]) => {
        const pill = document.createElement('div');
        pill.className = 'cfg-wg-stat';
        pill.innerHTML = `<span class="cfg-wg-stat-value">${val}</span><span class="cfg-wg-stat-label">${label}</span>`;
        stats.appendChild(pill);
      });
      container.appendChild(stats);
    }
  }

  // Root section
  const details = document.createElement('details');
  details.className = 'json-section json-root';
  details.open = true;
  details.dataset.key = 'root';
  details.dataset.type = 'object';

  const summary = document.createElement('summary');
  summary.className = 'json-section-summary';
  summary.textContent = 'root';
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'json-section-body';

  const knownKeys = new Set();
  const emit = (el) => { body.appendChild(el); };

  const field = (key, forceReadonly) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    const ro = readonly || forceReadonly || (lockedKeys && lockedKeys.has(key));
    emit(renderJsonFormField(key, data[key], ro, [key]));
  };

  // Identity
  emit(buildSectionDivider('Identity'));
  field('name');
  knownKeys.add('service_description');
  if ('service_description' in data) {
    const ro = readonly || (lockedKeys && lockedKeys.has('service_description'));
    emit(buildTextareaField('service_description', data.service_description, ro, 'service_description'));
  }

  // Visibility
  if ('is_discoverable' in data) {
    emit(buildSectionDivider('Visibility'));
    knownKeys.add('is_discoverable');
    emit(buildBooleanField('is_discoverable', data.is_discoverable, readonly, ['is_discoverable']));
    const help = document.createElement('div');
    help.className = 'cfg-wg-toggle-help';
    help.textContent = 'Make this workgroup visible to other users for cross-group collaboration';
    emit(help);
  }

  // System section (collapsed)
  knownKeys.add('id');
  knownKeys.add('owner_id');
  knownKeys.add('created_at');
  const sysDetails = document.createElement('details');
  sysDetails.className = 'cfg-wg-system';
  const sysSummary = document.createElement('summary');
  sysSummary.className = 'cfg-section-header';
  sysSummary.textContent = 'System';
  sysDetails.appendChild(sysSummary);

  const sysBody = document.createElement('div');
  [['id', data.id], ['owner_id', data.owner_id], ['created_at', data.created_at]].forEach(([key, val]) => {
    if (val == null) return;
    const row = document.createElement('div');
    row.className = 'cfg-wg-system-row';
    row.innerHTML = `<span class="cfg-wg-system-label">${escapeHtml(key)}</span><span>${escapeHtml(String(val))}</span>`;
    sysBody.appendChild(row);
    sysBody.appendChild(buildHiddenField(key, String(val)));
  });
  sysDetails.appendChild(sysBody);
  emit(sysDetails);

  // Fallback: unknown keys
  for (const [k, v] of Object.entries(data)) {
    if (!knownKeys.has(k)) {
      emit(renderJsonFormField(k, v, readonly, [k]));
    }
  }

  details.appendChild(body);
  container.appendChild(details);
}

/**
 * Collect the form values from `container` back into a JSON value.
 * Dispatches to collectAgentConfigForm for agent forms.
 * @param {HTMLElement} container
 * @returns {*} parsed JSON value, or null if no form found
 */
export function collectJsonFromForm(container) {
  const root = container.querySelector('.json-section');
  if (!root) return null;
  // Dispatch to specialized agent collector
  if (root.dataset.formType === 'agent') {
    return collectAgentConfigForm(container);
  }
  return collectJsonValue(root);
}

// ---- Field builders (exported for external use) ----

export function renderJsonFormField(key, value, readonly, path, lockedKeys) {
  if (value === null) {
    return buildScalarField(key, 'null', 'null', true, path);
  }
  switch (typeof value) {
    case 'string':
      return buildScalarField(key, 'string', value, readonly, path);
    case 'number':
      return buildScalarField(key, 'number', value, readonly, path);
    case 'boolean':
      return buildBooleanField(key, value, readonly, path);
    case 'object':
      return buildCollapsibleSection(key, value, readonly, path, Array.isArray(value), lockedKeys);
    default:
      return buildScalarField(key, 'string', String(value), readonly, path);
  }
}

export function buildScalarField(key, type, value, readonly, path) {
  const label = document.createElement('label');
  label.className = 'json-field' + (type === 'null' ? ' json-null' : '');

  const span = document.createElement('span');
  span.className = 'json-field-label';
  span.textContent = key;
  span.title = key;

  const input = document.createElement('input');
  input.type = type === 'number' ? 'number' : 'text';
  if (type === 'number') input.step = 'any';
  input.value = value;
  input.dataset.key = key;
  input.dataset.type = type;
  input.dataset.path = path.join('.');
  if (readonly || type === 'null') input.disabled = true;

  label.appendChild(span);
  label.appendChild(input);
  return label;
}

export function buildBooleanField(key, value, readonly, path) {
  const label = document.createElement('label');
  label.className = 'json-field json-field-bool';

  const span = document.createElement('span');
  span.className = 'json-field-label';
  span.textContent = key;
  span.title = key;

  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = value;
  input.dataset.key = key;
  input.dataset.type = 'boolean';
  input.dataset.path = path.join('.');
  if (readonly) input.disabled = true;

  label.appendChild(span);
  label.appendChild(input);
  return label;
}

export function buildCollapsibleSection(key, value, readonly, path, isArray, lockedKeys) {
  const details = document.createElement('details');
  details.className = 'json-section';
  details.open = true;
  details.dataset.key = key;
  details.dataset.type = isArray ? 'array' : 'object';
  details.dataset.path = path.join('.');

  const summary = document.createElement('summary');
  summary.className = 'json-section-summary';
  const entries = isArray ? value.length : Object.keys(value).length;
  const typeLabel = isArray ? 'items' : 'keys';
  summary.textContent = `${key} (${entries} ${typeLabel})`;
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'json-section-body';

  if (isArray) {
    value.forEach((item, index) => {
      const field = renderJsonFormField(String(index), item, readonly, [...path, String(index)], lockedKeys);
      if (field) body.appendChild(field);
    });
  } else {
    for (const [k, v] of Object.entries(value)) {
      const fieldReadonly = readonly || (lockedKeys && path.length === 0 && lockedKeys.has(k));
      const field = renderJsonFormField(k, v, fieldReadonly, [...path, k], lockedKeys);
      if (field) body.appendChild(field);
    }
  }

  details.appendChild(body);
  return details;
}

export function buildSectionDivider(title) {
  const div = document.createElement('div');
  div.className = 'cfg-section-header';
  div.textContent = title;
  return div;
}

export function buildTextareaField(key, value, readonly, label) {
  const wrap = document.createElement('div');
  wrap.className = 'cfg-field-wide';
  wrap.dataset.key = key;

  const span = document.createElement('span');
  span.className = 'json-field-label';
  span.textContent = label || key;

  const ta = document.createElement('textarea');
  ta.dataset.type = 'string';
  ta.dataset.key = key;
  ta.value = value ?? '';
  ta.rows = 3;
  if (readonly) ta.disabled = true;

  wrap.appendChild(span);
  wrap.appendChild(ta);
  return wrap;
}

export function buildRangeField(key, value, readonly, min, max, step, label) {
  const wrap = document.createElement('div');
  wrap.className = 'cfg-range-field';
  wrap.dataset.key = key;

  const span = document.createElement('span');
  span.className = 'json-field-label';
  span.textContent = label || key;

  const row = document.createElement('div');
  row.className = 'cfg-range-row';

  const input = document.createElement('input');
  input.type = 'range';
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value ?? min;
  input.dataset.type = 'number';
  input.dataset.key = key;
  if (readonly) input.disabled = true;

  const valSpan = document.createElement('span');
  valSpan.className = 'cfg-range-value';
  valSpan.textContent = value ?? min;

  input.oninput = () => { valSpan.textContent = input.value; };

  row.appendChild(input);
  row.appendChild(valSpan);
  wrap.appendChild(span);
  wrap.appendChild(row);
  return wrap;
}

export function buildHiddenField(key, value) {
  const wrap = document.createElement('div');
  wrap.className = 'cfg-hidden-field';
  wrap.dataset.key = key;

  const input = document.createElement('input');
  input.type = 'hidden';
  input.dataset.type = 'string';
  input.dataset.key = key;
  input.value = value ?? '';

  wrap.appendChild(input);
  return wrap;
}

// ---- Collect ----

export function collectJsonValue(el) {
  if (el.classList.contains('json-section')) {
    const isArray = el.dataset.type === 'array';
    const body = el.querySelector(':scope > .json-section-body');
    if (!body) return isArray ? [] : {};

    if (isArray) {
      const result = [];
      for (const child of body.children) {
        result.push(collectJsonValue(child));
      }
      return result;
    } else {
      const result = {};
      for (const child of body.children) {
        const key = child.dataset.key || child.querySelector('input,select')?.dataset.key;
        if (key !== undefined) {
          result[key] = collectJsonValue(child);
        }
      }
      return result;
    }
  }

  const input = el.querySelector('input, textarea') || el;
  const type = input.dataset?.type;

  switch (type) {
    case 'string':
      return input.value;
    case 'number': {
      const n = Number(input.value);
      return isNaN(n) ? 0 : n;
    }
    case 'boolean':
      return input.checked;
    case 'null':
      return null;
    default:
      return input.value;
  }
}

// ---- Avatar (inline, no external dependency) ----

function _generateBotSvg(name) {
  const colors = [
    '#e8384f', '#fd612c', '#fd9a00', '#eec300',
    '#a4cf30', '#62b847', '#37c5ab', '#20aaea',
    '#4186e0', '#7a6ff0', '#aa62e3', '#e362e3',
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const color = colors[Math.abs(hash) % colors.length];
  const initial = (name || '?').charAt(0).toUpperCase();
  return `<svg viewBox="0 0 40 40" width="40" height="40" xmlns="http://www.w3.org/2000/svg">
    <rect width="40" height="40" rx="8" fill="${color}"/>
    <text x="20" y="27" font-size="18" font-family="system-ui,sans-serif" font-weight="600"
      text-anchor="middle" fill="white">${escapeHtml(initial)}</text>
  </svg>`;
}
