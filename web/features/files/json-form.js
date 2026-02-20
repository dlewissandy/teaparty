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

  // Decorative header
  const header = document.createElement('div');
  header.className = 'cfg-agent-header';

  const avatarEl = document.createElement('div');
  avatarEl.className = 'cfg-agent-avatar';
  if (data.icon && isDataUrl(data.icon)) {
    avatarEl.innerHTML = `<img src="${escapeHtml(data.icon)}" alt="">`;
  } else {
    avatarEl.innerHTML = _generateBotSvg(data.name || 'Agent');
  }

  const nameBlock = document.createElement('div');
  nameBlock.innerHTML = `<strong>${escapeHtml(data.name || 'Agent')}</strong>`;
  if (data.role) nameBlock.innerHTML += `<div class="meta">${escapeHtml(data.role)}</div>`;

  header.appendChild(avatarEl);
  header.appendChild(nameBlock);
  container.appendChild(header);

  // Root section (compatible with collectJsonFromForm)
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

  const field = (key) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    emit(renderJsonFormField(key, data[key], readonly, [key]));
  };

  const textareaField = (key, label) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    emit(buildTextareaField(key, data[key], readonly, label));
  };

  const rangeField = (key, min, max, step, label) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    emit(buildRangeField(key, data[key], readonly, min, max, step, label));
  };

  const hiddenField = (key) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    emit(buildHiddenField(key, data[key]));
  };

  // Identity
  emit(buildSectionDivider('Identity'));
  hiddenField('id');
  field('name');
  field('role');
  textareaField('description', 'description');

  // Personality
  emit(buildSectionDivider('Personality'));
  textareaField('personality', 'personality');
  textareaField('backstory', 'backstory');

  // Model & Behavior
  emit(buildSectionDivider('Model & Behavior'));
  field('model');
  rangeField('temperature', 0, 2, 0.1, 'temperature');
  rangeField('verbosity', 0, 1, 0.05, 'verbosity');
  rangeField('response_threshold', 0, 1, 0.05, 'response_threshold');

  // Tools
  if ('tool_names' in data && Array.isArray(data.tool_names)) {
    knownKeys.add('tool_names');
    emit(buildSectionDivider('Tools'));

    const toolSection = document.createElement('details');
    toolSection.className = 'json-section';
    toolSection.open = true;
    toolSection.dataset.key = 'tool_names';
    toolSection.dataset.type = 'array';

    const toolSummary = document.createElement('summary');
    toolSummary.className = 'json-section-summary';
    toolSummary.textContent = `tool_names (${data.tool_names.length} items)`;
    toolSection.appendChild(toolSummary);

    const toolBody = document.createElement('div');
    toolBody.className = 'json-section-body cfg-tools-grid';

    const currentTools = [...data.tool_names];

    function rebuildToolPills() {
      toolBody.innerHTML = '';
      currentTools.forEach((tool, i) => {
        const pill = document.createElement('label');
        pill.className = 'cfg-tool-pill';
        pill.dataset.key = String(i);

        const inp = document.createElement('input');
        inp.type = 'hidden';
        inp.dataset.type = 'string';
        inp.dataset.key = String(i);
        inp.value = tool;
        pill.appendChild(inp);

        const txt = document.createElement('span');
        txt.textContent = tool;
        pill.appendChild(txt);

        if (!readonly) {
          const removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'cfg-tool-remove';
          removeBtn.textContent = '\u00d7';
          removeBtn.addEventListener('click', () => {
            currentTools.splice(i, 1);
            rebuildToolPills();
          });
          pill.appendChild(removeBtn);
        }

        toolBody.appendChild(pill);
      });

      if (!readonly) {
        const addRow = document.createElement('div');
        addRow.className = 'cfg-tool-add-row';
        const addInput = document.createElement('input');
        addInput.type = 'text';
        addInput.className = 'cfg-tool-add-input';
        addInput.placeholder = 'Add tool (e.g. Bash)';
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'cfg-tool-add';
        addBtn.textContent = '+';
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
        toolBody.appendChild(addRow);
      }

      toolSummary.textContent = `tool_names (${currentTools.length} items)`;
    }

    rebuildToolPills();
    toolSection.appendChild(toolBody);
    emit(toolSection);
  }

  // Hidden icon
  hiddenField('icon');

  // Fallback: any unknown keys
  for (const [k, v] of Object.entries(data)) {
    if (!knownKeys.has(k)) {
      emit(renderJsonFormField(k, v, readonly, [k]));
    }
  }

  details.appendChild(body);
  container.appendChild(details);
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
 * @param {HTMLElement} container
 * @returns {*} parsed JSON value, or null if no form found
 */
export function collectJsonFromForm(container) {
  const root = container.querySelector('.json-section');
  if (!root) return null;
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
