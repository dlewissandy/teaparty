const state = {
  token: sessionStorage.getItem("teaparty_token") || localStorage.getItem("teaparty_token") || "",
  user: null,
  config: null,
  organizations: [],
  workgroups: [],
  treeData: {},
  workgroupTemplates: [],
  workgroupCreateTemplateKey: "",
  workgroupCreateFiles: [],
  workgroupCreateAgents: [],
  selectedWorkgroupId: "",
  bladeOrgId: "",
  bladeWorkgroupId: "",
  bladeAgentId: "",
  activeConversationId: "",
  activeNodeKey: "",
  selectedWorkgroupFileIdByWorkgroup: {},
  expandedWorkgroupIds: {},
  activeMessages: [],
  thinkingByConversation: {},
  pollTimer: null,
  settingsOpen: false,
  settingsSubmitHandler: null,
  fileOverlayOpen: false,
  fileOverlayWorkgroupId: "",
  fileOverlayFileId: "",
  fileOverlayShowRaw: false,
  fileOverlayViewMode: "raw",
  fileOverlayParsedJson: null,
  fileOverlayLastContent: "",
  fileOverlayMemberContext: null,
  crossGroupTasks: [],
  activeTaskId: "",
  activeEngagementId: "",
  workgroupDirectory: [],
  conversationUsage: null,
  usagePollCounter: 0,
  myInvites: [],
  invitePollCounter: 0,
  fileBrowserOpen: false,
  fileBrowserWorkgroupId: "",
  fileBrowserPath: [],
  fileBrowserFileId: "",
  fileBrowserScope: "",
  fileBrowserOrgId: "",
  fileBrowserCompositeFiles: [],
  thoughtsByMessageId: {},
  lastLiveActivity: null,
  toolbarVisible: false,
};

const qs = (id) => document.getElementById(id);
const THEME_STORAGE_KEY = "teaparty_theme";
const GEAR_ICON_SVG = `
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path
      d="M10.325 4.317a1.724 1.724 0 0 1 3.35 0a1.724 1.724 0 0 0 2.573 1.066a1.724 1.724 0 0 1 2.9 1.676a1.724 1.724 0 0 0 .632 2.692a1.724 1.724 0 0 1 0 2.498a1.724 1.724 0 0 0-.632 2.692a1.724 1.724 0 0 1-2.9 1.676a1.724 1.724 0 0 0-2.573 1.066a1.724 1.724 0 0 1-3.35 0a1.724 1.724 0 0 0-2.573-1.066a1.724 1.724 0 0 1-2.9-1.676a1.724 1.724 0 0 0-.632-2.692a1.724 1.724 0 0 1 0-2.498a1.724 1.724 0 0 0 .632-2.692a1.724 1.724 0 0 1 2.9-1.676a1.724 1.724 0 0 0 2.573-1.066Z"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path d="M12 15.75a3.75 3.75 0 1 0 0-7.5a3.75 3.75 0 0 0 0 7.5Z" stroke="currentColor" stroke-width="1.5" />
  </svg>
`;
const FINDER_FOLDER_ICON_SVG = `
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h4.2c.7 0 1.36.3 1.83.82l.92 1.02c.19.21.47.33.75.33H18A2.5 2.5 0 0 1 20.5 9.7v6.8A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z" fill="currentColor" />
    <path d="M3.5 9.5h17" stroke="#fff" stroke-width="1.2" stroke-linecap="round" opacity="0.45" />
  </svg>
`;
const FINDER_FILE_ICON_SVG = `
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path d="M7 3.5h6.8c.53 0 1.04.21 1.41.59l3.2 3.2c.38.37.59.88.59 1.41V19A1.5 1.5 0 0 1 17.5 20.5h-10A1.5 1.5 0 0 1 6 19V5A1.5 1.5 0 0 1 7.5 3.5z" fill="currentColor" />
    <path d="M14 3.7V8a1 1 0 0 0 1 1h4.3" stroke="#fff" stroke-width="1.2" stroke-linecap="round" opacity="0.75" />
  </svg>
`;
const FINDER_LINK_ICON_SVG = `
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path d="M7 3.5h6.8c.53 0 1.04.21 1.41.59l3.2 3.2c.38.37.59.88.59 1.41V19A1.5 1.5 0 0 1 17.5 20.5h-10A1.5 1.5 0 0 1 6 19V5A1.5 1.5 0 0 1 7.5 3.5z" fill="currentColor" />
    <path d="M10 14.2h4.8m0 0-1.7-1.7m1.7 1.7-1.7 1.7" stroke="#fff" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
`;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function linkifyUrls(escaped) {
  return escaped.replace(
    /\bhttps?:\/\/[^\s<>&"')\]]+/g,
    (url) => `<a href="${url.replace(/&amp;/g, '&')}" target="_blank" rel="noopener noreferrer">${url}</a>`,
  );
}

function parseFileContext(text) {
  const match = text.match(/^\[file: (.+?)\]\n<<<\n([\s\S]*?)\n>>>\n\n([\s\S]*)$/);
  if (match) return { path: match[1], fileContent: match[2], message: match[3] };
  return null;
}

function isMarkdownFile(filePath) {
  return /\.md$/i.test(filePath);
}

function isJsonFile(filePath) {
  return /\.json$/i.test(filePath);
}

function isImageFile(filePath) {
  return /\.(png|jpe?g|gif|svg|webp|bmp|ico)$/i.test(filePath);
}

function isDataUrl(content) {
  return /^data:image\//.test(content);
}

function isAgentConfigPath(p) { return /^agents\/[^/]+\.json$/i.test(p); }
function isWorkgroupConfigPath(p) { return p === "workgroup.json"; }
function isAgentConfigShape(d) {
  return d && typeof d === "object" && !Array.isArray(d)
    && "name" in d && "model" in d && "temperature" in d;
}

function tryParseJson(content) {
  try {
    return { ok: true, data: JSON.parse(content) };
  } catch {
    return { ok: false, data: null };
  }
}

function setFileOverlayViewMode(mode) {
  state.fileOverlayViewMode = mode;
  const pre = qs("file-overlay-content");
  const form = qs("file-overlay-form");
  const rawToggle = qs("file-overlay-raw-toggle");

  if (mode === "form") {
    pre.classList.add("hidden");
    form.classList.remove("hidden");
    rawToggle.textContent = "Raw";
  } else {
    pre.classList.remove("hidden");
    form.classList.add("hidden");
    rawToggle.textContent = "Form";
  }
}

function updateFileOverlayEditButton(isOwner, isFormMode, isJsonParsed) {
  const editBtn = qs("file-overlay-edit");
  if (isOwner && isFormMode && isJsonParsed) {
    editBtn.textContent = "Save";
    editBtn.classList.remove("hidden");
  } else if (isOwner) {
    editBtn.textContent = "Edit";
    editBtn.classList.remove("hidden");
  } else {
    editBtn.classList.add("hidden");
  }
}

function renderJsonForm(data, readonly, lockedKeys) {
  const container = qs("file-overlay-form");
  container.innerHTML = "";
  if (data !== null && typeof data === "object") {
    const isArray = Array.isArray(data);
    const section = buildCollapsibleSection("root", data, readonly, [], isArray, lockedKeys);
    section.open = true;
    section.classList.add("json-root");
    container.appendChild(section);
  } else {
    const field = renderJsonFormField("value", data, readonly, []);
    if (field) container.appendChild(field);
  }
}

function renderJsonFormField(key, value, readonly, path, lockedKeys) {
  if (value === null) {
    return buildScalarField(key, "null", "null", true, path);
  }
  switch (typeof value) {
    case "string":
      return buildScalarField(key, "string", value, readonly, path);
    case "number":
      return buildScalarField(key, "number", value, readonly, path);
    case "boolean":
      return buildBooleanField(key, value, readonly, path);
    case "object":
      return buildCollapsibleSection(key, value, readonly, path, Array.isArray(value), lockedKeys);
    default:
      return buildScalarField(key, "string", String(value), readonly, path);
  }
}


function renderAgentConfigForm(data, readonly) {
  const container = qs("file-overlay-form");
  container.innerHTML = "";

  // Decorative header
  const header = document.createElement("div");
  header.className = "cfg-agent-header";
  const avatarEl = document.createElement("div");
  avatarEl.className = "cfg-agent-avatar";
  if (data.icon && isDataUrl(data.icon)) {
    avatarEl.innerHTML = `<img src="${escapeHtml(data.icon)}" alt="">`;
  } else {
    avatarEl.innerHTML = generateBotSvg(data.name || "Agent");
  }
  const nameBlock = document.createElement("div");
  nameBlock.innerHTML = `<strong>${escapeHtml(data.name || "Agent")}</strong>`;
  if (data.role) nameBlock.innerHTML += `<div class="meta">${escapeHtml(data.role)}</div>`;
  header.appendChild(avatarEl);
  header.appendChild(nameBlock);
  container.appendChild(header);

  // Root section (compatible with collectJsonFromForm)
  const details = document.createElement("details");
  details.className = "json-section json-root";
  details.open = true;
  details.dataset.key = "root";
  details.dataset.type = "object";

  const summary = document.createElement("summary");
  summary.className = "json-section-summary";
  summary.textContent = "root";
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "json-section-body";

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
  emit(buildSectionDivider("Identity"));
  hiddenField("id");
  field("name");
  field("role");
  textareaField("description", "description");

  // Personality
  emit(buildSectionDivider("Personality"));
  textareaField("personality", "personality");
  textareaField("backstory", "backstory");

  // Model & Behavior
  emit(buildSectionDivider("Model & Behavior"));
  field("model");
  rangeField("temperature", 0, 2, 0.1, "temperature");
  rangeField("verbosity", 0, 1, 0.05, "verbosity");
  rangeField("response_threshold", 0, 1, 0.05, "response_threshold");
  field("follow_up_minutes");

  // Tools
  if ("tool_names" in data && Array.isArray(data.tool_names)) {
    knownKeys.add("tool_names");
    emit(buildSectionDivider("Tools"));

    const toolSection = document.createElement("details");
    toolSection.className = "json-section";
    toolSection.open = true;
    toolSection.dataset.key = "tool_names";
    toolSection.dataset.type = "array";

    const toolSummary = document.createElement("summary");
    toolSummary.className = "json-section-summary";
    toolSummary.textContent = `tool_names (${data.tool_names.length} items)`;
    toolSection.appendChild(toolSummary);

    const toolBody = document.createElement("div");
    toolBody.className = "json-section-body cfg-tools-grid";

    const currentTools = [...data.tool_names];

    function rebuildToolPills() {
      toolBody.innerHTML = "";
      currentTools.forEach((tool, i) => {
        const pill = document.createElement("label");
        pill.className = "cfg-tool-pill";
        pill.dataset.key = String(i);

        const inp = document.createElement("input");
        inp.type = "hidden";
        inp.dataset.type = "string";
        inp.dataset.key = String(i);
        inp.value = tool;
        pill.appendChild(inp);

        const txt = document.createElement("span");
        txt.textContent = tool;
        pill.appendChild(txt);

        if (!readonly) {
          const removeBtn = document.createElement("button");
          removeBtn.type = "button";
          removeBtn.className = "cfg-tool-remove";
          removeBtn.textContent = "\u00d7";
          removeBtn.addEventListener("click", () => {
            currentTools.splice(i, 1);
            rebuildToolPills();
          });
          pill.appendChild(removeBtn);
        }

        toolBody.appendChild(pill);
      });

      if (!readonly) {
        const addRow = document.createElement("div");
        addRow.className = "cfg-tool-add-row";
        const addInput = document.createElement("input");
        addInput.type = "text";
        addInput.className = "cfg-tool-add-input";
        addInput.placeholder = "Add tool (e.g. Bash)";
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "cfg-tool-add";
        addBtn.textContent = "+";
        addBtn.addEventListener("click", () => {
          const name = addInput.value.trim();
          if (!name || currentTools.includes(name)) { addInput.value = ""; return; }
          currentTools.push(name);
          addInput.value = "";
          rebuildToolPills();
        });
        addInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); addBtn.click(); }
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
  hiddenField("icon");

  // Fallback: any unknown keys get generic fields
  for (const [k, v] of Object.entries(data)) {
    if (!knownKeys.has(k)) {
      emit(renderJsonFormField(k, v, readonly, [k]));
    }
  }

  details.appendChild(body);
  container.appendChild(details);
}


function renderWorkgroupConfigForm(data, readonly, lockedKeys) {
  const container = qs("file-overlay-form");
  container.innerHTML = "";

  const wgName = data.name || "Workgroup";

  // Hero header with colored initial circle
  const hero = document.createElement("div");
  hero.className = "cfg-wg-hero";

  const icon = document.createElement("div");
  icon.className = "cfg-wg-icon";
  let hash = 0;
  for (let i = 0; i < wgName.length; i++) hash = wgName.charCodeAt(i) + ((hash << 5) - hash);
  icon.style.background = `hsl(${((hash % 360) + 360) % 360}, 55%, 48%)`;
  icon.textContent = wgName.charAt(0).toUpperCase();

  const heroText = document.createElement("div");
  heroText.className = "cfg-wg-hero-text";
  heroText.innerHTML = `<h3>${escapeHtml(wgName)}</h3>` +
    (data.service_description ? `<div class="meta">${escapeHtml(data.service_description)}</div>` : "");

  hero.appendChild(icon);
  hero.appendChild(heroText);
  container.appendChild(hero);

  // Stats strip
  const wgData = state.treeData[state.fileOverlayWorkgroupId];
  if (wgData) {
    const memberCount = (wgData.members || []).length;
    const agentCount = (wgData.agents || []).filter((a) => a.description !== "__system_admin_agent__").length;
    const fileCount = normalizeWorkgroupFiles(wgData.workgroup?.files).length;
    const jobCount = (wgData.jobs || []).filter((t) => t.kind === "job").length;

    const stats = document.createElement("div");
    stats.className = "cfg-wg-stats";
    [
      [memberCount, "Users"],
      [agentCount, "Agents"],
      [fileCount, "Files"],
      [jobCount, "Jobs"],
    ].forEach(([val, label]) => {
      const pill = document.createElement("div");
      pill.className = "cfg-wg-stat";
      pill.innerHTML = `<span class="cfg-wg-stat-value">${val}</span><span class="cfg-wg-stat-label">${label}</span>`;
      stats.appendChild(pill);
    });
    container.appendChild(stats);
  }

  // Root section (json-root for collectJsonFromForm compatibility)
  const details = document.createElement("details");
  details.className = "json-section json-root";
  details.open = true;
  details.dataset.key = "root";
  details.dataset.type = "object";

  const summary = document.createElement("summary");
  summary.className = "json-section-summary";
  summary.textContent = "root";
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "json-section-body";

  const knownKeys = new Set();
  const emit = (el) => { body.appendChild(el); };
  const field = (key, forceReadonly) => {
    knownKeys.add(key);
    if (!(key in data)) return;
    const ro = readonly || forceReadonly || (lockedKeys && lockedKeys.has(key));
    emit(renderJsonFormField(key, data[key], ro, [key]));
  };

  // Identity section
  emit(buildSectionDivider("Identity"));
  field("name");
  knownKeys.add("service_description");
  if ("service_description" in data) {
    const ro = readonly || (lockedKeys && lockedKeys.has("service_description"));
    emit(buildTextareaField("service_description", data.service_description, ro, "service_description"));
  }

  // Visibility section
  if ("is_discoverable" in data) {
    emit(buildSectionDivider("Visibility"));
    knownKeys.add("is_discoverable");
    emit(buildBooleanField("is_discoverable", data.is_discoverable, readonly, ["is_discoverable"]));
    const help = document.createElement("div");
    help.className = "cfg-wg-toggle-help";
    help.textContent = "Make this workgroup visible to other users for cross-group collaboration";
    emit(help);
  }

  // System section (collapsed details)
  knownKeys.add("id");
  knownKeys.add("owner_id");
  knownKeys.add("created_at");
  const sysDetails = document.createElement("details");
  sysDetails.className = "cfg-wg-system";
  const sysSummary = document.createElement("summary");
  sysSummary.className = "cfg-section-header";
  sysSummary.textContent = "System";
  sysDetails.appendChild(sysSummary);

  const sysBody = document.createElement("div");
  [["id", data.id], ["owner_id", data.owner_id], ["created_at", data.created_at]].forEach(([key, val]) => {
    if (val == null) return;
    const row = document.createElement("div");
    row.className = "cfg-wg-system-row";
    row.innerHTML = `<span class="cfg-wg-system-label">${escapeHtml(key)}</span><span>${escapeHtml(String(val))}</span>`;
    sysBody.appendChild(row);
    // Hidden input preserves value for save round-trip
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

function buildScalarField(key, type, value, readonly, path) {
  const label = document.createElement("label");
  label.className = "json-field" + (type === "null" ? " json-null" : "");

  const span = document.createElement("span");
  span.className = "json-field-label";
  span.textContent = key;
  span.title = key;

  const input = document.createElement("input");
  input.type = type === "number" ? "number" : "text";
  if (type === "number") input.step = "any";
  input.value = value;
  input.dataset.key = key;
  input.dataset.type = type;
  input.dataset.path = path.join(".");
  if (readonly || type === "null") input.disabled = true;

  label.appendChild(span);
  label.appendChild(input);
  return label;
}

function buildBooleanField(key, value, readonly, path) {
  const label = document.createElement("label");
  label.className = "json-field json-field-bool";

  const span = document.createElement("span");
  span.className = "json-field-label";
  span.textContent = key;
  span.title = key;

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = value;
  input.dataset.key = key;
  input.dataset.type = "boolean";
  input.dataset.path = path.join(".");
  if (readonly) input.disabled = true;

  label.appendChild(span);
  label.appendChild(input);
  return label;
}

function buildCollapsibleSection(key, value, readonly, path, isArray, lockedKeys) {
  const details = document.createElement("details");
  details.className = "json-section";
  details.open = true;
  details.dataset.key = key;
  details.dataset.type = isArray ? "array" : "object";
  details.dataset.path = path.join(".");

  const summary = document.createElement("summary");
  summary.className = "json-section-summary";
  const entries = isArray ? value.length : Object.keys(value).length;
  const typeLabel = isArray ? "items" : "keys";
  summary.textContent = `${key} (${entries} ${typeLabel})`;
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "json-section-body";

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

function buildSectionDivider(title) {
  const div = document.createElement("div");
  div.className = "cfg-section-header";
  div.textContent = title;
  return div;
}

function buildTextareaField(key, value, readonly, label) {
  const wrap = document.createElement("div");
  wrap.className = "cfg-field-wide";
  wrap.dataset.key = key;

  const span = document.createElement("span");
  span.className = "json-field-label";
  span.textContent = label || key;

  const ta = document.createElement("textarea");
  ta.dataset.type = "string";
  ta.dataset.key = key;
  ta.value = value ?? "";
  ta.rows = 3;
  if (readonly) ta.disabled = true;

  wrap.appendChild(span);
  wrap.appendChild(ta);
  return wrap;
}

function buildRangeField(key, value, readonly, min, max, step, label) {
  const wrap = document.createElement("div");
  wrap.className = "cfg-range-field";
  wrap.dataset.key = key;

  const span = document.createElement("span");
  span.className = "json-field-label";
  span.textContent = label || key;

  const row = document.createElement("div");
  row.className = "cfg-range-row";

  const input = document.createElement("input");
  input.type = "range";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value ?? min;
  input.dataset.type = "number";
  input.dataset.key = key;
  if (readonly) input.disabled = true;

  const valSpan = document.createElement("span");
  valSpan.className = "cfg-range-value";
  valSpan.textContent = value ?? min;

  input.oninput = () => { valSpan.textContent = input.value; };

  row.appendChild(input);
  row.appendChild(valSpan);
  wrap.appendChild(span);
  wrap.appendChild(row);
  return wrap;
}

function buildHiddenField(key, value) {
  const wrap = document.createElement("div");
  wrap.className = "cfg-hidden-field";
  wrap.dataset.key = key;

  const input = document.createElement("input");
  input.type = "hidden";
  input.dataset.type = "string";
  input.dataset.key = key;
  input.value = value ?? "";

  wrap.appendChild(input);
  return wrap;
}

function collectJsonFromForm() {
  const root = qs("file-overlay-form").querySelector(".json-section");
  if (!root) return null;
  return collectJsonValue(root);
}

function collectJsonValue(el) {
  if (el.classList.contains("json-section")) {
    const isArray = el.dataset.type === "array";
    const body = el.querySelector(":scope > .json-section-body");
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
        const key = child.dataset.key || child.querySelector("input,select")?.dataset.key;
        if (key !== undefined) {
          result[key] = collectJsonValue(child);
        }
      }
      return result;
    }
  }

  const input = el.querySelector("input, textarea") || el;
  const type = input.dataset.type;

  switch (type) {
    case "string":
      return input.value;
    case "number": {
      const n = Number(input.value);
      return isNaN(n) ? 0 : n;
    }
    case "boolean":
      return input.checked;
    case "null":
      return null;
    default:
      return input.value;
  }
}

async function saveJsonFormOverlay() {
  const data = collectJsonFromForm();
  if (data === null && !state.fileOverlayParsedJson) return;

  const workgroupId = state.fileOverlayWorkgroupId;
  const fileId = state.fileOverlayFileId;
  const treeData = state.treeData[workgroupId];
  if (!treeData) return;

  const content = JSON.stringify(data, null, 2);
  const files = normalizeWorkgroupFiles(treeData.workgroup?.files).map((item) =>
    item.id === fileId ? { ...item, content } : item,
  );

  try {
    await saveWorkgroupFiles(workgroupId, files);
    state.fileOverlayLastContent = content;
    qs("file-overlay-content").textContent = content;
    flash("File updated", "success");
  } catch (err) {
    flash(err.message || "Failed to save file", "error");
  }
}

function renderMarkdown(raw) {
  if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
    return DOMPurify.sanitize(marked.parse(raw));
  }
  return `<pre>${escapeHtml(raw)}</pre>`;
}

function setTextIfPresent(id, value) {
  const node = qs(id);
  if (node) {
    node.textContent = value;
  }
}

function resolveInitialTheme() {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "dark" || stored === "light") {
    return stored;
  }
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return prefersDark ? "dark" : "light";
}

let _savePrefsTimer = null;
function savePreferences(patch) {
  if (!state.user || !state.token) return;
  state.user.preferences = { ...(state.user.preferences || {}), ...patch };
  clearTimeout(_savePrefsTimer);
  _savePrefsTimer = setTimeout(async () => {
    try {
      const updated = await api("/api/auth/me/preferences", {
        method: "PATCH",
        body: { preferences: patch },
      });
      state.user = updated;
    } catch (e) {
      console.error("Failed to save preferences", e);
    }
  }, 400);
}

function isShowAgentThoughts() {
  return Boolean((state.user?.preferences || {}).showAgentThoughts);
}

async function loadThoughtsForMessages(messageIds) {
  if (!state.activeConversationId) return;
  const ids = messageIds || [];
  const idsParam = ids.length ? `?message_ids=${ids.join(",")}` : "";
  try {
    const data = await api(`/api/conversations/${state.activeConversationId}/thoughts${idsParam}`, { retries: 0, timeout: 8000 });
    Object.assign(state.thoughtsByMessageId, data);
  } catch (e) {
    console.error("Failed to load thoughts", e);
  }
}

function renderThoughtsSection(thoughts) {
  const lines = [];
  if (thoughts.intent) {
    lines.push(`<span><span class="thought-label">Intent:</span>${escapeHtml(thoughts.intent)}</span>`);
  }
  if (thoughts.urgency != null) {
    lines.push(`<span><span class="thought-label">Urgency:</span>${Math.round(thoughts.urgency * 100)}%</span>`);
  }
  if (thoughts.chain_step) {
    lines.push(`<span><span class="thought-label">Chain step:</span>${thoughts.chain_step}</span>`);
  }
  if (!lines.length) return "";
  return `<div class="agent-thoughts" onclick="this.classList.toggle('expanded')"><span class="agent-thoughts-toggle">agent reasoning</span><div class="agent-thoughts-content">${lines.join("")}</div></div>`;
}

function parseAsUTC(str) {
  if (!str) return new Date(NaN);
  // Server datetimes may lack timezone suffix; treat as UTC
  if (!/Z|[+-]\d{2}:\d{2}$/.test(str)) return new Date(str + "Z");
  return new Date(str);
}

function isConversationUnread(conversation) {
  if (!conversation.latest_message_at) {
    console.log(`[unread] ${conversation.topic}: no latest_message_at`);
    return false;
  }
  const prefs = (state.user && state.user.preferences) || {};
  const lastRead = prefs.conversationLastRead && prefs.conversationLastRead[conversation.id];
  if (!lastRead) {
    console.log(`[unread] ${conversation.topic}: never read → UNREAD`);
    return true;
  }
  const latest = parseAsUTC(conversation.latest_message_at);
  const read = parseAsUTC(lastRead);
  const isUnread = latest > read;
  console.log(`[unread] ${conversation.topic}: latest=${conversation.latest_message_at} lastRead=${lastRead} → ${isUnread ? "UNREAD" : "read"}`);
  return isUnread;
}

function workgroupHasUnread(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) return false;
  console.log("[unread] checking workgroup", workgroupId, "directs:", data.directs.length, "jobs:", data.jobs.length);
  if (data.jobs.some((c) => !c.is_archived && isConversationUnread(c))) return true;
  const userId = state.user?.id;
  for (const member of data.members) {
    if (member.user_id === userId) continue;
    const dm = directConversationForMember(workgroupId, member.user_id);
    if (dm && isConversationUnread(dm)) return true;
  }
  for (const agent of (data.agents || [])) {
    if (agent.description === "__system_admin_agent__") continue;
    const dm = directConversationForAgent(workgroupId, agent.id);
    if (dm && isConversationUnread(dm)) return true;
  }
  for (const tc of (data.taskConversations || [])) {
    if (isConversationUnread(tc)) return true;
  }
  return false;
}

function directConversationForMember(workgroupId, memberUserId) {
  const data = state.treeData[workgroupId];
  if (!data) return null;
  const result = data.directs.find((c) => {
    const parts = c.topic.split(":");
    return parts[0] === "dm" && parts.includes(memberUserId);
  }) || null;
  console.log("[unread] looking for DM with member", memberUserId, "found:", result?.topic);
  return result;
}

function directConversationForAgent(workgroupId, agentId) {
  const data = state.treeData[workgroupId];
  if (!data) return null;
  const userId = state.user?.id;
  if (!userId) return null;
  return data.directs.find((c) => c.topic === `dma:${userId}:${agentId}`) || null;
}

function applyTheme(theme, persist = true) {
  const normalized = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", normalized);
  const toggle = qs("theme-toggle");
  if (toggle) {
    toggle.checked = normalized === "dark";
  }
  if (persist) {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
    savePreferences({ theme: normalized });
  }
}

function flash(message, tone = "info") {
  const stack = qs("flash-stack");
  const notice = document.createElement("div");
  notice.className = `flash ${tone}`;
  notice.textContent = message;
  stack.appendChild(notice);

  setTimeout(() => {
    notice.style.opacity = "0";
    notice.style.transform = "translateX(10px)";
    setTimeout(() => notice.remove(), 180);
  }, 3200);
}

async function api(path, options = {}) {
  const maxRetries = options.retries ?? 2;
  const timeoutMs = options.timeout ?? 30000;
  const retryDelays = [200, 600, 1500];

  const headers = { ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  let body = options.body;
  if (body && typeof body === "object" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, retryDelays[attempt - 1] || 1500));
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(path, { ...options, headers, body, signal: controller.signal });
      clearTimeout(timer);

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const error = new Error(payload.detail || `Request failed: ${response.status}`);
        error.status = response.status;

        if (response.status === 401 && state.token) {
          signOut();
          flash("Session expired. Sign in again.", "info");
        }

        // Don't retry client errors (4xx)
        if (response.status >= 400 && response.status < 500) {
          throw error;
        }

        lastError = error;
        continue;
      }

      if (response.status === 204) {
        return null;
      }
      return response.json();
    } catch (err) {
      clearTimeout(timer);
      if (err.name === "AbortError") {
        lastError = new Error("Request timed out");
        lastError.status = 0;
      } else if (err.status >= 400 && err.status < 500) {
        throw err;
      } else {
        lastError = err;
      }
    }
  }

  throw lastError;
}

function updateAuthUI() {
  const online = Boolean(state.user && state.token);
  const statusText = online ? `Signed in as ${state.user.email}` : "Not authenticated";

  const statusNode = qs("auth-state");
  statusNode.textContent = statusText;
  statusNode.classList.toggle("online", online);
  statusNode.classList.toggle("hidden", online);

  setTextIfPresent("menu-user-label", online ? state.user.email : "");
  qs("menu-authenticated").classList.toggle("hidden", !online);
  qs("menu-login-controls").classList.toggle("hidden", online);

  const menuButton = qs("user-menu-button");
  if (online && state.user) {
    const firstName = (state.user.name || state.user.email || "").split(" ")[0] || "User";
    const avatarHtml = state.user.picture
      ? `<img class="menu-avatar" src="${escapeHtml(state.user.picture)}" alt="" />`
      : `<span class="menu-avatar-initials">${generateHumanSvg(state.user.name || state.user.email || "U")}</span>`;
    menuButton.innerHTML = `${avatarHtml}${escapeHtml(firstName)}`;
  } else {
    menuButton.textContent = "User";
  }

  qs("chat-panel").classList.toggle("hidden", !online);
  qs("empty-panel").classList.toggle("hidden", online);
}

function closeUserMenu() {
  qs("user-menu-dropdown").classList.add("hidden");
  qs("user-menu-button").setAttribute("aria-expanded", "false");
}

function toggleUserMenu() {
  const dropdown = qs("user-menu-dropdown");
  const nextHidden = !dropdown.classList.contains("hidden");
  dropdown.classList.toggle("hidden", nextHidden);
  qs("user-menu-button").setAttribute("aria-expanded", String(!nextHidden));
}

function updateMetrics() {
  setTextIfPresent("metric-workgroups", String(state.workgroups.length));

  const selected = state.treeData[state.selectedWorkgroupId];
  const conversationCount = selected ? selected.jobs.length + selected.directs.length : 0;
  setTextIfPresent("metric-conversations", String(conversationCount));

  setTextIfPresent("metric-messages", String(state.activeMessages.length));
}

function isWorkgroupOwner(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data || !state.user) {
    return false;
  }
  const self = data.members.find((member) => member.user_id === state.user.id);
  return self?.role === "owner";
}

function memberName(workgroupId, userId) {
  const data = state.treeData[workgroupId];
  const member = data?.members.find((item) => item.user_id === userId);
  if (!member) {
    return userId?.slice(0, 8) || "unknown";
  }
  return member.name || member.email;
}


function agentName(workgroupId, agentId) {
  const data = state.treeData[workgroupId];
  const agent = data?.agents?.find((item) => item.id === agentId);
  if (!agent) {
    return agentId?.slice(0, 8) || "agent";
  }
  return agent.name || agent.id.slice(0, 8);
}

function senderLabel(workgroupId, message) {
  if (message.sender_type === "user") {
    if (state.user && message.sender_user_id === state.user.id) {
      return "You";
    }
    return memberName(workgroupId, message.sender_user_id);
  }

  if (message.sender_agent_id) {
    return agentName(workgroupId, message.sender_agent_id);
  }

  if (message.sender_type === "system") {
    return "System";
  }

  return "Agent";
}

function initialsFromName(name) {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((item) => item[0])
    .join("")
    .toUpperCase() || "?";
}

const AVATAR_COLORS = [
  "#e8384f", "#fd612c", "#fd9a00", "#eec300",
  "#a4cf30", "#62b847", "#37c5ab", "#20aaea",
  "#4186e0", "#7a6ff0", "#aa62e3", "#e362e3",
  "#ea4e9d", "#fc91ad", "#8da3a6", "#6d6e72",
];

function hashCode(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function avatarColor(name) {
  return AVATAR_COLORS[hashCode(name) % AVATAR_COLORS.length];
}

function generateBotSvg(name) {
  const color = avatarColor(name);
  const h = hashCode(name);
  const antennaStyle = h % 3;
  const eyeStyle = (h >> 2) % 3;
  const mouthStyle = (h >> 4) % 3;

  let antenna = "";
  if (antennaStyle === 0) {
    antenna = `<line x1="16" y1="6" x2="16" y2="2" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><circle cx="16" cy="1.5" r="1.5" fill="#fff"/>`;
  } else if (antennaStyle === 1) {
    antenna = `<line x1="16" y1="6" x2="16" y2="2.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><line x1="13.5" y1="2.5" x2="18.5" y2="2.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>`;
  }

  let eyes = "";
  if (eyeStyle === 0) {
    eyes = `<circle cx="12" cy="16" r="2" fill="${color}"/><circle cx="20" cy="16" r="2" fill="${color}"/>`;
  } else if (eyeStyle === 1) {
    eyes = `<rect x="10" y="14" width="4" height="4" rx="0.5" fill="${color}"/><rect x="18" y="14" width="4" height="4" rx="0.5" fill="${color}"/>`;
  } else {
    eyes = `<rect x="10" y="15" width="4" height="2" rx="1" fill="${color}"/><rect x="18" y="15" width="4" height="2" rx="1" fill="${color}"/>`;
  }

  let mouth = "";
  if (mouthStyle === 0) {
    mouth = `<rect x="13" y="21" width="6" height="1.5" rx="0.75" fill="${color}"/>`;
  } else if (mouthStyle === 1) {
    mouth = `<path d="M13 21 Q16 24 19 21" stroke="${color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;
  } else {
    mouth = `<rect x="13.5" y="20.5" width="5" height="2.5" rx="1.25" fill="${color}"/>`;
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${antenna}<rect x="3" y="6" width="26" height="24" rx="6" fill="${color}"/><rect x="7" y="10" width="18" height="16" rx="4" fill="#fff"/>${eyes}${mouth}</svg>`;
}

function generateHumanSvg(name) {
  const color = avatarColor(name);
  const initials = initialsFromName(name);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="${color}"/><text x="16" y="16" text-anchor="middle" dominant-baseline="central" fill="#fff" font-family="sans-serif" font-weight="700" font-size="12">${escapeHtml(initials)}</text></svg>`;
}

function senderInitials(workgroupId, message) {
  if (message.sender_type === "agent") {
    return "AI";
  }
  const label = senderLabel(workgroupId, message);
  return initialsFromName(label);
}

function renderAvatarHtml(name, pictureUrl, cssClass) {
  if (pictureUrl) {
    return `<img class="${cssClass}" src="${escapeHtml(pictureUrl)}" alt="" />`;
  }
  const initials = initialsFromName(name);
  return `<span class="${cssClass} avatar-initials">${escapeHtml(initials)}</span>`;
}

function isActiveConversationArchived() {
  if (!state.selectedWorkgroupId || !state.activeConversationId) return false;
  const data = state.treeData[state.selectedWorkgroupId];
  if (!data) return false;
  const conv = data.jobs.find((c) => c.id === state.activeConversationId)
    || data.directs.find((c) => c.id === state.activeConversationId);
  return conv?.is_archived === true;
}

function jobDisplayName(conversation) {
  const explicit = (conversation?.name || "").trim();
  if (explicit) {
    return explicit;
  }
  const fallback = (conversation?.topic || "").trim();
  return fallback || "job";
}

function normalizeWorkgroupFiles(files) {
  if (!Array.isArray(files)) {
    return [];
  }

  const normalized = [];
  const seenIds = new Set();
  for (const item of files) {
    let id = "";
    let path = "";
    let content = "";

    if (typeof item === "string") {
      path = item.trim();
    } else if (item && typeof item === "object") {
      id = String(item.id || "").trim();
      path = String(item.path || "").trim();
      content = typeof item.content === "string" ? item.content : String(item.content || "");
    }

    if (!path) {
      continue;
    }

    if (!id) {
      id = `legacy:${path}`;
    }

    if (seenIds.has(id)) {
      let suffix = 2;
      while (seenIds.has(`${id}:${suffix}`)) {
        suffix += 1;
      }
      id = `${id}:${suffix}`;
    }

    const topic_id = (item && typeof item === "object") ? String(item.topic_id || "") : "";

    seenIds.add(id);
    normalized.push({ id, path, content, topic_id });
  }
  return normalized;
}

function topicIdForConversation(conversation) {
  if (!conversation) return "";
  if (conversation.kind === "job") return conversation.id;
  if (conversation.kind === "direct" && conversation.topic) {
    if (conversation.topic.startsWith("dma:")) {
      const parts = conversation.topic.split(":");
      if (parts.length >= 3) return `agent:${parts[2]}`;
    }
    if (conversation.topic.startsWith("dm:")) {
      return conversation.topic;
    }
  }
  return "";
}

function filesForConversationContext(files, workgroupId) {
  const conversationId = state.activeConversationId;
  if (!conversationId || !workgroupId) return files;
  const conversation = conversationById(workgroupId, conversationId);
  if (!conversation || conversation.kind === "admin") return files;
  const scopeId = topicIdForConversation(conversation);
  if (conversation.kind === "direct" && scopeId) {
    return files.filter(f => f.topic_id === scopeId);
  }
  if (scopeId) {
    return files.filter(f => !f.topic_id || f.topic_id === scopeId);
  }
  return files.filter(f => !f.topic_id);
}

function normalizePathEntry(value) {
  return value
    .replaceAll("\\", "/")
    .replace(/\/+/g, "/")
    .replace(/^\/+/, "")
    .replace(/\/+$/, "");
}

function urlLabel(value) {
  try {
    const parsed = new URL(value);
    const parts = parsed.pathname.split("/").filter(Boolean);
    const leaf = parts.length ? parts[parts.length - 1] : "";
    return leaf ? `${parsed.hostname}/${leaf}` : parsed.hostname;
  } catch {
    return value;
  }
}

function buildWorkgroupFileTree(fileEntries) {
  const root = { folders: new Map(), files: [] };

  for (const file of fileEntries) {
    if (/^https?:\/\//i.test(file.path)) {
      root.files.push({
        id: file.id,
        name: urlLabel(file.path),
        path: file.path,
        content: file.content,
        isLink: true,
      });
      continue;
    }

    const normalized = normalizePathEntry(file.path);
    if (!normalized) {
      continue;
    }

    const parts = normalized.split("/").filter(Boolean);
    if (!parts.length) {
      continue;
    }

    let node = root;
    for (let index = 0; index < parts.length - 1; index += 1) {
      const folderName = parts[index];
      if (!node.folders.has(folderName)) {
        node.folders.set(folderName, { folders: new Map(), files: [] });
      }
      node = node.folders.get(folderName);
    }

    const filename = parts[parts.length - 1];
    node.files.push({
      id: file.id,
      name: filename,
      path: normalized,
      content: file.content,
      isLink: false,
    });
  }

  return root;
}

function renderWorkgroupFileTreeNode(node, workgroupId, selectedFileId, depth = 0, parentPath = "", isOwner = false) {
  const folderHtml = Array.from(node.folders.entries())
    .sort((left, right) => left[0].localeCompare(right[0], undefined, { sensitivity: "base" }))
    .map(([folderName, folderNode]) => {
      const expanded = depth < 1 ? " open" : "";
      const folderPath = parentPath ? parentPath + "/" + folderName : folderName;
      const folderDeleteBtn = isOwner
        ? `<button class="folder-delete-btn" data-action="folder-delete"
            data-workgroup="${escapeHtml(workgroupId)}"
            data-folder-path="${escapeHtml(folderPath)}"
            title="Delete folder and contents">&times;</button>`
        : "";
      return `
        <details class="workgroup-folder"${expanded}>
          <summary>
            <span class="finder-folder-label">
              <span class="finder-disclosure" aria-hidden="true"></span>
              <span class="finder-icon folder">${FINDER_FOLDER_ICON_SVG}</span>
              <span class="workgroup-folder-name">${escapeHtml(folderName)}</span>
            </span>
            <span class="finder-kind">Folder</span>
            ${folderDeleteBtn}
          </summary>
          <div class="workgroup-folder-children">${renderWorkgroupFileTreeNode(
            folderNode,
            workgroupId,
            selectedFileId,
            depth + 1,
            folderPath,
            isOwner,
          )}</div>
        </details>
      `;
    })
    .join("");

  const fileHtml = node.files
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }))
    .map((entry) => {
      const activeClass = entry.id === selectedFileId ? "active" : "";
      const fileKind = entry.isLink ? "Link" : "File";
      const fileIcon = entry.isLink ? FINDER_LINK_ICON_SVG : FINDER_FILE_ICON_SVG;
      const iconClass = entry.isLink ? "link" : "file";
      const selectButton = `
        <button
          class="tree-button file ${activeClass}"
          data-action="select-file"
          data-workgroup="${escapeHtml(workgroupId)}"
          data-file-id="${escapeHtml(entry.id)}"
          title="${escapeHtml(entry.path)}"
        >
          <span class="finder-file-label">
            <span class="finder-icon ${iconClass}">${fileIcon}</span>
            <span class="finder-file-name">${escapeHtml(entry.name)}</span>
          </span>
          <span class="finder-kind">${fileKind}</span>
        </button>
      `;
      if (entry.isLink) {
        return `
          <div class="tree-item-row workgroup-file-item">
            ${selectButton}
            <a class="workgroup-file-link" href="${escapeHtml(entry.path)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${escapeHtml(entry.name)}">↗</a>
          </div>
        `;
      }
      return `
        <div class="tree-item-row workgroup-file-item">
          ${selectButton}
        </div>
      `;
    })
    .join("");

  return folderHtml + fileHtml;
}

function selectedWorkgroupFile(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return null;
  }
  const fileId = state.selectedWorkgroupFileIdByWorkgroup[workgroupId];
  if (!fileId) {
    return null;
  }
  return normalizeWorkgroupFiles(data.workgroup?.files).find((item) => item.id === fileId) || null;
}

function updateFileSelection(workgroupId, fileId) {
  const workgroupDetails = document.querySelector(`.tree-workgroup[data-workgroup="${workgroupId}"]`);
  if (!workgroupDetails) {
    return;
  }

  workgroupDetails.querySelectorAll('.tree-button.file.active').forEach((btn) => btn.classList.remove('active'));
  const target = workgroupDetails.querySelector(`.tree-button.file[data-file-id="${fileId}"]`);
  if (target) {
    target.classList.add('active');
  }

  const selected = selectedWorkgroupFile(workgroupId);
  const canManage = isWorkgroupOwner(workgroupId);
  const canEdit = canManage && Boolean(fileId);
  workgroupDetails.querySelectorAll('[data-action="file-edit"], [data-action="file-rename"]').forEach((btn) => {
    btn.disabled = !canEdit;
  });
  workgroupDetails.querySelectorAll('[data-action="file-delete"]').forEach((btn) => {
    btn.disabled = !canEdit;
  });

  const files = normalizeWorkgroupFiles(state.treeData[workgroupId]?.workgroup?.files);
  const countLabel = `${files.length} item${files.length === 1 ? "" : "s"}`;
  const statusText = selected ? `Selected: ${selected.path}` : countLabel;
  const statusEl = workgroupDetails.querySelector('.finder-status');
  if (statusEl) {
    statusEl.textContent = statusText;
    statusEl.title = statusText;
  }
}

function showOverlaySplit() {
  const chatPanel = document.getElementById("chat-panel");
  document.getElementById("file-overlay-resize-handle").classList.remove("hidden");
  chatPanel.classList.add("overlay-split");
  const prefs = (state.user && state.user.preferences) || {};
  if (prefs.overlayHeight) {
    chatPanel.style.setProperty("--overlay-height", prefs.overlayHeight + "px");
  }
}

function hideOverlaySplit() {
  document.getElementById("file-overlay-resize-handle").classList.add("hidden");
  document.getElementById("chat-panel").classList.remove("overlay-split");
}

function openFileOverlay(workgroupId, fileId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return;
  }
  const files = normalizeWorkgroupFiles(data.workgroup?.files);
  const file = files.find((item) => item.id === fileId);
  if (!file) {
    return;
  }

  qs("file-overlay-path").textContent = file.path;
  qs("file-overlay-workgroup").textContent = data.workgroup.name;

  const pre = qs("file-overlay-content");
  const rendered = qs("file-overlay-rendered");
  const rawToggle = qs("file-overlay-raw-toggle");

  pre.textContent = file.content;
  state.fileOverlayShowRaw = false;
  state.fileOverlayLastContent = file.content;

  const form = qs("file-overlay-form");
  const isOwner = isWorkgroupOwner(workgroupId);

  if (isJsonFile(file.path)) {
    const parsed = tryParseJson(file.content);
    state.fileOverlayParsedJson = parsed.ok ? parsed.data : null;

    if (parsed.ok) {
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      if (isAgentConfigPath(file.path) && isAgentConfigShape(parsed.data)) {
        renderAgentConfigForm(parsed.data, !isOwner);
      } else if (isToolsManifestPath(file.path) && isToolsManifestShape(parsed.data)) {
        renderToolsManifestForm(parsed.data, !isOwner);
      } else if (isWorkgroupConfigPath(file.path)) {
        renderWorkgroupConfigForm(parsed.data, !isOwner, new Set(["id", "owner_id", "created_at"]));
      } else {
        const lockedKeys = file.path.endsWith("workgroup.json")
          ? new Set(["id", "owner_id", "created_at"])
          : null;
        renderJsonForm(parsed.data, !isOwner, lockedKeys);
      }
      rawToggle.classList.remove("hidden");
      setFileOverlayViewMode("form");
      updateFileOverlayEditButton(isOwner, true, true);
    } else {
      form.innerHTML = "";
      form.classList.add("hidden");
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      pre.classList.remove("hidden");
      rawToggle.classList.add("hidden");
      state.fileOverlayViewMode = "raw";
      state.fileOverlayParsedJson = null;
      const editBtn = qs("file-overlay-edit");
      editBtn.textContent = "Edit";
      editBtn.classList.toggle("hidden", !isOwner);
    }
  } else if (isMarkdownFile(file.path)) {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    state.fileOverlayViewMode = "raw";
    pre.classList.add("hidden");
    rendered.innerHTML = renderMarkdown(file.content);
    rendered.classList.remove("hidden");
    rawToggle.textContent = "Raw";
    rawToggle.classList.remove("hidden");
    const editBtn = qs("file-overlay-edit");
    editBtn.textContent = "Edit";
    editBtn.classList.toggle("hidden", !isOwner);
  } else if (isImageFile(file.path) || isDataUrl(file.content)) {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    state.fileOverlayViewMode = "raw";
    pre.classList.add("hidden");
    const src = isDataUrl(file.content) ? escapeHtml(file.content) : escapeHtml(file.content);
    rendered.innerHTML = `<img src="${src}" alt="${escapeHtml(file.path)}" class="file-overlay-image" />`;
    rendered.classList.remove("hidden");
    rawToggle.classList.add("hidden");
    qs("file-overlay-edit").classList.add("hidden");
  } else {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    state.fileOverlayViewMode = "raw";
    pre.classList.remove("hidden");
    rendered.innerHTML = "";
    rendered.classList.add("hidden");
    rawToggle.classList.add("hidden");
    const editBtn = qs("file-overlay-edit");
    editBtn.textContent = "Edit";
    editBtn.classList.toggle("hidden", !isOwner);
  }

  qs("file-overlay-delete").classList.toggle("hidden", !isOwner);

  qs("file-overlay").classList.remove("hidden");
  showOverlaySplit();
  state.fileOverlayOpen = true;
  state.fileOverlayWorkgroupId = workgroupId;
  state.fileOverlayFileId = fileId;

  const ctxBar = qs("composer-file-context");
  ctxBar.innerHTML = `<span>Attached: <strong>${escapeHtml(file.path)}</strong></span><button type="button" class="icon-button" data-action="clear-file-context">\u00d7</button>`;
  ctxBar.classList.remove("hidden");
}

function openConfigOverlay(workgroupId, label, data) {
  qs("file-overlay-path").textContent = label;
  const wgData = state.treeData[workgroupId];
  qs("file-overlay-workgroup").textContent = wgData?.workgroup?.name || "";

  const jsonStr = JSON.stringify(data, null, 2);
  const pre = qs("file-overlay-content");
  const rendered = qs("file-overlay-rendered");
  const rawToggle = qs("file-overlay-raw-toggle");
  const form = qs("file-overlay-form");
  const editBtn = qs("file-overlay-edit");

  pre.textContent = jsonStr;
  state.fileOverlayShowRaw = false;
  state.fileOverlayLastContent = jsonStr;
  state.fileOverlayParsedJson = data;

  rendered.innerHTML = "";
  rendered.classList.add("hidden");
  renderJsonForm(data, true);
  rawToggle.classList.remove("hidden");
  setFileOverlayViewMode("form");
  editBtn.classList.add("hidden");
  qs("file-overlay-delete").classList.add("hidden");

  qs("file-overlay").classList.remove("hidden");
  showOverlaySplit();
  state.fileOverlayOpen = true;
  state.fileOverlayWorkgroupId = workgroupId;
  state.fileOverlayFileId = "";

  const ctxBar = qs("composer-file-context");
  ctxBar.innerHTML = `<span>Viewing: <strong>${escapeHtml(label)}</strong></span><button type="button" class="icon-button" data-action="clear-file-context">\u00d7</button>`;
  ctxBar.classList.remove("hidden");
}

async function openConfigAndAdmin(workgroupId, label, configData) {
  const wgData = state.treeData[workgroupId];
  if (wgData) {
    const admin = wgData.jobs.find((c) => c.kind === "admin");
    if (admin) {
      await selectConversation(workgroupId, admin.id, `job:${workgroupId}:${admin.id}`);
    }
  }
  openConfigOverlay(workgroupId, label, configData);
}

function closeFileOverlay() {
  document.querySelector(".cfg-tool-picker-backdrop")?.remove();
  qs("file-overlay").classList.add("hidden");
  hideOverlaySplit();
  state.fileOverlayOpen = false;
  state.fileOverlayShowRaw = false;
  state.fileOverlayViewMode = "raw";
  state.fileOverlayParsedJson = null;
  state.fileOverlayLastContent = "";
  state.fileOverlayMemberContext = null;

  state.fileBrowserOpen = false;
  state.fileBrowserWorkgroupId = "";
  state.fileBrowserPath = [];
  state.fileBrowserFileId = "";
  state.fileBrowserScope = "";
  state.fileBrowserOrgId = "";
  state.fileBrowserCompositeFiles = [];

  const rendered = qs("file-overlay-rendered");
  rendered.innerHTML = "";
  rendered.classList.add("hidden");

  const form = qs("file-overlay-form");
  form.innerHTML = "";
  form.classList.add("hidden");

  const listing = qs("file-browser-listing");
  listing.innerHTML = "";
  listing.classList.add("hidden");

  const editBtn = qs("file-overlay-edit");
  editBtn.textContent = "Edit";

  qs("file-overlay-delete").classList.add("hidden");

  qs("file-overlay-content").classList.remove("hidden");
  qs("file-overlay-raw-toggle").classList.add("hidden");

  // Restore title elements that renderFileBrowser may have hidden
  qs("file-overlay-path").classList.remove("hidden");
  qs("file-overlay-workgroup").classList.remove("hidden");
  const breadcrumbWrap = qs("file-browser-breadcrumb");
  breadcrumbWrap.innerHTML = "";
  breadcrumbWrap.classList.add("hidden");

  qs("composer-file-context").classList.add("hidden");
}

function fileBrowserSlug(name) {
  return String(name || "").replace(/[/\\]/g, "_").replace(/\.\./g, "_");
}

function _buildCompositeWorkgroupFiles(wg, wgPrefix) {
  const files = [];
  files.push({
    id: `virtual-wg:${wg.id}`,
    path: `${wgPrefix}/workgroup.json`,
    content: JSON.stringify({ id: wg.id, name: wg.name, organization_id: wg.organization_id || "" }, null, 2),
    _source: "virtual-wg",
    _sourceWorkgroupId: wg.id,
  });

  const data = state.treeData[wg.id];
  if (data?.agents) {
    for (const agent of data.agents) {
      const agentSlug = fileBrowserSlug(agent.name).replace(/\s+/g, "_").toLowerCase();
      files.push({
        id: `virtual-agent:${agent.id}`,
        path: `${wgPrefix}/agents/${agentSlug}.json`,
        content: JSON.stringify({ id: agent.id, name: agent.name, role: agent.role || "" }, null, 2),
        _source: "virtual-agent",
        _sourceWorkgroupId: wg.id,
        _agentId: agent.id,
      });
    }
  }

  const wgFiles = normalizeWorkgroupFiles(data?.workgroup?.files);
  for (const f of wgFiles) {
    if (f.path.startsWith(".templates/")) continue;
    if (f.path === "workgroup.json") continue;
    if (f.path.startsWith("agents/") && f.path.endsWith(".json")) continue;
    if (f.path === "tools.json") continue;
    files.push({
      ...f,
      path: `${wgPrefix}/files/${f.path}`,
      _source: "workgroup-file",
      _sourceWorkgroupId: wg.id,
      _originalPath: f.path,
    });
  }
  return files;
}

function buildCompositeFilesForRoot() {
  const files = [];
  const adminWg = state.workgroups.find(w => w.name === "Administration" && !w.organization_id);

  // Admin workgroup's .templates/ files
  if (adminWg) {
    const data = state.treeData[adminWg.id];
    const wgFiles = normalizeWorkgroupFiles(data?.workgroup?.files);
    for (const f of wgFiles) {
      if (f.path.startsWith(".templates/")) {
        files.push({ ...f, _source: "admin", _sourceWorkgroupId: adminWg.id });
      }
    }
  }

  // Organization data
  for (const org of state.organizations) {
    const orgSlug = fileBrowserSlug(org.name);
    const orgPrefix = `organizations/${orgSlug}`;

    files.push({
      id: `virtual-org:${org.id}`,
      path: `${orgPrefix}/organization.json`,
      content: JSON.stringify({ id: org.id, name: org.name, description: org.description || "" }, null, 2),
      _source: "virtual-org",
      _orgId: org.id,
    });

    const orgWorkgroups = state.workgroups.filter(w => w.organization_id === org.id && w.name !== "Administration");
    for (const wg of orgWorkgroups) {
      const wgPrefix = `${orgPrefix}/workgroups/${fileBrowserSlug(wg.name)}`;
      files.push(..._buildCompositeWorkgroupFiles(wg, wgPrefix));
    }
  }

  // Ungrouped workgroups
  const ungrouped = state.workgroups.filter(w => !w.organization_id && w.name !== "Administration");
  for (const wg of ungrouped) {
    const wgPrefix = `workgroups/${fileBrowserSlug(wg.name)}`;
    files.push(..._buildCompositeWorkgroupFiles(wg, wgPrefix));
  }

  return files;
}

function buildCompositeFilesForOrg(orgId) {
  const org = state.organizations.find(o => o.id === orgId);
  if (!org) return [];

  const files = [];

  files.push({
    id: `virtual-org:${org.id}`,
    path: "organization.json",
    content: JSON.stringify({ id: org.id, name: org.name, description: org.description || "" }, null, 2),
    _source: "virtual-org",
    _orgId: org.id,
  });

  const orgWorkgroups = state.workgroups.filter(w => w.organization_id === org.id && w.name !== "Administration");
  for (const wg of orgWorkgroups) {
    const wgPrefix = `workgroups/${fileBrowserSlug(wg.name)}`;
    files.push(..._buildCompositeWorkgroupFiles(wg, wgPrefix));
  }

  return files;
}

function openFileBrowser(workgroupId, pathSegments = [], scope = "", orgId = "") {
  if (scope === "root") {
    state.fileBrowserOpen = true;
    state.fileBrowserWorkgroupId = "";
    state.fileBrowserPath = pathSegments;
    state.fileBrowserFileId = "";
    state.fileBrowserScope = "root";
    state.fileBrowserOrgId = "";
    state.fileBrowserCompositeFiles = buildCompositeFilesForRoot();
    state.fileOverlayOpen = false;
    state.fileOverlayParsedJson = null;
    renderFileBrowser();
    return;
  }

  if (scope === "org" && orgId) {
    state.fileBrowserOpen = true;
    state.fileBrowserWorkgroupId = "";
    state.fileBrowserPath = pathSegments;
    state.fileBrowserFileId = "";
    state.fileBrowserScope = "org";
    state.fileBrowserOrgId = orgId;
    state.fileBrowserCompositeFiles = buildCompositeFilesForOrg(orgId);
    state.fileOverlayOpen = false;
    state.fileOverlayParsedJson = null;
    renderFileBrowser();
    return;
  }

  const data = state.treeData[workgroupId];
  if (!data) return;

  state.fileBrowserOpen = true;
  state.fileBrowserWorkgroupId = workgroupId;
  state.fileBrowserPath = pathSegments;
  state.fileBrowserFileId = "";
  state.fileBrowserScope = "";
  state.fileBrowserOrgId = "";
  state.fileBrowserCompositeFiles = [];

  state.fileOverlayOpen = false;
  state.fileOverlayParsedJson = null;

  renderFileBrowser();
}

function renderFileBrowserBreadcrumbs() {
  const isComposite = state.fileBrowserScope === "root" || state.fileBrowserScope === "org";
  let rootLabel = "Files";
  if (state.fileBrowserScope === "org") {
    const org = state.organizations.find(o => o.id === state.fileBrowserOrgId);
    rootLabel = org?.name || "Organization";
  } else if (!isComposite) {
    rootLabel = fileBrowserContextLabel(state.fileBrowserWorkgroupId);
  }

  const parts = [];

  // Root crumb
  if (state.fileBrowserPath.length > 0 || state.fileBrowserFileId) {
    parts.push(`<button class="file-browser-crumb" data-action="browser-navigate" data-depth="0">${escapeHtml(rootLabel)}</button>`);
  } else {
    parts.push(`<span class="file-browser-crumb-current">${escapeHtml(rootLabel)}</span>`);
  }

  // Path segments
  for (let i = 0; i < state.fileBrowserPath.length; i++) {
    parts.push(`<span class="file-browser-sep">\u203A</span>`);
    const isLast = i === state.fileBrowserPath.length - 1 && !state.fileBrowserFileId;
    if (isLast) {
      parts.push(`<span class="file-browser-crumb-current">${escapeHtml(state.fileBrowserPath[i])}</span>`);
    } else {
      parts.push(`<button class="file-browser-crumb" data-action="browser-navigate" data-depth="${i + 1}">${escapeHtml(state.fileBrowserPath[i])}</button>`);
    }
  }

  // File name breadcrumb
  if (state.fileBrowserFileId) {
    const allFiles = isComposite
      ? state.fileBrowserCompositeFiles
      : filesForConversationContext(normalizeWorkgroupFiles(state.treeData[state.fileBrowserWorkgroupId]?.workgroup?.files), state.fileBrowserWorkgroupId);
    const file = allFiles.find((f) => f.id === state.fileBrowserFileId);
    if (file) {
      const fileName = file.path.split("/").pop() || file.path;
      parts.push(`<span class="file-browser-sep">\u203A</span>`);
      parts.push(`<span class="file-browser-crumb-current">${escapeHtml(fileName)}</span>`);
    }
  }

  return `<div class="file-browser-breadcrumbs">${parts.join("")}</div>`;
}

function renderFileBrowserListing(node, isOwner) {
  const isComposite = state.fileBrowserScope === "root" || state.fileBrowserScope === "org";
  const folders = Array.from(node.folders.entries())
    .sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: "base" }));
  const files = [...node.files]
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));

  let html = "";

  // In composite mode, only show toolbar inside .templates/ paths targeting admin wg
  if (isOwner && !isComposite) {
    html += `<div class="file-browser-toolbar">
      <button type="button" class="file-browser-toolbar-btn" data-action="browser-add-file">+ File</button>
      <button type="button" class="file-browser-toolbar-btn" data-action="browser-new-folder">+ Folder</button>
    </div>`;
  } else if (isOwner && isComposite) {
    const currentPath = state.fileBrowserPath.join("/");
    if (currentPath.startsWith(".templates")) {
      html += `<div class="file-browser-toolbar">
        <button type="button" class="file-browser-toolbar-btn" data-action="browser-add-file">+ File</button>
        <button type="button" class="file-browser-toolbar-btn" data-action="browser-new-folder">+ Folder</button>
      </div>`;
    }
  }

  if (!folders.length && !files.length) {
    return html + `<div class="finder-empty">Empty folder</div>`;
  }

  for (const [folderName, folderNode] of folders) {
    const childCount = folderNode.folders.size + folderNode.files.length;
    const itemLabel = childCount + " item" + (childCount !== 1 ? "s" : "");
    const fullPath = [...state.fileBrowserPath, folderName].join("/");
    const actions = (isOwner && !isComposite) ? `<span class="file-browser-actions">
      <button type="button" data-action="browser-rename-folder" data-folder-path="${escapeHtml(fullPath)}">Rename</button>
      <button type="button" data-action="browser-copy-folder" data-folder-path="${escapeHtml(fullPath)}">Copy</button>
      <button type="button" data-action="browser-delete-folder" data-folder-path="${escapeHtml(fullPath)}">Delete</button>
    </span>` : "";
    html += `<div class="file-browser-row">
      <button class="file-browser-item" data-action="browser-drill" data-folder="${escapeHtml(folderName)}">
        <span class="finder-icon folder">${FINDER_FOLDER_ICON_SVG}</span>
        <span class="file-browser-name">${escapeHtml(folderName)}</span>
        <span class="file-browser-meta">${itemLabel}</span>
      </button>
      ${actions}
    </div>`;
  }

  for (const file of files) {
    const iconClass = file.isLink ? "link" : "file";
    const iconSvg = file.isLink ? FINDER_LINK_ICON_SVG : FINDER_FILE_ICON_SVG;
    const isVirtual = file._source && file._source.startsWith("virtual-");
    const actions = (isOwner && !isVirtual && !isComposite) ? `<span class="file-browser-actions">
      <button type="button" data-action="browser-rename-file" data-file-id="${escapeHtml(file.id)}">Rename</button>
      <button type="button" data-action="browser-copy-file" data-file-id="${escapeHtml(file.id)}">Copy</button>
      <button type="button" data-action="browser-delete-file" data-file-id="${escapeHtml(file.id)}">Delete</button>
    </span>` : "";
    const wgAttr = state.fileBrowserWorkgroupId || (file._sourceWorkgroupId || "");
    html += `<div class="file-browser-row">
      <button class="file-browser-item" data-action="browser-open-file" data-file-id="${escapeHtml(file.id)}" data-workgroup="${escapeHtml(wgAttr)}">
        <span class="finder-icon ${iconClass}">${iconSvg}</span>
        <span class="file-browser-name">${escapeHtml(file.name)}</span>
        <span class="file-browser-meta">File</span>
      </button>
      ${actions}
    </div>`;
  }

  return html;
}

function renderFileBrowser() {
  const isComposite = state.fileBrowserScope === "root" || state.fileBrowserScope === "org";
  const data = state.treeData[state.fileBrowserWorkgroupId];
  if (!isComposite && !data) return;

  const overlay = qs("file-overlay");
  const listing = qs("file-browser-listing");
  const pre = qs("file-overlay-content");
  const rendered = qs("file-overlay-rendered");
  const form = qs("file-overlay-form");

  // Show breadcrumbs, hide normal title elements
  qs("file-overlay-path").classList.add("hidden");
  qs("file-overlay-workgroup").classList.add("hidden");
  const breadcrumbEl = qs("file-browser-breadcrumb");
  breadcrumbEl.innerHTML = renderFileBrowserBreadcrumbs();
  breadcrumbEl.classList.remove("hidden");

  if (state.fileBrowserFileId) {
    // Viewing a file within the browser
    listing.innerHTML = "";
    listing.classList.add("hidden");

    // Resolve the file from composite or workgroup files
    let file = null;
    if (isComposite) {
      file = state.fileBrowserCompositeFiles.find((f) => f.id === state.fileBrowserFileId);
    } else {
      const files = filesForConversationContext(normalizeWorkgroupFiles(data.workgroup?.files), state.fileBrowserWorkgroupId);
      file = files.find((f) => f.id === state.fileBrowserFileId);
    }
    if (!file) return;

    // For composite virtual files, route to appropriate UI
    if (isComposite && file._source) {
      if (file._source === "virtual-org" && file._orgId) {
        openOrgSettingsModal(file._orgId);
        state.fileBrowserFileId = "";
        renderFileBrowser();
        return;
      }
      if (file._source === "virtual-wg" && file._sourceWorkgroupId) {
        const wgData = state.treeData[file._sourceWorkgroupId];
        if (wgData) {
          state.fileBrowserFileId = "";
          // Navigate to workgroup-scoped browser
          openFileBrowser(file._sourceWorkgroupId);
          return;
        }
      }
      if (file._source === "virtual-agent" && file._sourceWorkgroupId && file._agentId) {
        openAgentSettings(file._sourceWorkgroupId, file._agentId);
        state.fileBrowserFileId = "";
        renderFileBrowser();
        return;
      }
    }

    // Set file overlay state so edit/delete handlers work
    state.fileOverlayOpen = true;
    const effectiveWgId = file._sourceWorkgroupId || state.fileBrowserWorkgroupId;
    state.fileOverlayWorkgroupId = effectiveWgId;
    state.fileOverlayFileId = state.fileBrowserFileId;

    const isOwner = isComposite ? !!state.user?.is_system_admin : isWorkgroupOwner(state.fileBrowserWorkgroupId);
    const isVirtual = file._source && file._source.startsWith("virtual-");

    // Reuse existing file rendering logic
    const displayPath = file._originalPath || file.path;
    pre.textContent = file.content;
    state.fileOverlayShowRaw = false;
    state.fileOverlayLastContent = file.content;

    const rawToggle = qs("file-overlay-raw-toggle");

    if (isJsonFile(displayPath)) {
      const parsed = tryParseJson(file.content);
      state.fileOverlayParsedJson = parsed.ok ? parsed.data : null;

      if (parsed.ok) {
        rendered.innerHTML = "";
        rendered.classList.add("hidden");
        if (isAgentConfigPath(displayPath) && isAgentConfigShape(parsed.data)) {
          renderAgentConfigForm(parsed.data, !isOwner || isVirtual);
        } else if (isWorkgroupConfigPath(displayPath)) {
          renderWorkgroupConfigForm(parsed.data, !isOwner || isVirtual, new Set(["id", "owner_id", "created_at"]));
        } else {
          const lockedKeys = displayPath.endsWith("workgroup.json")
            ? new Set(["id", "owner_id", "created_at"])
            : null;
          renderJsonForm(parsed.data, !isOwner || isVirtual, lockedKeys);
        }
        rawToggle.classList.remove("hidden");
        setFileOverlayViewMode("form");
        updateFileOverlayEditButton(isOwner && !isVirtual, true, true);
      } else {
        form.innerHTML = "";
        form.classList.add("hidden");
        rendered.innerHTML = "";
        rendered.classList.add("hidden");
        pre.classList.remove("hidden");
        rawToggle.classList.add("hidden");
        state.fileOverlayViewMode = "raw";
        state.fileOverlayParsedJson = null;
        const editBtn = qs("file-overlay-edit");
        editBtn.textContent = "Edit";
        editBtn.classList.toggle("hidden", !isOwner || isVirtual);
      }
    } else if (isMarkdownFile(displayPath)) {
      form.innerHTML = "";
      form.classList.add("hidden");
      state.fileOverlayParsedJson = null;
      state.fileOverlayViewMode = "raw";
      pre.classList.add("hidden");
      rendered.innerHTML = renderMarkdown(file.content);
      rendered.classList.remove("hidden");
      rawToggle.textContent = "Raw";
      rawToggle.classList.remove("hidden");
      const editBtn = qs("file-overlay-edit");
      editBtn.textContent = "Edit";
      editBtn.classList.toggle("hidden", !isOwner || isVirtual);
    } else if (isImageFile(displayPath) || isDataUrl(file.content)) {
      form.innerHTML = "";
      form.classList.add("hidden");
      state.fileOverlayParsedJson = null;
      state.fileOverlayViewMode = "raw";
      pre.classList.add("hidden");
      const src = escapeHtml(file.content);
      rendered.innerHTML = `<img src="${src}" alt="${escapeHtml(displayPath)}" class="file-overlay-image" />`;
      rendered.classList.remove("hidden");
      rawToggle.classList.add("hidden");
      qs("file-overlay-edit").classList.add("hidden");
    } else {
      form.innerHTML = "";
      form.classList.add("hidden");
      state.fileOverlayParsedJson = null;
      state.fileOverlayViewMode = "raw";
      pre.classList.remove("hidden");
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      rawToggle.classList.add("hidden");
      const editBtn = qs("file-overlay-edit");
      editBtn.textContent = "Edit";
      editBtn.classList.toggle("hidden", !isOwner || isVirtual);
    }

    qs("file-overlay-delete").classList.toggle("hidden", !isOwner || isVirtual);

    // Show composer file context
    const ctxBar = qs("composer-file-context");
    ctxBar.innerHTML = `<span>Attached: <strong>${escapeHtml(displayPath)}</strong></span><button type="button" class="icon-button" data-action="clear-file-context">\u00d7</button>`;
    ctxBar.classList.remove("hidden");
  } else {
    // Browsing directory listing
    state.fileOverlayOpen = false;
    state.fileOverlayParsedJson = null;

    pre.classList.add("hidden");
    rendered.innerHTML = "";
    rendered.classList.add("hidden");
    form.innerHTML = "";
    form.classList.add("hidden");
    qs("file-overlay-raw-toggle").classList.add("hidden");
    qs("file-overlay-edit").classList.add("hidden");
    qs("file-overlay-delete").classList.add("hidden");
    qs("composer-file-context").classList.add("hidden");

    // Navigate to the current path in the file tree
    let files;
    if (isComposite) {
      files = state.fileBrowserCompositeFiles;
    } else {
      files = filesForConversationContext(normalizeWorkgroupFiles(data.workgroup?.files), state.fileBrowserWorkgroupId);
    }
    const tree = buildWorkgroupFileTree(files);
    let node = tree;
    for (const segment of state.fileBrowserPath) {
      if (node.folders.has(segment)) {
        node = node.folders.get(segment);
      } else {
        // Path no longer exists, reset to root
        state.fileBrowserPath = [];
        node = tree;
        break;
      }
    }

    const isOwner = isComposite ? !!state.user?.is_system_admin : isWorkgroupOwner(state.fileBrowserWorkgroupId);
    listing.innerHTML = renderFileBrowserListing(node, isOwner);
    listing.classList.remove("hidden");
  }

  overlay.classList.remove("hidden");
  showOverlaySplit();
}

function refreshFileOverlayIfOpen() {
  if (state.fileBrowserOpen) {
    renderFileBrowser();
    return;
  }
  if (!state.fileOverlayOpen) {
    return;
  }
  const data = state.treeData[state.fileOverlayWorkgroupId];
  if (!data) {
    closeFileOverlay();
    flash("Workgroup no longer available", "info");
    return;
  }
  const files = normalizeWorkgroupFiles(data.workgroup?.files);
  const file = files.find((item) => item.id === state.fileOverlayFileId);
  if (!file) {
    closeFileOverlay();
    flash("File was deleted", "info");
    return;
  }
  qs("file-overlay-path").textContent = file.path;
  qs("file-overlay-workgroup").textContent = data.workgroup.name;

  if (file.content === state.fileOverlayLastContent) {
    return;
  }
  state.fileOverlayLastContent = file.content;

  const pre = qs("file-overlay-content");
  const rendered = qs("file-overlay-rendered");
  const rawToggle = qs("file-overlay-raw-toggle");
  const form = qs("file-overlay-form");
  const isOwner = isWorkgroupOwner(state.fileOverlayWorkgroupId);

  pre.textContent = file.content;

  if (isJsonFile(file.path)) {
    const parsed = tryParseJson(file.content);
    state.fileOverlayParsedJson = parsed.ok ? parsed.data : null;

    if (parsed.ok) {
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      if (isAgentConfigPath(file.path) && isAgentConfigShape(parsed.data)) {
        renderAgentConfigForm(parsed.data, !isOwner);
      } else if (isToolsManifestPath(file.path) && isToolsManifestShape(parsed.data)) {
        renderToolsManifestForm(parsed.data, !isOwner);
      } else if (isWorkgroupConfigPath(file.path)) {
        renderWorkgroupConfigForm(parsed.data, !isOwner, new Set(["id", "owner_id", "created_at"]));
      } else {
        const lockedKeys = file.path.endsWith("workgroup.json")
          ? new Set(["id", "owner_id", "created_at"])
          : null;
        renderJsonForm(parsed.data, !isOwner, lockedKeys);
      }
      rawToggle.classList.remove("hidden");
      if (state.fileOverlayViewMode === "form") {
        setFileOverlayViewMode("form");
      }
      updateFileOverlayEditButton(isOwner, state.fileOverlayViewMode === "form", true);
    } else {
      form.innerHTML = "";
      form.classList.add("hidden");
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      pre.classList.remove("hidden");
      rawToggle.classList.add("hidden");
      state.fileOverlayViewMode = "raw";
      state.fileOverlayParsedJson = null;
      const editBtn = qs("file-overlay-edit");
      editBtn.textContent = "Edit";
      editBtn.classList.toggle("hidden", !isOwner);
    }
  } else if (isMarkdownFile(file.path)) {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    rawToggle.classList.remove("hidden");
    if (state.fileOverlayShowRaw) {
      pre.classList.remove("hidden");
      rendered.innerHTML = "";
      rendered.classList.add("hidden");
      rawToggle.textContent = "Rendered";
    } else {
      pre.classList.add("hidden");
      rendered.innerHTML = renderMarkdown(file.content);
      rendered.classList.remove("hidden");
      rawToggle.textContent = "Raw";
    }
    const editBtn = qs("file-overlay-edit");
    editBtn.textContent = "Edit";
    editBtn.classList.toggle("hidden", !isOwner);
  } else if (isImageFile(file.path) || isDataUrl(file.content)) {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    pre.classList.add("hidden");
    const src = isDataUrl(file.content) ? escapeHtml(file.content) : escapeHtml(file.content);
    rendered.innerHTML = `<img src="${src}" alt="${escapeHtml(file.path)}" class="file-overlay-image" />`;
    rendered.classList.remove("hidden");
    rawToggle.classList.add("hidden");
    qs("file-overlay-edit").classList.add("hidden");
  } else {
    form.innerHTML = "";
    form.classList.add("hidden");
    state.fileOverlayParsedJson = null;
    pre.classList.remove("hidden");
    rendered.innerHTML = "";
    rendered.classList.add("hidden");
    rawToggle.classList.add("hidden");
    const editBtn = qs("file-overlay-edit");
    editBtn.textContent = "Edit";
    editBtn.classList.toggle("hidden", !isOwner);
  }
}

function newWorkgroupFileId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `file-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeTemplateDraftFiles(files) {
  if (!Array.isArray(files)) {
    return [];
  }

  const normalized = [];
  const seenPaths = new Set();
  for (const item of files) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const path = String(item.path || "").trim();
    const content = typeof item.content === "string" ? item.content : String(item.content || "");
    if (!path || seenPaths.has(path)) {
      continue;
    }
    seenPaths.add(path);
    normalized.push({ id: newWorkgroupFileId(), path, content });
  }
  return normalized;
}

function normalizeTemplateDraftAgents(agents) {
  if (!Array.isArray(agents)) {
    return [];
  }

  const normalized = [];
  const seenNames = new Set();
  for (const item of agents) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const name = String(item.name || "").trim();
    if (!name || seenNames.has(name.toLowerCase())) {
      continue;
    }
    seenNames.add(name.toLowerCase());

    const toolNames = Array.isArray(item.tool_names)
      ? item.tool_names.map((value) => String(value || "").trim()).filter(Boolean)
      : [];

    normalized.push({
      id: newWorkgroupFileId(),
      name,
      description: String(item.description || ""),
      role: String(item.role || ""),
      personality: String(item.personality || "Professional and concise"),
      backstory: String(item.backstory || ""),
      model: String(item.model || "gpt-5-nano"),
      temperature: Number.isFinite(Number(item.temperature)) ? Number(item.temperature) : 0.7,
      verbosity: Number.isFinite(Number(item.verbosity)) ? Number(item.verbosity) : 0.5,
      tool_names: toolNames,
      response_threshold: Number.isFinite(Number(item.response_threshold)) ? Number(item.response_threshold) : 0.55,
      follow_up_minutes: Number.isFinite(Number(item.follow_up_minutes)) ? Number(item.follow_up_minutes) : 60,
    });
  }
  return normalized;
}

function normalizeWorkgroupTemplateCatalog(templates) {
  if (!Array.isArray(templates)) {
    return [];
  }

  const normalized = [];
  const seenKeys = new Set();
  for (const item of templates) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const key = String(item.key || "").trim();
    if (!key || seenKeys.has(key)) {
      continue;
    }
    seenKeys.add(key);

    normalized.push({
      key,
      name: String(item.name || key),
      description: String(item.description || ""),
      files: normalizeTemplateDraftFiles(item.files),
      agents: normalizeTemplateDraftAgents(item.agents),
    });
  }
  return normalized;
}

function templateByKey(templateKey) {
  if (!templateKey) {
    return null;
  }
  return state.workgroupTemplates.find((item) => item.key === templateKey) || null;
}

function preferredCreateTemplateKey() {
  const coding = state.workgroupTemplates.find((item) => item.key === "coding");
  if (coding) {
    return coding.key;
  }
  return state.workgroupTemplates[0]?.key || "";
}

function renderWorkgroupTemplateSelector() {
  const templateSelect = qs("workgroup-template");
  if (!templateSelect) {
    return;
  }

  if (!state.workgroupTemplates.length) {
    templateSelect.innerHTML = "<option value=''>No templates available</option>";
    templateSelect.disabled = true;
  } else {
    templateSelect.disabled = false;
    templateSelect.innerHTML = state.workgroupTemplates
      .map((template) => `<option value="${escapeHtml(template.key)}">${escapeHtml(template.name)}</option>`)
      .join("");

    const key = templateByKey(state.workgroupCreateTemplateKey) ? state.workgroupCreateTemplateKey : preferredCreateTemplateKey();
    state.workgroupCreateTemplateKey = key;
    templateSelect.value = key;
  }

  const descriptionNode = qs("workgroup-template-description");
  if (descriptionNode) {
    const currentTemplate = templateByKey(state.workgroupCreateTemplateKey);
    descriptionNode.textContent =
      currentTemplate?.description ||
      "Choose a template. Template definitions are managed in the Administration workgroup under .templates/workgroups/.";
  }
}

function renderWorkgroupCreateFilesEditor() {
  const node = qs("workgroup-create-files");
  if (!node) {
    return;
  }

  if (!state.workgroupCreateFiles.length) {
    node.innerHTML = "<p class='meta create-workgroup-empty'>No starter files. Add one if needed.</p>";
    return;
  }

  node.innerHTML = state.workgroupCreateFiles
    .map(
      (file) => `
        <div class="create-workgroup-file-row" data-file-id="${escapeHtml(file.id)}">
          <div class="create-workgroup-file-top">
            <input
              type="text"
              maxlength="512"
              placeholder="docs/notes.md"
              value="${escapeHtml(file.path)}"
              data-action="create-file-path"
              data-file-id="${escapeHtml(file.id)}"
            />
            <button type="button" class="danger" data-action="create-file-remove" data-file-id="${escapeHtml(file.id)}">Remove</button>
          </div>
          <textarea
            rows="4"
            placeholder="Starter content"
            data-action="create-file-content"
            data-file-id="${escapeHtml(file.id)}"
          >${escapeHtml(file.content)}</textarea>
        </div>
      `,
    )
    .join("");
}

function renderWorkgroupCreateEditor() {
  renderWorkgroupTemplateSelector();
}

function applyTemplateToCreateDraft(templateKey) {
  const template = templateByKey(templateKey);
  if (!template) {
    state.workgroupCreateTemplateKey = "";
    renderWorkgroupCreateEditor();
    return;
  }
  state.workgroupCreateTemplateKey = template.key;
  renderWorkgroupCreateEditor();
}

function resetWorkgroupCreateDraft() {
  const preferred = preferredCreateTemplateKey();
  if (!preferred) {
    state.workgroupCreateTemplateKey = "";
    renderWorkgroupCreateEditor();
    return;
  }
  applyTemplateToCreateDraft(preferred);
}

function updateWorkgroupCreateFile(fileId, field, value) {
  const index = state.workgroupCreateFiles.findIndex((file) => file.id === fileId);
  if (index < 0) {
    return;
  }
  state.workgroupCreateFiles[index] = { ...state.workgroupCreateFiles[index], [field]: value };
}

function removeWorkgroupCreateFile(fileId) {
  state.workgroupCreateFiles = state.workgroupCreateFiles.filter((file) => file.id !== fileId);
  renderWorkgroupCreateFilesEditor();
}

function renderWorkgroupCreateAgentsEditor() {
  const node = qs("workgroup-create-agents");
  if (!node) {
    return;
  }

  if (!state.workgroupCreateAgents.length) {
    node.innerHTML = "<p class='meta create-workgroup-empty'>No starter agents. Add one if needed.</p>";
    return;
  }

  node.innerHTML = state.workgroupCreateAgents
    .map(
      (agent) => `
        <div class="create-workgroup-agent-row" data-agent-id="${escapeHtml(agent.id)}">
          <div class="create-workgroup-file-top">
            <input
              type="text"
              maxlength="80"
              placeholder="Agent name"
              value="${escapeHtml(agent.name)}"
              data-action="create-agent-name"
              data-agent-id="${escapeHtml(agent.id)}"
            />
            <button type="button" class="danger" data-action="create-agent-remove" data-agent-id="${escapeHtml(agent.id)}">Remove</button>
          </div>
          <input
            type="text"
            maxlength="200"
            placeholder="Role"
            value="${escapeHtml(agent.role)}"
            data-action="create-agent-role"
            data-agent-id="${escapeHtml(agent.id)}"
          />
          <textarea
            rows="2"
            placeholder="Personality"
            data-action="create-agent-personality"
            data-agent-id="${escapeHtml(agent.id)}"
          >${escapeHtml(agent.personality)}</textarea>
          <input
            type="text"
            placeholder="tools: Read, Write, Edit, Bash"
            value="${escapeHtml(agent.tool_names.join(", "))}"
            data-action="create-agent-tools"
            data-agent-id="${escapeHtml(agent.id)}"
          />
        </div>
      `,
    )
    .join("");
}

function newWorkgroupCreateAgentDraft() {
  return {
    id: newWorkgroupFileId(),
    name: "",
    description: "",
    role: "",
    personality: "Professional and concise",
    backstory: "",
    model: "gpt-5-nano",
    temperature: 0.7,
    verbosity: 0.5,
    tool_names: [],
    response_threshold: 0.55,
    follow_up_minutes: 60,
  };
}

function updateWorkgroupCreateAgent(agentId, field, value) {
  const index = state.workgroupCreateAgents.findIndex((agent) => agent.id === agentId);
  if (index < 0) {
    return;
  }
  state.workgroupCreateAgents[index] = { ...state.workgroupCreateAgents[index], [field]: value };
}

function removeWorkgroupCreateAgent(agentId) {
  state.workgroupCreateAgents = state.workgroupCreateAgents.filter((agent) => agent.id !== agentId);
  renderWorkgroupCreateAgentsEditor();
}

function normalizeWorkgroupCreateFilesForSubmit() {
  const normalized = [];
  const seenPaths = new Set();
  for (const file of state.workgroupCreateFiles) {
    const path = String(file.path || "").trim();
    const content = typeof file.content === "string" ? file.content : String(file.content || "");
    if (!path && !content.trim()) {
      continue;
    }
    if (!path) {
      throw new Error("Starter file path cannot be empty");
    }
    if (path.length > 512) {
      throw new Error(`Starter file path is too long: ${path.slice(0, 40)}...`);
    }
    if (content.length > 200000) {
      throw new Error(`Starter file content is too long: ${path}`);
    }
    if (seenPaths.has(path)) {
      throw new Error(`Duplicate starter file path: ${path}`);
    }
    seenPaths.add(path);
    normalized.push({ id: file.id || newWorkgroupFileId(), path, content });
  }
  return normalized;
}

function normalizeWorkgroupCreateAgentsForSubmit() {
  const normalized = [];
  const seenNames = new Set();
  for (const agent of state.workgroupCreateAgents) {
    const name = String(agent.name || "").trim();
    const role = String(agent.role || "").trim();
    const personality = String(agent.personality || "Professional and concise").trim() || "Professional and concise";
    const toolNames = Array.isArray(agent.tool_names)
      ? agent.tool_names.map((tool) => String(tool || "").trim()).filter(Boolean)
      : [];

    if (!name && !role && !toolNames.length) {
      continue;
    }
    if (!name) {
      throw new Error("Starter agent name cannot be empty");
    }
    if (seenNames.has(name.toLowerCase())) {
      throw new Error(`Duplicate starter agent name: ${name}`);
    }
    seenNames.add(name.toLowerCase());

    normalized.push({
      name,
      description: String(agent.description || ""),
      role,
      personality,
      backstory: String(agent.backstory || ""),
      model: String(agent.model || "gpt-5-nano"),
      temperature: Number.isFinite(Number(agent.temperature)) ? Number(agent.temperature) : 0.7,
      verbosity: Number.isFinite(Number(agent.verbosity)) ? Number(agent.verbosity) : 0.5,
      tool_names: toolNames,
      response_threshold: Number.isFinite(Number(agent.response_threshold)) ? Number(agent.response_threshold) : 0.55,
      follow_up_minutes: Number.isFinite(Number(agent.follow_up_minutes)) ? Math.trunc(Number(agent.follow_up_minutes)) : 60,
    });
  }
  return normalized;
}

async function loadWorkgroupTemplates() {
  if (!state.token) {
    state.workgroupTemplates = [];
    state.workgroupCreateTemplateKey = "";
    state.workgroupCreateFiles = [];
    state.workgroupCreateAgents = [];
    renderWorkgroupCreateEditor();
    return;
  }

  const templates = await api("/api/workgroup-templates");
  state.workgroupTemplates = normalizeWorkgroupTemplateCatalog(templates);
  resetWorkgroupCreateDraft();
}

function directKeyForCurrentUser(otherUserId) {
  if (!state.user) {
    return "";
  }
  const pair = [state.user.id, otherUserId].sort();
  return `dm:${pair[0]}:${pair[1]}`;
}

function adminConversationId(workgroupId) {
  const data = state.treeData[workgroupId];
  const admin = data?.jobs.find((item) => item.kind === "admin");
  return admin?.id || "";
}

function isAdminConversation(workgroupId, conversationId) {
  const conversation = conversationById(workgroupId, conversationId);
  return conversation?.kind === "admin";
}

function nodeKeyForConversation(workgroupId, conversation) {
  if (!conversation) {
    return "";
  }
  if (conversation.kind !== "direct") {
    return `job:${workgroupId}:${conversation.id}`;
  }

  if (conversation.topic.startsWith("dma:")) {
    const parts = conversation.topic.split(":");
    const agentId = parts[2] || "";
    return agentId ? `agent:${workgroupId}:${agentId}` : "";
  }

  const parts = conversation.topic.split(":");
  const otherUserId = parts.find((part) => part !== "dm" && part !== state.user?.id) || "";
  return otherUserId ? `member:${workgroupId}:${otherUserId}` : "";
}

function fallbackConversation(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return null;
  }

  const admin = data.jobs.find((item) => item.kind === "admin");
  if (admin) {
    return admin;
  }
  if (data.jobs.length) {
    return data.jobs[0];
  }
  if (data.directs.length) {
    return data.directs[0];
  }
  return null;
}

function clearActiveConversationUI() {
  const previousConversationId = state.activeConversationId;
  if (previousConversationId) {
    delete state.thinkingByConversation[previousConversationId];
  }
  state.activeConversationId = "";
  state.activeNodeKey = "";
  state.activeMessages = [];
  state.conversationUsage = null;
  renderMessages([]);
  setTextIfPresent("active-conversation", "No active conversation");
  setTextIfPresent("active-context", "Use the tree to open a job, member DM, or administration conversation.");
  const usageEl = qs("active-usage");
  if (usageEl) usageEl.classList.add("hidden");
  const toolBar = qs("chat-tool-buttons");
  if (toolBar) { toolBar.innerHTML = ""; toolBar.classList.add("hidden"); }
  const headerActions = qs("chat-header-actions");
  if (headerActions) headerActions.classList.add("hidden");
  const composerForm = qs("message-form");
  if (composerForm) composerForm.classList.remove("hidden");
}

function isDestructiveAdminCommand(content) {
  const normalized = content.trim().toLowerCase();
  return /(?:^|\s)(remove|delete)\s+(?:the\s+)?(?:member|user|participant|agent|job|conversation|channel|workgroup)\b/.test(normalized);
}

function isDeleteWorkgroupCommand(content) {
  const normalized = content.trim().toLowerCase();
  return /(?:^|\s)(remove|delete)\s+(?:(?:this|the|a)\s+)?workgroup\b/.test(normalized);
}

function scheduleDestructiveAdminRefresh(delaysMs = [650, 1700]) {
  for (const delayMs of delaysMs) {
    window.setTimeout(async () => {
      if (!state.token) {
        return;
      }
      try {
        await loadWorkgroups();
      } catch (error) {
        console.error(error);
      }
    }, delayMs);
  }
}

function conversationLabel(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return "Conversation";
  }

  const jobConv = data.jobs.find((item) => item.id === conversationId);
  if (jobConv) {
    if (jobConv.kind === "admin") {
      if (data.workgroup.name === "Administration" && !data.workgroup.organization_id) {
        return "System Administration";
      }
      if (data.workgroup.name === "Administration" && data.workgroup.organization_name) {
        return `Organization Administration · ${data.workgroup.organization_name}`;
      }
      const orgName = data.workgroup.organization_name;
      if (orgName) {
        return `Administration · ${orgName} · ${data.workgroup.name}`;
      }
      return `Administration · ${data.workgroup.name}`;
    }
    return jobDisplayName(jobConv);
  }

  const taskConv = (data.taskConversations || []).find((item) => item.id === conversationId);
  if (taskConv) {
    const task = (data.agentTasks || []).find((t) => t.conversation_id === conversationId);
    if (task) {
      return task.title;
    }
    return taskConv.name || taskConv.topic || "Task";
  }

  const direct = data.directs.find((item) => item.id === conversationId);
  if (direct) {
    if (direct.topic.startsWith("dma:")) {
      const parts = direct.topic.split(":");
      const directAgentId = parts[2] || "";
      return `@${agentName(workgroupId, directAgentId)}`;
    }

    const parts = direct.topic.split(":");
    const otherUserId = parts.find((part) => part !== "dm" && part !== state.user?.id) || "";
    return `@${memberName(workgroupId, otherUserId)}`;
  }

  return "Conversation";
}


function conversationById(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return null;
  }
  return data.jobs.find((item) => item.id === conversationId) || data.directs.find((item) => item.id === conversationId) || (data.taskConversations || []).find((item) => item.id === conversationId) || null;
}


function fileBrowserContextLabel(workgroupId) {
  const conv = conversationById(workgroupId, state.activeConversationId);
  if (conv?.kind === "direct") {
    return conversationLabel(workgroupId, state.activeConversationId);
  }
  const data = state.treeData[workgroupId];
  return data?.workgroup?.name || "Files";
}

function conversationContextLabel(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  const workgroupName = data?.workgroup?.name || workgroupId;
  const conversation = conversationById(workgroupId, conversationId);
  if (workgroupName === "Administration" && conversation?.kind === "admin") {
    if (!data?.workgroup?.organization_id) {
      return "System Administration";
    }
    const orgName = data.workgroup.organization_name || "Organization";
    return `Organization Administration · ${orgName}`;
  }
  const base = `Workgroup: ${workgroupName}`;
  if (!conversation) {
    return base;
  }
  const description = (conversation.description || "").trim();
  if (!description) {
    return base;
  }
  return `${base} · ${description}`;
}


function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}


function isAgentMentioned(content, agent) {
  const text = (content || "").trim();
  const name = (agent?.name || "").trim();
  if (!text || !name) {
    return false;
  }

  const fullNamePattern = new RegExp(`@\\s*${escapeRegex(name)}\\b`, "i");
  if (fullNamePattern.test(text)) {
    return true;
  }

  const firstToken = name.split(/\s+/)[0] || "";
  if (firstToken.length >= 3) {
    const tokenPattern = new RegExp(`\\b${escapeRegex(firstToken)}\\b`, "i");
    if (tokenPattern.test(text)) {
      return true;
    }
  }

  return false;
}


function inferThinkingAgentIds(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  const conversation = conversationById(workgroupId, conversationId);
  if (!data || !conversation) {
    return [];
  }

  if (conversation.kind === "direct") {
    if (!conversation.topic.startsWith("dma:")) {
      return [];
    }
    const parts = conversation.topic.split(":");
    return parts[2] ? [parts[2]] : [];
  }

  if (conversation.kind === "admin") {
    return (data.agents || [])
      .filter((item) => item.description === "__system_admin_agent__")
      .map((item) => item.id);
  }

  return [];
}


function startThinkingForMessage(postedMessage) {
  if (!state.selectedWorkgroupId || !state.activeConversationId) {
    return;
  }

  const workgroupId = state.selectedWorkgroupId;
  const conversationId = state.activeConversationId;
  const data = state.treeData[workgroupId];
  const conversation = conversationById(workgroupId, conversationId);
  if (!conversation || !data) {
    delete state.thinkingByConversation[conversationId];
    return;
  }

  const defaultAgentIds = inferThinkingAgentIds(workgroupId, conversationId);
  let mode = "agent";
  let agentIds = defaultAgentIds;

  if (conversation.kind === "job" || conversation.kind === "engagement") {
    const jobAgents = (data.agents || []).filter((item) => item.description !== "__system_admin_agent__");
    const mentionedAgentIds = jobAgents
      .filter((agent) => isAgentMentioned(postedMessage.content || "", agent))
      .map((agent) => agent.id);

    if (mentionedAgentIds.length === 1) {
      agentIds = [mentionedAgentIds[0]];
      mode = "agent";
    } else {
      agentIds = [];
      mode = "selecting";
    }
  }

  if (!agentIds.length && mode !== "selecting") {
    delete state.thinkingByConversation[conversationId];
    return;
  }

  state.thinkingByConversation[conversationId] = {
    triggerMessageId: postedMessage.id,
    triggerCreatedAtMs: new Date(postedMessage.created_at).getTime(),
    startedAtMs: Date.now(),
    lastActivityAtMs: Date.now(),
    agentIds,
    mode,
  };
}


function syncThinkingState(messages) {
  const conversationId = state.activeConversationId;
  if (!conversationId) {
    return;
  }

  const pending = state.thinkingByConversation[conversationId];
  if (!pending) {
    return;
  }

  // Time out after 60s of inactivity (no live activity from server).
  // lastActivityAtMs is reset whenever the server reports live activity.
  const inactiveMs = Date.now() - (pending.lastActivityAtMs || pending.startedAtMs);
  if (inactiveMs > 60000) {
    delete state.thinkingByConversation[conversationId];
    return;
  }

  // Hard cap at 5 minutes regardless of activity.
  if (Date.now() - pending.startedAtMs > 300000) {
    delete state.thinkingByConversation[conversationId];
    return;
  }

  // Only clear thinking when agent replies arrive AND no recent server
  // activity.  Between chain steps there's a brief gap where liveActivity
  // is empty, so we use lastActivityAtMs with a grace period instead.
  const hasAgentReply = messages.some((message) => {
    if (message.sender_type !== "agent") {
      return false;
    }
    if (message.response_to_message_id === pending.triggerMessageId) {
      return true;
    }
    const createdAtMs = new Date(message.created_at).getTime();
    return createdAtMs > pending.triggerCreatedAtMs;
  });

  if (hasAgentReply) {
    const recentActivityMs = pending.lastActivityAtMs
      ? Date.now() - pending.lastActivityAtMs
      : Infinity;
    // If the server reported agent activity within the last 15s, the chain
    // is likely still running — keep the thinking state alive.
    if (recentActivityMs > 15000) {
      delete state.thinkingByConversation[conversationId];
    }
  }
}


function _phaseStatusText(phase, detail) {
  if (phase === "probing") return "evaluating...";
  if (phase === "tool" && detail) return `running ${detail}...`;
  if (phase === "composing") return "composing reply...";
  return "thinking...";
}

function renderThinkingRows(workgroupId, pending) {
  // Use live activity data when available.
  const liveActivity = pending.liveActivity;
  if (liveActivity && liveActivity.length) {
    return liveActivity.map((entry) => {
      const name = entry.agent_name || agentName(workgroupId, entry.agent_id);
      const wgData = state.treeData[workgroupId];
      const thinkingAgent = wgData?.agents?.find((a) => a.id === entry.agent_id);
      const avatarContent = thinkingAgent?.icon
        ? `<img src="${escapeHtml(thinkingAgent.icon)}" alt="" />`
        : generateBotSvg(name);
      const statusText = _phaseStatusText(entry.phase, entry.detail);
      return `
        <article class="message-row agent thinking">
          <div class="avatar">${avatarContent}</div>
          <div>
            <div class="message-meta">
              <span class="sender">${escapeHtml(name)}</span>
              <span class="thinking-status"><span class="thinking-dot" aria-hidden="true"></span>${escapeHtml(statusText)}</span>
            </div>
          </div>
        </article>
      `;
    }).join("");
  }

  if (pending.mode === "selecting" || !pending.agentIds.length) {
    return `
      <article class="message-row agent thinking">
        <div class="avatar">${generateBotSvg("Agent router")}</div>
        <div>
          <div class="message-meta">
            <span class="sender">Agent router</span>
            <span class="thinking-status"><span class="thinking-dot" aria-hidden="true"></span>selecting responder...</span>
          </div>
          <div class="message-text">Choosing the best next agent to reply.</div>
        </div>
      </article>
    `;
  }

  return pending.agentIds
    .map((agentId) => {
      const name = agentName(workgroupId, agentId);
      const wgData = state.treeData[workgroupId];
      const thinkingAgent = wgData?.agents?.find((a) => a.id === agentId);
      const thinkingAvatarContent = thinkingAgent?.icon
        ? `<img src="${escapeHtml(thinkingAgent.icon)}" alt="" />`
        : generateBotSvg(name);
      return `
        <article class="message-row agent thinking">
          <div class="avatar">${thinkingAvatarContent}</div>
          <div>
            <div class="message-meta">
              <span class="sender">${escapeHtml(name)}</span>
              <span class="thinking-status"><span class="thinking-dot" aria-hidden="true"></span>thinking...</span>
            </div>
            <div class="message-text">Working on a response.</div>
          </div>
        </article>
      `;
    })
    .join("");
}

function setSettingsSubtitle(value) {
  const node = qs("settings-subtitle");
  if (!value) {
    node.textContent = "";
    node.classList.add("hidden");
    return;
  }
  node.textContent = value;
  node.classList.remove("hidden");
}

function closeSettingsModal() {
  const modal = qs("settings-modal");
  const form = qs("settings-form");
  modal.classList.add("hidden");
  state.settingsOpen = false;
  state.settingsSubmitHandler = null;
  setSettingsSubtitle("");
  setTextIfPresent("settings-title", "Settings");
  form.onsubmit = null;
  form.innerHTML = "";
}

function settingsFormIsDirty(form) {
  const fields = form.querySelectorAll("input, textarea, select");
  for (const field of fields) {
    if (field.disabled) {
      continue;
    }
    if (field instanceof HTMLInputElement && (field.type === "checkbox" || field.type === "radio")) {
      if (field.checked !== field.defaultChecked) {
        return true;
      }
      continue;
    }
    if (field instanceof HTMLSelectElement && field.multiple) {
      const current = Array.from(field.options).map((option) => option.selected);
      const defaults = Array.from(field.options).map((option) => option.defaultSelected);
      if (current.some((value, idx) => value !== defaults[idx])) {
        return true;
      }
      continue;
    }
    if (field.value !== field.defaultValue) {
      return true;
    }
  }
  return false;
}

async function submitSettingsForm(form) {
  if (!state.settingsSubmitHandler) {
    closeSettingsModal();
    return;
  }

  const submitButton = form.querySelector("button[type='submit']");
  const originalSubmitLabel = submitButton ? submitButton.textContent : "";
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = "Saving...";
  }
  try {
    await state.settingsSubmitHandler(new FormData(form));
    closeSettingsModal();
  } catch (error) {
    flash(error.message || "Failed to save settings", "error");
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = originalSubmitLabel;
    }
  }
}

async function requestSettingsClose({ saveIfDirty = false } = {}) {
  if (!state.settingsOpen) {
    return;
  }
  const form = qs("settings-form");
  const submitButton = form.querySelector("button[type='submit']");
  const canSubmit = Boolean(state.settingsSubmitHandler && submitButton && !submitButton.disabled);

  if (saveIfDirty && canSubmit && settingsFormIsDirty(form)) {
    await submitSettingsForm(form);
    return;
  }

  closeSettingsModal();
}

function openSettingsModal({ title, subtitle = "", formHtml, onSubmit, onRender = null }) {
  const modal = qs("settings-modal");
  const form = qs("settings-form");
  setTextIfPresent("settings-title", title);
  setSettingsSubtitle(subtitle);
  form.innerHTML = formHtml;
  state.settingsSubmitHandler = onSubmit;
  form.onsubmit = async (event) => {
    event.preventDefault();
    await submitSettingsForm(form);
  };

  const cancel = form.querySelector("[data-action='settings-cancel']");
  if (cancel) {
    cancel.addEventListener("click", () => closeSettingsModal());
  }

  if (onRender) {
    onRender(form);
  }

  modal.classList.remove("hidden");
  state.settingsOpen = true;
  const firstInput = form.querySelector("input:not([disabled]), textarea:not([disabled]), select:not([disabled])");
  if (firstInput) {
    firstInput.focus();
  }
}

function toolDisplayLabel(name) {
  return name.replace(/^custom:/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getConversationAgent(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  if (!data) return null;

  const conversation = conversationById(workgroupId, conversationId);
  if (!conversation) return null;

  if (conversation.kind === "admin") {
    return (data.agents || []).find((a) => a.description === "__system_admin_agent__") || null;
  }

  if (conversation.kind === "direct" && conversation.topic.startsWith("dma:")) {
    const agentId = conversation.topic.split(":")[2] || "";
    return (data.agents || []).find((a) => a.id === agentId) || null;
  }

  // Task conversations — find the agent via the task record
  const task = (data.agentTasks || []).find((t) => t.conversation_id === conversationId);
  if (task) {
    return (data.agents || []).find((a) => a.id === task.agent_id) || null;
  }

  return null;
}

function refreshActiveConversationHeader() {
  if (!state.selectedWorkgroupId || !state.activeConversationId) {
    return;
  }
  setTextIfPresent("active-conversation", conversationLabel(state.selectedWorkgroupId, state.activeConversationId));
  setTextIfPresent("active-context", conversationContextLabel(state.selectedWorkgroupId, state.activeConversationId));

  // Hide composer for archived conversations
  const composerForm = qs("message-form");
  if (composerForm) {
    if (isActiveConversationArchived()) {
      composerForm.classList.add("hidden");
    } else {
      composerForm.classList.remove("hidden");
    }
  }

  const toolBar = qs("chat-tool-buttons");
  if (!toolBar) return;

  // Check for engagement actions first
  const activeEngagement = getActiveEngagement();
  if (activeEngagement) {
    const isTargetOwner = isWorkgroupOwner(activeEngagement.target_workgroup_id) && activeEngagement.target_workgroup_id === state.selectedWorkgroupId;
    const isTargetMember = state.treeData[state.selectedWorkgroupId]?.engagements?.some(
      (e) => e.id === activeEngagement.id && e.target_workgroup_id === state.selectedWorkgroupId
    );
    const isSourceMember = state.treeData[state.selectedWorkgroupId]?.engagements?.some(
      (e) => e.id === activeEngagement.id && e.source_workgroup_id === state.selectedWorkgroupId
    );

    let buttons = "";
    if (isTargetOwner && (activeEngagement.status === "proposed" || activeEngagement.status === "negotiating")) {
      buttons += `<button type="button" class="chat-tool-btn accept" onclick="engagementRespond('${escapeHtml(activeEngagement.id)}', 'accept')">Accept</button>`;
      buttons += `<button type="button" class="chat-tool-btn decline" onclick="engagementRespond('${escapeHtml(activeEngagement.id)}', 'decline')">Decline</button>`;
    }
    if (isTargetMember && activeEngagement.status === "in_progress") {
      buttons += `<button type="button" class="chat-tool-btn" onclick="engagementComplete('${escapeHtml(activeEngagement.id)}')">Complete</button>`;
    }
    if (isSourceMember && activeEngagement.status === "completed") {
      buttons += `<button type="button" class="chat-tool-btn" onclick="engagementReview('${escapeHtml(activeEngagement.id)}', 'satisfied')">Satisfied</button>`;
      buttons += `<button type="button" class="chat-tool-btn" onclick="engagementReview('${escapeHtml(activeEngagement.id)}', 'dissatisfied')">Dissatisfied</button>`;
    }
    if (activeEngagement.status !== "cancelled" && activeEngagement.status !== "declined" && activeEngagement.status !== "reviewed") {
      buttons += `<button type="button" class="chat-tool-btn danger" onclick="engagementCancel('${escapeHtml(activeEngagement.id)}')">Cancel</button>`;
    }

    if (buttons) {
      toolBar.innerHTML = `<span class="task-badge ${escapeHtml(activeEngagement.status)}">${escapeHtml(activeEngagement.status)}</span> ` + buttons;
      toolBar.classList.remove("hidden");
    } else {
      toolBar.innerHTML = `<span class="task-badge ${escapeHtml(activeEngagement.status)}">${escapeHtml(activeEngagement.status)}</span>`;
      toolBar.classList.remove("hidden");
    }

    // Show jobs for this engagement
    const engagementJobs = [];
    for (const wgId of Object.keys(state.treeData)) {
      const wgData = state.treeData[wgId];
      if (wgData?.jobRecords) {
        for (const job of wgData.jobRecords) {
          if (job.engagement_id === activeEngagement.id) {
            engagementJobs.push({ ...job, workgroup_name: wgData.workgroup?.name || '?' });
          }
        }
      }
    }
    if (engagementJobs.length > 0) {
      const jobList = engagementJobs.map(j =>
        `<div class="engagement-job-item" data-action="open-job" data-workgroup="${escapeHtml(j.workgroup_id)}" data-job="${escapeHtml(j.id)}" data-conversation="${escapeHtml(j.conversation_id || "")}">
          <span class="task-badge ${escapeHtml(j.status)}">${escapeHtml(j.status)}</span>
          <span>${escapeHtml(j.title)}</span>
          <span class="finder-kind">${escapeHtml(j.workgroup_name)}</span>
        </div>`
      ).join("");
      toolBar.innerHTML += `<div class="engagement-jobs-section"><div class="engagement-jobs-title">Jobs</div>${jobList}</div>`;
    }

    return;
  }

  // Check for job context
  const activeJob = getActiveJob();
  let jobInfoHtml = "";
  if (activeJob) {
    jobInfoHtml = `<span class="task-badge ${escapeHtml(activeJob.status)}">${escapeHtml(activeJob.status)}</span>`;
    if (activeJob.engagement_id) {
      jobInfoHtml += ` <span class="job-engagement-link">Engagement: ${escapeHtml(activeJob.engagement_id.substring(0, 8))}...</span>`;
    }
  }

  const agent = getConversationAgent(state.selectedWorkgroupId, state.activeConversationId);
  const hasTools = agent && agent.tool_names && agent.tool_names.length;

  if (activeJob || hasTools) {
    let content = jobInfoHtml;
    if (hasTools) {
      const toolButtons = agent.tool_names
        .map((name) => `<button type="button" class="chat-tool-btn" data-tool-name="${escapeHtml(name)}">${escapeHtml(toolDisplayLabel(name))}</button>`)
        .join("");
      content += (content ? " " : "") + toolButtons;
    }
    toolBar.innerHTML = content;
    if (activeJob) {
      toolBar.classList.remove("hidden");
    } else {
      toolBar.classList.toggle("hidden", !state.toolbarVisible);
    }
  } else {
    toolBar.innerHTML = "";
    toolBar.classList.add("hidden");
  }

  // Highlight toolbar toggle when tools exist but toolbar is hidden
  const toggleBtn = qs("toggle-toolbar-btn");
  if (toggleBtn) {
    toggleBtn.classList.toggle("has-tools", !!hasTools && !state.toolbarVisible);
  }
}

function applyWorkgroupUpdateInState(updatedWorkgroup) {
  state.workgroups = state.workgroups.map((workgroup) => (workgroup.id === updatedWorkgroup.id ? updatedWorkgroup : workgroup));
  if (state.treeData[updatedWorkgroup.id]) {
    state.treeData[updatedWorkgroup.id].workgroup = updatedWorkgroup;
  }
  renderTree();
  refreshActiveConversationHeader();
  refreshFileOverlayIfOpen();
}

function applyJobUpdateInState(workgroupId, updatedConversation) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return;
  }
  data.jobs = data.jobs.map((conversation) => (conversation.id === updatedConversation.id ? updatedConversation : conversation));
  renderTree();
  refreshActiveConversationHeader();
}

function applyAgentUpdateInState(workgroupId, updatedAgent) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return;
  }
  data.agents = data.agents.map((agent) => (agent.id === updatedAgent.id ? updatedAgent : agent));
  renderTree();
  refreshActiveConversationHeader();
  if (state.activeMessages.length) {
    renderMessages(state.activeMessages);
  }
}

// ── Organization API helpers ──

async function loadOrganizations() {
  try {
    state.organizations = await api("/api/organizations");
  } catch {
    state.organizations = [];
  }
}

async function createOrganization(name, description = "") {
  const org = await api("/api/organizations", {
    method: "POST",
    body: { name, description },
  });
  state.organizations = [...state.organizations, org];
  return org;
}

async function updateOrganization(orgId, updates) {
  const org = await api(`/api/organizations/${orgId}`, {
    method: "PATCH",
    body: updates,
  });
  state.organizations = state.organizations.map((o) => (o.id === org.id ? org : o));
  return org;
}

async function deleteOrganization(orgId) {
  await api(`/api/organizations/${orgId}`, { method: "DELETE" });
  state.organizations = state.organizations.filter((o) => o.id !== orgId);
  // Ungroup workgroups in local state
  for (const wg of state.workgroups) {
    if (wg.organization_id === orgId) {
      wg.organization_id = null;
      wg.organization_name = "";
    }
  }
  for (const data of Object.values(state.treeData)) {
    if (data.workgroup && data.workgroup.organization_id === orgId) {
      data.workgroup.organization_id = null;
      data.workgroup.organization_name = "";
    }
  }
  if (state.bladeOrgId === orgId) {
    state.bladeOrgId = "";
  }
}

function openOrgCreateModal() {
  openSettingsModal({
    title: "New Organization",
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Name</span>
        <input name="name" type="text" maxlength="120" required placeholder="Organization name" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="2" placeholder="Optional description"></textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Create</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const name = String(formData.get("name") || "").trim();
      if (!name) throw new Error("Organization name cannot be empty");
      const description = String(formData.get("description") || "").trim();
      await createOrganization(name, description);
      await loadWorkgroups();
      renderTree();
      flash("Organization created", "success");
    },
  });
}

function openOrgSettingsModal(orgId) {
  const org = state.organizations.find((o) => o.id === orgId);
  if (!org) {
    flash("Organization not found", "error");
    return;
  }
  const isOwner = state.user && org.owner_id === state.user.id;
  const disabledAttr = isOwner ? "" : "disabled";

  openSettingsModal({
    title: "Organization settings",
    subtitle: org.name,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Name</span>
        <input name="name" type="text" maxlength="120" required value="${escapeHtml(org.name)}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="2" ${disabledAttr}>${escapeHtml(org.description || "")}</textarea>
      </label>
      ${isOwner ? `<div class="settings-danger-zone">
        <button type="button" class="danger" id="delete-org-btn">Delete Organization</button>
        <span class="settings-hint">Workgroups will be ungrouped, not deleted.</span>
      </div>` : ""}
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit" ${disabledAttr}>Save</button>
      </div>
    `,
    onRender: () => {
      const deleteBtn = document.getElementById("delete-org-btn");
      if (deleteBtn) {
        deleteBtn.addEventListener("click", async () => {
          if (!confirm(`Delete organization "${org.name}"? Workgroups will be ungrouped, not deleted.`)) return;
          try {
            await deleteOrganization(orgId);
            closeSettingsModal();
            await loadWorkgroups();
            renderTree();
            flash("Organization deleted", "success");
          } catch (error) {
            flash(error.message, "error");
          }
        });
      }
    },
    onSubmit: async (formData) => {
      if (!isOwner) return;
      const name = String(formData.get("name") || "").trim();
      if (!name) throw new Error("Organization name cannot be empty");
      const description = String(formData.get("description") || "").trim();
      const updated = await updateOrganization(orgId, { name, description });
      // Update org name on workgroups in local state
      for (const wg of state.workgroups) {
        if (wg.organization_id === orgId) wg.organization_name = updated.name;
      }
      for (const data of Object.values(state.treeData)) {
        if (data.workgroup && data.workgroup.organization_id === orgId) {
          data.workgroup.organization_name = updated.name;
        }
      }
      renderTree();
      flash("Organization settings saved", "success");
    },
  });
}

async function openSystemSettingsModal() {
  let config;
  try {
    config = await api("/api/system/settings");
  } catch (error) {
    flash(error.message, "error");
    return;
  }

  const keyPlaceholder = config.anthropic_api_key_set ? "(key is set)" : "Not set";

  openSettingsModal({
    title: "System settings",
    subtitle: config.app_name,
    formHtml: `
      <p class="meta settings-note">Changes apply for this server session. Restart to restore defaults from environment.</p>

      <div class="settings-section-header">LLM Configuration</div>
      <label class="settings-field">
        <span class="settings-label">Default model</span>
        <input name="llm_default_model" type="text" value="${escapeHtml(config.llm_default_model)}" />
        <span class="settings-hint">Model used for agent replies</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">Cheap model</span>
        <input name="llm_cheap_model" type="text" value="${escapeHtml(config.llm_cheap_model)}" />
        <span class="settings-hint">Model used for intent probes and summaries</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">Admin agent model</span>
        <input name="admin_agent_model" type="text" value="${escapeHtml(config.admin_agent_model)}" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Intent probe model</span>
        <input name="intent_probe_model" type="text" value="${escapeHtml(config.intent_probe_model)}" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Anthropic API key</span>
        <input name="anthropic_api_key" type="password" placeholder="${escapeHtml(keyPlaceholder)}" />
        <span class="settings-hint">Leave empty to keep current value</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">Ollama base URL</span>
        <input name="ollama_base_url" type="text" value="${escapeHtml(config.ollama_base_url)}" />
      </label>

      <div class="settings-section-header">Agent Behavior</div>
      <label class="settings-field">
        <span class="settings-label">Agent chain max</span>
        <input name="agent_chain_max" type="number" min="1" max="50" value="${config.agent_chain_max}" />
        <span class="settings-hint">Max agents that can reply in a chain (1–50)</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">SDK max turns</span>
        <input name="agent_sdk_max_turns" type="number" min="1" max="50" value="${config.agent_sdk_max_turns}" />
        <span class="settings-hint">Max tool-use turns per agent reply (1–50)</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">Follow-up scan limit</span>
        <input name="follow_up_scan_limit" type="number" min="10" max="1000" value="${config.follow_up_scan_limit}" />
        <span class="settings-hint">Messages scanned for follow-up triggers (10–1000)</span>
      </label>

      <div class="settings-section-header">Application</div>
      <label class="settings-field">
        <span class="settings-label">App name</span>
        <input name="app_name" type="text" value="${escapeHtml(config.app_name)}" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Workspace root</span>
        <input name="workspace_root" type="text" value="${escapeHtml(config.workspace_root)}" />
        <span class="settings-hint">Base path for workspace file operations</span>
      </label>
      <div class="switch-row">
        <span class="settings-label">Admin agent uses SDK</span>
        <input name="admin_agent_use_sdk" type="checkbox" ${config.admin_agent_use_sdk ? "checked" : ""} />
      </div>

      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Save</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const patch = {};
      const str = (name) => String(formData.get(name) || "").trim();

      if (str("llm_default_model") !== config.llm_default_model) patch.llm_default_model = str("llm_default_model");
      if (str("llm_cheap_model") !== config.llm_cheap_model) patch.llm_cheap_model = str("llm_cheap_model");
      if (str("admin_agent_model") !== config.admin_agent_model) patch.admin_agent_model = str("admin_agent_model");
      if (str("intent_probe_model") !== config.intent_probe_model) patch.intent_probe_model = str("intent_probe_model");
      if (str("ollama_base_url") !== config.ollama_base_url) patch.ollama_base_url = str("ollama_base_url");
      if (str("app_name") !== config.app_name) patch.app_name = str("app_name");
      if (str("workspace_root") !== config.workspace_root) patch.workspace_root = str("workspace_root");

      const apiKey = str("anthropic_api_key");
      if (apiKey) patch.anthropic_api_key = apiKey;

      const chainMax = parseInt(str("agent_chain_max"), 10);
      if (!isNaN(chainMax) && chainMax !== config.agent_chain_max) patch.agent_chain_max = chainMax;
      const sdkMax = parseInt(str("agent_sdk_max_turns"), 10);
      if (!isNaN(sdkMax) && sdkMax !== config.agent_sdk_max_turns) patch.agent_sdk_max_turns = sdkMax;
      const scanLimit = parseInt(str("follow_up_scan_limit"), 10);
      if (!isNaN(scanLimit) && scanLimit !== config.follow_up_scan_limit) patch.follow_up_scan_limit = scanLimit;

      const useSdk = formData.has("admin_agent_use_sdk");
      if (useSdk !== config.admin_agent_use_sdk) patch.admin_agent_use_sdk = useSdk;

      if (Object.keys(patch).length === 0) {
        flash("No changes to save", "info");
        return;
      }

      await api("/api/system/settings", { method: "PATCH", body: patch });
      flash("System settings saved", "success");
    },
  });
}

function openWorkgroupSettings(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    flash("Workgroup data not loaded", "error");
    return;
  }

  const workgroup = data.workgroup;
  const editable = isWorkgroupOwner(workgroupId);
  const disabledAttr = editable ? "" : "disabled";
  const ownerNote = editable
    ? ""
    : "<p class='meta settings-note'>Only workgroup owners can edit these settings.</p>";

  const orgOptions = state.organizations.map((o) => {
    const selected = workgroup.organization_id === o.id ? "selected" : "";
    return `<option value="${escapeHtml(o.id)}" ${selected}>${escapeHtml(o.name)}</option>`;
  }).join("");
  const orgSelectHtml = `
    <label class="settings-field">
      <span class="settings-label">Organization</span>
      <select name="organization_id" ${disabledAttr}>
        <option value=""${!workgroup.organization_id ? " selected" : ""}>No organization (ungrouped)</option>
        ${orgOptions}
      </select>
    </label>
  `;

  openSettingsModal({
    title: "Workgroup settings",
    subtitle: `${workgroup.name} (${workgroup.id.slice(0, 8)})`,
    formHtml: `
      <div class="settings-usage" id="workgroup-usage-section">
        <span class="settings-label">Usage</span>
        <div class="settings-usage-body" id="workgroup-usage-body">Loading usage&hellip;</div>
      </div>
      <label class="settings-field">
        <span class="settings-label">Name</span>
        <input name="name" type="text" maxlength="120" required value="${escapeHtml(workgroup.name)}" ${disabledAttr} />
      </label>
      ${orgSelectHtml}
      <label class="settings-field">
        <span class="settings-label">Discoverable</span>
        <input name="is_discoverable" type="checkbox" ${workgroup.is_discoverable ? "checked" : ""} ${disabledAttr} />
        <span class="settings-hint">Allow other workgroups to find and request tasks from this workgroup</span>
      </label>
      <label class="settings-field">
        <span class="settings-label">Service description</span>
        <textarea name="service_description" rows="2" placeholder="Describe what services this workgroup offers" ${disabledAttr}>${escapeHtml(workgroup.service_description || "")}</textarea>
      </label>
      ${ownerNote}
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit" ${disabledAttr}>Save</button>
      </div>
    `,
    onRender: () => {
      api(`/api/workgroups/${workgroupId}/usage`).then((usage) => {
        const el = document.getElementById("workgroup-usage-body");
        if (!el) return;
        el.textContent = "";
        el.innerHTML =
          `<span>${formatTokenCount(usage.total_tokens)} tokens</span>` +
          `<span>~$${usage.estimated_cost_usd.toFixed(4)}</span>` +
          `<span>${usage.api_calls} API calls</span>` +
          `<span>${formatDuration(usage.total_duration_ms)}</span>`;
      }).catch(() => {
        const el = document.getElementById("workgroup-usage-body");
        if (el) el.textContent = "Unable to load usage";
      });
    },
    onSubmit: async (formData) => {
      if (!editable) {
        return;
      }
      const name = String(formData.get("name") || "").trim();
      if (!name) {
        throw new Error("Workgroup name cannot be empty");
      }
      const isDiscoverable = Boolean(formData.get("is_discoverable"));
      const serviceDescription = String(formData.get("service_description") || "").trim();
      const body = { name, is_discoverable: isDiscoverable, service_description: serviceDescription };
      const selectedOrgId = String(formData.get("organization_id") || "");
      const currentOrgId = workgroup.organization_id || "";
      if (selectedOrgId !== currentOrgId) {
        body.organization_id = selectedOrgId;  // "" to ungroup, org ID to assign
      }
      const updated = await api(`/api/workgroups/${workgroupId}`, {
        method: "PATCH",
        body,
      });
      applyWorkgroupUpdateInState(updated);
      flash("Workgroup settings saved", "success");
    },
  });
}

async function saveWorkgroupFiles(workgroupId, files) {
  const updated = await api(`/api/workgroups/${workgroupId}`, {
    method: "PATCH",
    body: { files },
  });
  applyWorkgroupUpdateInState(updated);
  return updated;
}

function openWorkgroupFileEditor({ title, subtitle, pathValue = "", contentValue = "", pathReadonly = false, onSubmit }) {
  const readonlyAttr = pathReadonly ? "readonly" : "";
  const readonlyNote = pathReadonly ? "<p class='meta settings-note'>Path is read-only in this action.</p>" : "";
  const isMd = isMarkdownFile(pathValue);
  const toolbarHtml = isMd
    ? `<div class="md-toolbar">
        <button type="button" class="md-toolbar-btn" data-md-action="bold" title="Bold"><b>B</b></button>
        <button type="button" class="md-toolbar-btn" data-md-action="italic" title="Italic"><i>I</i></button>
        <button type="button" class="md-toolbar-btn" data-md-action="heading" title="Heading">H</button>
        <button type="button" class="md-toolbar-btn" data-md-action="link" title="Link">Link</button>
        <button type="button" class="md-toolbar-btn" data-md-action="code" title="Inline code">&lt;/&gt;</button>
        <button type="button" class="md-toolbar-btn" data-md-action="codeblock" title="Code block">Code Block</button>
        <button type="button" class="md-toolbar-btn" data-md-action="ul" title="Bullet list">Bullet List</button>
        <button type="button" class="md-toolbar-btn" data-md-action="ol" title="Numbered list">Numbered List</button>
        <div class="md-toolbar-spacer"></div>
        <button type="button" class="md-toolbar-btn md-toolbar-preview-btn" data-md-action="preview">Preview</button>
      </div>`
    : "";
  const previewHtml = isMd
    ? `<div class="md-editor-preview file-overlay-rendered hidden"></div>`
    : "";
  openSettingsModal({
    title,
    subtitle,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Path</span>
        <input name="path" type="text" required maxlength="512" value="${escapeHtml(pathValue)}" ${readonlyAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Content</span>
        ${toolbarHtml}
        <textarea name="content" rows="10" placeholder="File content">${escapeHtml(contentValue)}</textarea>
        ${previewHtml}
      </label>
      ${readonlyNote}
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Save</button>
      </div>
    `,
    onRender: isMd ? (form) => bindMdToolbar(form) : null,
    onSubmit: async (formData) => {
      const path = String(formData.get("path") || "").trim();
      const content = String(formData.get("content") || "");
      if (!path) {
        throw new Error("File path cannot be empty");
      }
      await onSubmit({ path, content });
    },
  });
}

function addWorkgroupFile(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) {
    flash("Workgroup not loaded", "error");
    return;
  }

  openWorkgroupFileEditor({
    title: "Add file",
    subtitle: fileBrowserContextLabel(workgroupId),
    onSubmit: async ({ path, content }) => {
      const files = normalizeWorkgroupFiles(data.workgroup.files);
      const scopedFiles = filesForConversationContext(files, workgroupId);
      const exists = scopedFiles.some((item) => item.path === path);
      if (exists) {
        throw new Error("A file with that path already exists");
      }
      const conversation = conversationById(workgroupId, state.activeConversationId);
      const topic_id = topicIdForConversation(conversation);
      const newFile = { id: newWorkgroupFileId(), path, content, topic_id };
      await saveWorkgroupFiles(workgroupId, [...files, newFile]);
      state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = newFile.id;
      renderTree();
      flash("File added", "success");
    },
  });
}

function editWorkgroupFile(workgroupId) {
  const data = state.treeData[workgroupId];
  const selected = selectedWorkgroupFile(workgroupId);
  if (!data || !selected) {
    flash("Select a file first", "info");
    return;
  }

  openWorkgroupFileEditor({
    title: "Edit file",
    subtitle: `${fileBrowserContextLabel(workgroupId)} · ${selected.path}`,
    pathValue: selected.path,
    contentValue: selected.content,
    pathReadonly: true,
    onSubmit: async ({ content }) => {
      const files = normalizeWorkgroupFiles(data.workgroup.files).map((item) =>
        item.id === selected.id ? { ...item, content } : item,
      );
      await saveWorkgroupFiles(workgroupId, files);
      flash("File updated", "success");
    },
  });
}

function renameWorkgroupFile(workgroupId) {
  const data = state.treeData[workgroupId];
  const selected = selectedWorkgroupFile(workgroupId);
  if (!data || !selected) {
    flash("Select a file first", "info");
    return;
  }

  openSettingsModal({
    title: "Rename file",
    subtitle: `${fileBrowserContextLabel(workgroupId)} · ${selected.path}`,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">New path</span>
        <input name="path" type="text" required maxlength="512" value="${escapeHtml(selected.path)}" />
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Rename</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const renamedPath = String(formData.get("path") || "").trim();
      if (!renamedPath) {
        throw new Error("File path cannot be empty");
      }
      const files = normalizeWorkgroupFiles(data.workgroup.files);
      if (files.some((item) => item.id !== selected.id && item.path === renamedPath)) {
        throw new Error("A file with that path already exists");
      }
      const updatedFiles = files.map((item) => (item.id === selected.id ? { ...item, path: renamedPath } : item));
      await saveWorkgroupFiles(workgroupId, updatedFiles);
      flash("File renamed", "success");
    },
  });
}

function deleteWorkgroupFile(workgroupId) {
  const data = state.treeData[workgroupId];
  const selected = selectedWorkgroupFile(workgroupId);
  if (!data || !selected) {
    flash("Select a file first", "info");
    return;
  }

  const confirmed = window.confirm(`Delete file "${selected.path}"?`);
  if (!confirmed) {
    return;
  }

  const files = normalizeWorkgroupFiles(data.workgroup.files).filter((item) => item.id !== selected.id);
  saveWorkgroupFiles(workgroupId, files)
    .then(() => {
      delete state.selectedWorkgroupFileIdByWorkgroup[workgroupId];
      renderTree();
      flash("File deleted", "success");
    })
    .catch((error) => {
      flash(error.message || "Failed to delete file", "error");
    });
}

function deleteWorkgroupFolder(workgroupId, folderPath) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return;
  }

  const prefix = folderPath + "/";
  const files = normalizeWorkgroupFiles(data.workgroup.files);
  const matchingFiles = files.filter((item) => item.path === folderPath || item.path.startsWith(prefix));

  if (matchingFiles.length === 0) {
    flash("No files in this folder", "info");
    return;
  }

  const confirmed = window.confirm(`Delete folder "${folderPath}" and its ${matchingFiles.length} file(s)?`);
  if (!confirmed) {
    return;
  }

  const matchingIds = new Set(matchingFiles.map((item) => item.id));
  const remainingFiles = files.filter((item) => !matchingIds.has(item.id));

  saveWorkgroupFiles(workgroupId, remainingFiles)
    .then(() => {
      const selectedFileId = state.selectedWorkgroupFileIdByWorkgroup[workgroupId];
      if (selectedFileId && matchingIds.has(selectedFileId)) {
        delete state.selectedWorkgroupFileIdByWorkgroup[workgroupId];
      }
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash(`Folder "${folderPath}" deleted (${matchingFiles.length} file${matchingFiles.length === 1 ? "" : "s"})`, "success");
    })
    .catch((error) => {
      flash(error.message || "Failed to delete folder", "error");
    });
}

// ── File browser CRUD operations ──

function browserAddFile(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) { flash("Workgroup not loaded", "error"); return; }
  const pathPrefix = state.fileBrowserPath.length ? state.fileBrowserPath.join("/") + "/" : "";
  openWorkgroupFileEditor({
    title: "New file",
    subtitle: fileBrowserContextLabel(workgroupId),
    pathValue: pathPrefix,
    onSubmit: async ({ path, content }) => {
      const files = normalizeWorkgroupFiles(data.workgroup.files);
      if (files.some(f => f.path === path)) throw new Error("A file with that path already exists");
      const conversation = conversationById(workgroupId, state.activeConversationId);
      const topic_id = topicIdForConversation(conversation);
      const newFile = { id: newWorkgroupFileId(), path, content, topic_id };
      await saveWorkgroupFiles(workgroupId, [...files, newFile]);
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("File added", "success");
    },
  });
}

function browserNewFolder(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) return;
  const name = window.prompt("Folder name:");
  if (!name || !name.trim()) return;
  const folderName = normalizePathEntry(name.trim());
  if (!folderName) { flash("Invalid folder name", "error"); return; }
  const currentPath = state.fileBrowserPath.join("/");
  const prefix = currentPath ? currentPath + "/" + folderName + "/" : folderName + "/";
  openWorkgroupFileEditor({
    title: "New file in " + folderName,
    subtitle: fileBrowserContextLabel(workgroupId),
    pathValue: prefix,
    onSubmit: async ({ path, content }) => {
      const files = normalizeWorkgroupFiles(data.workgroup.files);
      if (files.some(f => f.path === path)) throw new Error("A file with that path already exists");
      const conversation = conversationById(workgroupId, state.activeConversationId);
      const topic_id = topicIdForConversation(conversation);
      const newFile = { id: newWorkgroupFileId(), path, content, topic_id };
      await saveWorkgroupFiles(workgroupId, [...files, newFile]);
      state.fileBrowserFileId = "";
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("Folder and file created", "success");
    },
  });
}

function browserRenameFile(workgroupId, fileId) {
  const data = state.treeData[workgroupId];
  if (!data) return;
  const files = normalizeWorkgroupFiles(data.workgroup.files);
  const file = files.find(f => f.id === fileId);
  if (!file) return;

  openSettingsModal({
    title: "Rename file",
    subtitle: file.path,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">New path</span>
        <input name="path" type="text" required maxlength="512" value="${escapeHtml(file.path)}" />
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Rename</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const newPath = normalizePathEntry(String(formData.get("path") || "").trim());
      if (!newPath) throw new Error("File path cannot be empty");
      if (files.some(f => f.id !== fileId && f.path === newPath)) {
        throw new Error("A file with that path already exists");
      }
      const updated = files.map(f => f.id === fileId ? { ...f, path: newPath } : f);
      await saveWorkgroupFiles(workgroupId, updated);
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("File renamed", "success");
    },
  });
}

function browserCopyFile(workgroupId, fileId) {
  const data = state.treeData[workgroupId];
  if (!data) return;
  const files = normalizeWorkgroupFiles(data.workgroup.files);
  const file = files.find(f => f.id === fileId);
  if (!file) return;

  const existingPaths = new Set(files.map(f => f.path));
  const dot = file.path.lastIndexOf(".");
  const base = dot > 0 ? file.path.slice(0, dot) : file.path;
  const ext = dot > 0 ? file.path.slice(dot) : "";
  let copyPath = base + " (copy)" + ext;
  let n = 2;
  while (existingPaths.has(copyPath)) {
    copyPath = base + " (copy " + n + ")" + ext;
    n++;
  }

  const newFile = { id: newWorkgroupFileId(), path: copyPath, content: file.content, topic_id: file.topic_id };
  saveWorkgroupFiles(workgroupId, [...files, newFile])
    .then(() => {
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("File copied", "success");
    })
    .catch(error => flash(error.message || "Failed to copy file", "error"));
}

function browserDeleteFile(workgroupId, fileId) {
  const data = state.treeData[workgroupId];
  if (!data) return;
  const files = normalizeWorkgroupFiles(data.workgroup.files);
  const file = files.find(f => f.id === fileId);
  if (!file) return;

  if (!window.confirm(`Delete "${file.path}"?`)) return;

  const remaining = files.filter(f => f.id !== fileId);
  saveWorkgroupFiles(workgroupId, remaining)
    .then(() => {
      if (state.fileBrowserFileId === fileId) state.fileBrowserFileId = "";
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("File deleted", "success");
    })
    .catch(error => flash(error.message || "Failed to delete file", "error"));
}

function browserRenameFolder(workgroupId, folderPath) {
  const data = state.treeData[workgroupId];
  if (!data) return;

  const parts = folderPath.split("/");
  const oldName = parts[parts.length - 1];

  openSettingsModal({
    title: "Rename folder",
    subtitle: folderPath,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">New name</span>
        <input name="name" type="text" required maxlength="256" value="${escapeHtml(oldName)}" />
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Rename</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const newName = normalizePathEntry(String(formData.get("name") || "").trim());
      if (!newName) throw new Error("Folder name cannot be empty");
      const parentPath = parts.slice(0, -1).join("/");
      const newFolderPath = parentPath ? parentPath + "/" + newName : newName;
      if (newFolderPath === folderPath) return;

      const files = normalizeWorkgroupFiles(data.workgroup.files);
      const prefix = folderPath + "/";
      const newPrefix = newFolderPath + "/";

      if (files.some(f => !f.path.startsWith(prefix) && f.path.startsWith(newPrefix))) {
        throw new Error("A folder with that name already exists");
      }

      const updated = files.map(f => {
        if (f.path === folderPath || f.path.startsWith(prefix)) {
          return { ...f, path: newFolderPath + f.path.slice(folderPath.length) };
        }
        return f;
      });
      await saveWorkgroupFiles(workgroupId, updated);
      // Update browser path if we're inside the renamed folder
      const browserPrefix = folderPath.split("/");
      const currentPath = state.fileBrowserPath.join("/");
      if (currentPath === folderPath || currentPath.startsWith(folderPath + "/")) {
        state.fileBrowserPath = newFolderPath.split("/").concat(
          state.fileBrowserPath.slice(browserPrefix.length)
        );
      }
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash("Folder renamed", "success");
    },
  });
}

function browserCopyFolder(workgroupId, folderPath) {
  const data = state.treeData[workgroupId];
  if (!data) return;

  const parts = folderPath.split("/");
  const oldName = parts[parts.length - 1];

  openSettingsModal({
    title: "Copy folder",
    subtitle: folderPath,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">New folder name</span>
        <input name="name" type="text" required maxlength="256" value="${escapeHtml(oldName + " (copy)")}" />
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Copy</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const newName = normalizePathEntry(String(formData.get("name") || "").trim());
      if (!newName) throw new Error("Folder name cannot be empty");
      const parentPath = parts.slice(0, -1).join("/");
      const newFolderPath = parentPath ? parentPath + "/" + newName : newName;

      const files = normalizeWorkgroupFiles(data.workgroup.files);
      const prefix = folderPath + "/";
      const matching = files.filter(f => f.path === folderPath || f.path.startsWith(prefix));
      if (!matching.length) { flash("No files to copy", "info"); return; }

      const copies = matching.map(f => ({
        id: newWorkgroupFileId(),
        path: newFolderPath + f.path.slice(folderPath.length),
        content: f.content,
        topic_id: f.topic_id,
      }));

      const existingPaths = new Set(files.map(f => f.path));
      for (const c of copies) {
        if (existingPaths.has(c.path)) throw new Error(`File "${c.path}" already exists`);
      }

      await saveWorkgroupFiles(workgroupId, [...files, ...copies]);
      if (state.fileBrowserOpen) renderFileBrowser();
      renderTree();
      flash(`Folder copied (${copies.length} file${copies.length !== 1 ? "s" : ""})`, "success");
    },
  });
}

async function ensureAgentLearningsFile(workgroupId, agent) {
  const data = state.treeData[workgroupId];
  if (!data) return;

  const slug = agent.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const filePath = `agents/${slug}-learnings.md`;
  const files = normalizeWorkgroupFiles(data.workgroup?.files);
  let file = files.find((f) => f.path === filePath);

  if (!file) {
    const newFile = {
      id: newWorkgroupFileId(),
      path: filePath,
      content: `# ${agent.name} — Learnings\n\nCapture observations, corrections, and insights for this agent.\n`,
    };
    try {
      await saveWorkgroupFiles(workgroupId, [...files, newFile]);
      file = newFile;
    } catch (err) {
      flash(err.message || "Failed to create learnings file", "error");
      return;
    }
  }

  const admin = data.jobs.find((c) => c.kind === "admin");
  if (admin) {
    await selectConversation(workgroupId, admin.id, `job:${workgroupId}:${admin.id}`);
  }

  state.expandedWorkgroupIds[workgroupId] = true;
  state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = file.id;
  openFileOverlay(workgroupId, file.id);
}

async function ensureWorkgroupConfigFile(workgroupId) {
  const data = state.treeData[workgroupId];
  if (!data) return;

  const wg = data.workgroup;
  const filePath = "workgroup.json";
  const files = normalizeWorkgroupFiles(wg?.files);

  const configData = {
    id: wg.id,
    name: wg.name,
    service_description: wg.service_description || "",
    is_discoverable: !!wg.is_discoverable,
    owner_id: wg.owner_id,
    created_at: wg.created_at,
  };
  const content = JSON.stringify(configData, null, 2);

  let file = files.find((f) => f.path === filePath);
  let needsSave = false;

  if (!file) {
    file = { id: newWorkgroupFileId(), path: filePath, content };
    needsSave = true;
  } else if (file.content !== content) {
    file = { ...file, content };
    needsSave = true;
  }

  if (needsSave) {
    const updatedFiles = files.filter((f) => f.path !== filePath);
    updatedFiles.push(file);
    try {
      await saveWorkgroupFiles(workgroupId, updatedFiles);
    } catch (err) {
      flash(err.message || "Failed to save workgroup config", "error");
      return;
    }
  }

  const admin = data.jobs.find((c) => c.kind === "admin");
  if (admin) {
    await selectConversation(workgroupId, admin.id, `job:${workgroupId}:${admin.id}`);
  }

  state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = file.id;
  openFileOverlay(workgroupId, file.id);
}


async function ensureAgentConfigFile(workgroupId, agent) {
  const data = state.treeData[workgroupId];
  if (!data) return;

  const slug = agent.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const filePath = `agents/${slug}.json`;
  const files = normalizeWorkgroupFiles(data.workgroup?.files);

  const configData = {
    id: agent.id,
    name: agent.name,
    description: agent.description,
    role: agent.role,
    personality: agent.personality,
    backstory: agent.backstory,
    model: agent.model,
    temperature: agent.temperature,
    verbosity: agent.verbosity,
    tool_names: agent.tool_names || [],
    response_threshold: agent.response_threshold,
    follow_up_minutes: agent.follow_up_minutes,
    icon: agent.icon || "",
  };
  const content = JSON.stringify(configData, null, 2);

  let file = files.find((f) => f.path === filePath);
  let needsSave = false;

  if (!file) {
    file = { id: newWorkgroupFileId(), path: filePath, content };
    needsSave = true;
  } else if (file.content !== content) {
    file = { ...file, content };
    needsSave = true;
  }

  if (needsSave) {
    const updatedFiles = files.filter((f) => f.path !== filePath);
    updatedFiles.push(file);
    try {
      await saveWorkgroupFiles(workgroupId, updatedFiles);
    } catch (err) {
      flash(err.message || "Failed to save agent config", "error");
      return;
    }
  }

  const admin = data.jobs.find((c) => c.kind === "admin");
  if (admin) {
    await selectConversation(workgroupId, admin.id, `job:${workgroupId}:${admin.id}`);
  }

  state.expandedWorkgroupIds[workgroupId] = true;
  state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = file.id;
  openFileOverlay(workgroupId, file.id);
}

async function inviteMemberPrompt(workgroupId) {
  const email = prompt("Email address to invite:");
  if (!email || !email.trim()) return;
  try {
    await api(`/api/workgroups/${workgroupId}/invites`, {
      method: "POST",
      body: { email: email.trim() },
    });
    flash(`Invite sent to ${email.trim()}`, "success");
    if (state.treeData[workgroupId]) {
      await refreshWorkgroupTree(state.treeData[workgroupId].workgroup);
      renderTree();
    }
  } catch (error) {
    flash(error.message || "Failed to send invite", "error");
  }
}

function slugify(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function createJobPrompt(workgroupId) {
  const data = state.treeData[workgroupId];
  const workgroupName = data?.workgroup?.name || "Workgroup";
  let keyTouched = false;

  openSettingsModal({
    title: "New job",
    subtitle: `${workgroupName} · New job`,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Display name</span>
        <input name="name" type="text" required maxlength="120" placeholder="e.g. Design Reviews" autofocus />
      </label>
      <label class="settings-field">
        <span class="settings-label">Job key <span class="settings-field-auto" id="job-key-auto">auto</span></span>
        <div class="settings-slug-wrap">
          <input name="topic" type="text" required maxlength="120" class="settings-slug-input" placeholder="job-key" />
        </div>
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="3" placeholder="What's this job about?"></textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Create</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const name = String(formData.get("name") || "").trim();
      const topic = String(formData.get("topic") || "").trim();
      const description = String(formData.get("description") || "").trim();
      if (!name) throw new Error("Display name cannot be empty");
      if (!topic) throw new Error("Job key cannot be empty");

      const result = await api(`/api/workgroups/${workgroupId}/conversations`, {
        method: "POST",
        body: {
          kind: "job",
          topic,
          name,
          description,
          participant_user_ids: [],
          participant_agent_ids: [],
        },
      });
      const treeData = state.treeData[workgroupId];
      if (treeData) {
        await refreshWorkgroupTree(treeData.workgroup);
        renderTree();
      }
      if (result?.id) {
        await selectConversation(workgroupId, result.id, `job:${workgroupId}:${result.id}`);
      }
      flash(`Job "${name}" created`, "success");
    },
    onRender: (form) => {
      const nameInput = form.querySelector("input[name='name']");
      const jobKeyInput = form.querySelector("input[name='topic']");
      const autoIndicator = form.querySelector("#job-key-auto");

      nameInput.addEventListener("input", () => {
        if (!keyTouched) {
          jobKeyInput.value = slugify(nameInput.value);
        }
      });

      jobKeyInput.addEventListener("input", () => {
        if (jobKeyInput.value === "") {
          keyTouched = false;
          if (autoIndicator) autoIndicator.style.display = "";
        } else {
          const expected = slugify(nameInput.value);
          if (jobKeyInput.value !== expected) {
            keyTouched = true;
            if (autoIndicator) autoIndicator.style.display = "none";
          }
        }
      });

      jobKeyInput.addEventListener("focus", () => {
        if (!keyTouched && jobKeyInput.value) {
          keyTouched = true;
          if (autoIndicator) autoIndicator.style.display = "none";
        }
      });
    },
  });
}

function createAgentTaskPrompt(workgroupId, agentId) {
  const data = state.treeData[workgroupId];
  const agent = (data?.agents || []).find((a) => a.id === agentId);
  const agentLabel = agent ? agent.name : "Agent";
  const workgroupName = data?.workgroup?.name || "Workgroup";

  openSettingsModal({
    title: "New task",
    subtitle: `${workgroupName} · ${agentLabel} · New task`,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Title</span>
        <input name="title" type="text" required maxlength="200" placeholder="e.g. Review PR #42" autofocus />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="3" placeholder="Optional details about this task"></textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit">Create</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const title = String(formData.get("title") || "").trim();
      const description = String(formData.get("description") || "").trim();
      if (!title) throw new Error("Title cannot be empty");

      const result = await api(`/api/workgroups/${workgroupId}/agents/${agentId}/tasks`, {
        method: "POST",
        body: { title, description: description || undefined },
      });
      const treeData = state.treeData[workgroupId];
      if (treeData) {
        await refreshWorkgroupTree(treeData.workgroup);
        renderTree();
      }
      if (result?.conversation_id) {
        await selectConversation(workgroupId, result.conversation_id, `task:${workgroupId}:${result.id}`);
      }
      flash(`Task "${title}" created for ${agentLabel}`, "success");
    },
  });
}

function openJobSettings(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  const conversation = data?.jobs.find((item) => item.id === conversationId);
  if (!data || !conversation) {
    flash("Job not found", "error");
    return;
  }

  const editable = conversation.kind === "job";
  const canClearHistory = editable && isWorkgroupOwner(workgroupId);
  const disabledAttr = editable ? "" : "disabled";
  const note = editable
    ? ""
    : "<p class='meta settings-note'>Administration settings are managed by the system.</p>";
  const dangerZone = editable
    ? `<div class="settings-danger-zone">
        <div class="settings-danger-zone-title">Danger zone</div>
        ${canClearHistory
          ? `<button type="button" class="danger" data-action="clear-job-history">Clear history</button>`
          : `<button type="button" class="danger" data-action="clear-job-history" disabled>Clear history</button>
             <p class='meta settings-note'>Only workgroup owners can clear job history.</p>`}
      </div>`
    : "";

  openSettingsModal({
    title: "Job settings",
    subtitle: `${data.workgroup.name} · ${jobDisplayName(conversation)}`,
    formHtml: `
      <div class="job-preview">
        <h2>${escapeHtml(jobDisplayName(conversation))}</h2>
      </div>
      <label class="settings-field">
        <span class="settings-label">Job key</span>
        <div class="settings-slug-wrap">
          <input name="topic" type="text" required maxlength="120" class="settings-slug-input" value="${escapeHtml(conversation.topic || "")}" ${disabledAttr} />
        </div>
      </label>
      <label class="settings-field">
        <span class="settings-label">Display name</span>
        <input name="name" type="text" required maxlength="120" value="${escapeHtml(jobDisplayName(conversation))}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="4" ${disabledAttr}>${escapeHtml(conversation.description || "")}</textarea>
      </label>
      ${note}
      ${dangerZone}
      <div class="settings-actions">
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit" ${disabledAttr}>Save</button>
      </div>
    `,
    onSubmit: async (formData) => {
      if (!editable) {
        return;
      }

      const topic = String(formData.get("topic") || "").trim();
      const name = String(formData.get("name") || "").trim();
      const description = String(formData.get("description") || "").trim();
      if (!topic) {
        throw new Error("Job key cannot be empty");
      }
      if (!name) {
        throw new Error("Display name cannot be empty");
      }

      const updated = await api(`/api/workgroups/${workgroupId}/conversations/${conversationId}`, {
        method: "PATCH",
        body: { topic, name, description },
      });
      applyJobUpdateInState(workgroupId, updated);
      flash("Job settings saved", "success");
    },
    onRender: (form) => {
      const clearButton = form.querySelector("[data-action='clear-job-history']");
      if (!(clearButton instanceof HTMLButtonElement)) {
        return;
      }

      clearButton.addEventListener("click", async () => {
        if (!canClearHistory) {
          return;
        }

        const confirmed = window.confirm(
          `Clear all messages for "${jobDisplayName(conversation)}"? This cannot be undone.`,
        );
        if (!confirmed) {
          return;
        }

        const originalLabel = clearButton.textContent || "Clear history";
        clearButton.disabled = true;
        clearButton.textContent = "Clearing...";

        try {
          const result = await api(`/api/workgroups/${workgroupId}/conversations/${conversationId}/messages`, {
            method: "DELETE",
          });
          if (state.activeConversationId === conversationId) {
            delete state.thinkingByConversation[conversationId];
            await loadMessages();
          }

          const deletedMessages = Number(result?.deleted_messages || 0);
          flash(
            deletedMessages > 0
              ? `Cleared ${deletedMessages} message${deletedMessages === 1 ? "" : "s"} from job history`
              : "Job history is already empty",
            "success",
          );
        } catch (error) {
          flash(error.message || "Failed to clear job history", "error");
        } finally {
          clearButton.disabled = !canClearHistory;
          clearButton.textContent = originalLabel;
        }
      });
    },
  });
}

async function openAgentSettings(workgroupId, agentId) {
  const data = state.treeData[workgroupId];
  const agent = data?.agents.find((item) => item.id === agentId);
  if (!data || !agent) {
    flash("Agent not found", "error");
    return;
  }

  await ensureAgentConfigFile(workgroupId, agent);
}

function renderMemberContactCard(member, isOwner) {
  const container = qs("file-overlay-form");
  container.innerHTML = "";

  // Header with avatar
  const header = document.createElement("div");
  header.className = "cfg-agent-header";
  const avatarEl = document.createElement("div");
  avatarEl.className = "cfg-agent-avatar";
  if (member.picture) {
    avatarEl.innerHTML = `<img src="${escapeHtml(member.picture)}" alt="">`;
  } else {
    avatarEl.innerHTML = generateHumanSvg(member.name || member.email);
  }
  const nameBlock = document.createElement("div");
  nameBlock.innerHTML = `<strong>${escapeHtml(member.name || member.email)}</strong>`;
  if (member.role) nameBlock.innerHTML += `<div class="meta">${escapeHtml(member.role)}</div>`;
  header.appendChild(avatarEl);
  header.appendChild(nameBlock);
  container.appendChild(header);

  // Root section (compatible with collectJsonFromForm)
  const details = document.createElement("details");
  details.className = "json-section json-root";
  details.open = true;
  details.dataset.key = "root";
  details.dataset.type = "object";

  const summary = document.createElement("summary");
  summary.className = "json-section-summary";
  summary.textContent = "root";
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "json-section-body";

  const emit = (el) => { body.appendChild(el); };

  // Identity (read-only)
  emit(buildSectionDivider("Identity"));
  emit(buildScalarField("name", "string", member.name || "", true, ["name"]));
  emit(buildScalarField("email", "string", member.email || "", true, ["email"]));

  // Role & Permissions
  emit(buildSectionDivider("Role & Permissions"));

  const isSelf = member.user_id === state.user?.id;
  const canEditRole = isOwner && !isSelf && member.role !== "owner";

  // Role field — dropdown for editable, plain text for read-only
  const roleLabel = document.createElement("label");
  roleLabel.className = "json-field";
  const roleSpan = document.createElement("span");
  roleSpan.className = "json-field-label";
  roleSpan.textContent = "role";
  roleLabel.appendChild(roleSpan);

  if (canEditRole) {
    const select = document.createElement("select");
    select.dataset.key = "role";
    select.dataset.type = "string";
    for (const r of ["member", "editor"]) {
      const opt = document.createElement("option");
      opt.value = r;
      opt.textContent = r;
      if (r === member.role) opt.selected = true;
      select.appendChild(opt);
    }
    roleLabel.appendChild(select);
  } else {
    const input = document.createElement("input");
    input.type = "text";
    input.value = member.role || "";
    input.disabled = true;
    roleLabel.appendChild(input);
  }
  emit(roleLabel);

  // Budget limit
  const canEditBudget = isOwner && !isSelf;
  emit(buildScalarField("budget_limit_usd", "number", member.budget_limit_usd ?? "", !canEditBudget, ["budget_limit_usd"]));

  // Budget used (always read-only)
  emit(buildScalarField("budget_used_usd", "number", member.budget_used_usd ?? 0, true, ["budget_used_usd"]));

  details.appendChild(body);
  container.appendChild(details);
}

async function saveMemberContactCard() {
  const ctx = state.fileOverlayMemberContext;
  if (!ctx) return;

  const { workgroupId, memberId, originalRole, originalBudgetLimit } = ctx;

  const form = qs("file-overlay-form");
  const roleSelect = form.querySelector('select[data-key="role"]');
  const budgetInput = form.querySelector('input[data-key="budget_limit_usd"]');

  const newRole = roleSelect ? roleSelect.value : originalRole;
  const rawBudget = budgetInput && !budgetInput.disabled ? budgetInput.value : null;
  const newBudgetLimit = rawBudget === "" || rawBudget === null ? null : Number(rawBudget);

  try {
    if (newRole !== originalRole) {
      await api(`/api/workgroups/${workgroupId}/members/${memberId}/role`, {
        method: "PATCH",
        body: { role: newRole },
      });
    }
    if (newBudgetLimit !== originalBudgetLimit) {
      await api(`/api/workgroups/${workgroupId}/members/${memberId}/budget`, {
        method: "PATCH",
        body: { budget_limit_usd: newBudgetLimit },
      });
    }
    flash("Member updated", "success");
    const wg = state.treeData[workgroupId]?.workgroup;
    if (wg) await refreshWorkgroupTree(wg);
    renderTree();
  } catch (err) {
    flash(err.message || "Failed to update member", "error");
  }
}

function openMemberContactCard(workgroupId, memberId) {
  const data = state.treeData[workgroupId];
  const member = data?.members.find((m) => m.user_id === memberId);
  if (!data || !member) {
    flash("Member not found", "error");
    return;
  }

  const isOwner = isWorkgroupOwner(workgroupId);

  qs("file-overlay-path").textContent = `member: ${member.name || member.email}`;
  qs("file-overlay-workgroup").textContent = data.workgroup?.name || "";

  qs("file-overlay-content").classList.add("hidden");
  qs("file-overlay-rendered").innerHTML = "";
  qs("file-overlay-rendered").classList.add("hidden");
  qs("file-overlay-raw-toggle").classList.add("hidden");
  qs("file-overlay-delete").classList.add("hidden");

  state.fileOverlayShowRaw = false;
  state.fileOverlayParsedJson = null;
  state.fileOverlayLastContent = "";
  state.fileOverlayViewMode = "form";

  renderMemberContactCard(member, isOwner);
  setFileOverlayViewMode("form");

  const isSelf = member.user_id === state.user?.id;
  const canEdit = isOwner && !isSelf;
  const editBtn = qs("file-overlay-edit");
  if (canEdit) {
    editBtn.textContent = "Save";
    editBtn.classList.remove("hidden");
  } else {
    editBtn.classList.add("hidden");
  }

  state.fileOverlayMemberContext = {
    workgroupId,
    memberId: member.user_id,
    originalRole: member.role || "",
    originalBudgetLimit: member.budget_limit_usd ?? null,
  };

  qs("file-overlay").classList.remove("hidden");
  showOverlaySplit();
  state.fileOverlayOpen = true;
  state.fileOverlayWorkgroupId = workgroupId;
  state.fileOverlayFileId = "";

  const ctxBar = qs("composer-file-context");
  const label = `member: ${member.name || member.email}`;
  ctxBar.innerHTML = `<span>Viewing: <strong>${escapeHtml(label)}</strong></span><button type="button" class="icon-button" data-action="clear-file-context">\u00d7</button>`;
  ctxBar.classList.remove("hidden");
}

async function refreshWorkgroupTree(workgroup) {
  const isOwner = workgroup.owner_id === state.user?.id;
  const [conversations, members, agents, crossGroupTasks, engagements, invites, jobs, agentTasks] = await Promise.all([
    api(`/api/workgroups/${workgroup.id}/conversations?include_archived=true`),
    api(`/api/workgroups/${workgroup.id}/members`),
    api(`/api/workgroups/${workgroup.id}/agents${isOwner ? "?include_hidden=true" : ""}`),
    api(`/api/workgroups/${workgroup.id}/cross-group-tasks`).catch(() => []),
    api(`/api/workgroups/${workgroup.id}/engagements`).catch(() => []),
    isOwner ? api(`/api/workgroups/${workgroup.id}/invites`).catch(() => []) : Promise.resolve([]),
    api(`/api/workgroups/${workgroup.id}/jobs`).catch(() => []),
    api(`/api/workgroups/${workgroup.id}/agent-tasks`).catch(() => []),
  ]);

  const engagementConversationIds = new Set(
    (engagements || []).flatMap((e) => [e.source_conversation_id, e.target_conversation_id].filter(Boolean))
  );
  const taskConversationIds = new Set(
    (agentTasks || []).map((t) => t.conversation_id).filter(Boolean)
  );
  const jobConversations = conversations.filter((item) => (item.kind === "job" || (item.kind === "admin" && isOwner)) && !engagementConversationIds.has(item.id) && !taskConversationIds.has(item.id));
  const directs = conversations.filter((item) => item.kind === "direct" && !taskConversationIds.has(item.id));
  const taskConversations = conversations.filter((item) => taskConversationIds.has(item.id));
  const engagementConversations = conversations.filter((item) => item.kind === "engagement" || engagementConversationIds.has(item.id));

  const pendingInvites = (invites || []).filter((inv) => inv.status === "pending");

  state.treeData[workgroup.id] = {
    workgroup,
    jobs: jobConversations,
    directs,
    members,
    agents,
    crossGroupTasks: crossGroupTasks || [],
    engagements: engagements || [],
    engagementConversations,
    invites: pendingInvites,
    jobRecords: jobs || [],
    agentTasks: agentTasks || [],
    taskConversations,
  };

  const selectedFileId = state.selectedWorkgroupFileIdByWorkgroup[workgroup.id];
  if (selectedFileId) {
    const files = normalizeWorkgroupFiles(workgroup.files);
    const exists = files.some((item) => item.id === selectedFileId);
    if (!exists) {
      delete state.selectedWorkgroupFileIdByWorkgroup[workgroup.id];
    }
  }
}

function renderTree() {
  const node = qs("treeview");
  const breadcrumb = document.getElementById("blade-breadcrumb");
  const createWrap = document.getElementById("workgroup-create-wrap");
  const addBtn = document.getElementById("new-workgroup-toggle");

  if (!state.workgroups.length) {
    if (breadcrumb) breadcrumb.innerHTML = "<span>Organizations</span>";
    if (createWrap) createWrap.classList.add("hidden-by-blade");
    if (addBtn) addBtn.classList.add("hidden");
    node.innerHTML = "<p class='tree-caption'>Create an organization to get started.</p>";
    updateMetrics();
    return;
  }

  // Partition workgroups by organization (used at multiple levels)
  const orgGroups = new Map();
  for (const wg of state.workgroups) {
    if (wg.organization_id && wg.organization_name) {
      if (!orgGroups.has(wg.organization_id)) {
        orgGroups.set(wg.organization_id, { name: wg.organization_name, workgroups: [] });
      }
      orgGroups.get(wg.organization_id).workgroups.push(wg);
    }
  }

  const renderWgButton = (workgroup) => {
    const activeClass = workgroup.id === state.selectedWorkgroupId ? "active" : "";
    const unreadDot = workgroupHasUnread(workgroup.id) ? `<span class="unread-dot"></span>` : "";
    return `<div class="blade-workgroup-row"><button class="blade-workgroup-item ${activeClass}" data-action="drill-workgroup" data-workgroup="${escapeHtml(workgroup.id)}">${escapeHtml(workgroup.name)}</button>${unreadDot}</div>`;
  };

  const drillId = state.bladeWorkgroupId;
  const drillAgentId = state.bladeAgentId;

  if (drillId && drillAgentId) {
    // ── Level 4: Agent Detail — Tasks ──
    const workgroup = state.workgroups.find((w) => w.id === drillId);
    const data = workgroup ? state.treeData[workgroup.id] : null;
    const agent = data?.agents?.find((a) => a.id === drillAgentId);
    if (!agent || !data) {
      state.bladeAgentId = "";
      renderTree();
      return;
    }

    if (breadcrumb) {
      let crumbs = `<button data-action="blade-back-root" class="blade-crumb-link">Organizations</button>`;
      if (workgroup.organization_id && workgroup.organization_name) {
        crumbs += `<span class="blade-crumb-sep">\u203A</span><button data-action="blade-back" class="blade-crumb-link">${escapeHtml(workgroup.organization_name)}</button>`;
      }
      crumbs += `<span class="blade-crumb-sep">\u203A</span><span>${escapeHtml(agent.name)}</span>`;
      crumbs += `<button class="tree-gear summary" data-action="settings-agent" data-workgroup="${escapeHtml(workgroup.id)}" data-agent="${escapeHtml(agent.id)}" aria-label="Agent settings for ${escapeHtml(agent.name)}">${GEAR_ICON_SVG}</button>`;
      breadcrumb.innerHTML = crumbs;
    }
    if (createWrap) createWrap.classList.add("hidden-by-blade");
    if (addBtn) addBtn.classList.add("hidden");

    const agentTasks = (data.agentTasks || []).filter((t) => t.agent_id === agent.id);
    const taskNodes = agentTasks.length
      ? agentTasks.map((t) => {
          const taskKey = `task:${workgroup.id}:${t.id}`;
          const taskActiveClass = state.activeNodeKey === taskKey ? "active" : "";
          const taskConv = (data.taskConversations || []).find((c) => c.id === t.conversation_id);
          const taskUnreadDot = taskConv && isConversationUnread(taskConv) ? `<span class="unread-dot"></span>` : "";
          return `<div class="tree-item-row">
            <button class="tree-button ${taskActiveClass}" data-action="open-agent-task" data-workgroup="${escapeHtml(workgroup.id)}" data-task-id="${escapeHtml(t.id)}" data-conversation="${escapeHtml(t.conversation_id)}">${escapeHtml(t.title)}<span class="task-badge ${escapeHtml(t.status)}">${escapeHtml(t.status)}</span></button>
            ${taskUnreadDot}
          </div>`;
        }).join("")
      : "<div class='tree-caption'>No tasks</div>";

    node.innerHTML = `
      <div class="tree-section">
        <div class="tree-section-title"><span>Tasks</span><button type="button" class="tree-tool" data-action="new-agent-task" data-workgroup="${escapeHtml(workgroup.id)}" data-agent="${escapeHtml(agent.id)}">+</button></div>
        <div class="tree-list">${taskNodes}</div>
      </div>
    `;
    updateMetrics();
    return;
  }

  if (!drillId && !state.bladeOrgId) {
    // ── Level 1: Root — Organizations ──
    if (breadcrumb) breadcrumb.innerHTML = "<span>Organizations</span>";
    if (createWrap) createWrap.classList.add("hidden-by-blade");
    if (addBtn) addBtn.classList.add("hidden");

    // Invites section
    let invitesHtml = "";
    if (state.myInvites.length > 0) {
      const cards = state.myInvites.map((inv) => {
        const inviterLabel = inv.invited_by_name ? ` by ${escapeHtml(inv.invited_by_name)}` : "";
        return `<div class="invite-card">
          <div class="invite-info">
            <strong>${escapeHtml(inv.workgroup_name || "Unknown workgroup")}</strong>
            <span class="invite-meta">Invited${inviterLabel}</span>
          </div>
          <div class="invite-actions">
            <button type="button" data-action="accept-invite" data-workgroup="${escapeHtml(inv.workgroup_id)}" data-token="${escapeHtml(inv.token)}">Accept</button>
            <button type="button" class="secondary" data-action="decline-invite" data-workgroup="${escapeHtml(inv.workgroup_id)}" data-token="${escapeHtml(inv.token)}">Decline</button>
          </div>
        </div>`;
      }).join("");
      invitesHtml = `<div class="tree-section">
        <div class="tree-section-title"><span>Invites</span><span class="task-badge requested">${state.myInvites.length}</span></div>
        <div class="tree-list">${cards}</div>
      </div>`;
    }

    // Organizations section
    const sortedOrgs = [...orgGroups.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name));
    const orgItems = sortedOrgs.map(([orgId, group]) => {
      const hasUnread = group.workgroups.some((w) => workgroupHasUnread(w.id));
      const unreadDot = hasUnread ? `<span class="unread-dot"></span>` : "";
      return `<div class="tree-item-row">
        <button class="tree-button" data-action="drill-org" data-org="${escapeHtml(orgId)}">${escapeHtml(group.name)}<span class="org-group-count">${group.workgroups.length}</span></button>
        ${unreadDot}
        <button type="button" class="tree-gear" data-action="settings-org" data-org="${escapeHtml(orgId)}" aria-label="Organization settings for ${escapeHtml(group.name)}">${GEAR_ICON_SVG}</button>
      </div>`;
    }).join("");

    const orgsContent = orgItems || "<div class='tree-caption'>No organizations</div>";

    node.innerHTML = `
      ${invitesHtml}
      <div class="tree-section">
        <div class="tree-section-title"><span>Organizations</span><button type="button" class="tree-tool" data-action="new-org">+</button></div>
        <div class="tree-list">${orgsContent}</div>
      </div>
    `;
    updateMetrics();
    return;
  }

  if (state.bladeOrgId && !drillId) {
    // ── Level 2: Org Detail — Workgroups, Engagements, Members ──
    const orgData = orgGroups.get(state.bladeOrgId);
    if (!orgData) {
      state.bladeOrgId = "";
      renderTree();
      return;
    }

    if (breadcrumb) {
      breadcrumb.innerHTML = `<button data-action="blade-back" class="blade-crumb-link">Organizations</button><span class="blade-crumb-sep">\u203A</span><span>${escapeHtml(orgData.name)}</span>`;
    }
    if (createWrap) createWrap.classList.add("hidden-by-blade");
    if (addBtn) addBtn.classList.add("hidden");

    // Workgroups section (exclude org-level Administration workgroup)
    const visibleOrgWorkgroups = orgData.workgroups.filter(wg => wg.name !== "Administration");
    const wgItems = visibleOrgWorkgroups.map((wg) => {
      const unreadDot = workgroupHasUnread(wg.id) ? `<span class="unread-dot"></span>` : "";
      return `<div class="tree-item-row">
        <button class="tree-button" data-action="drill-workgroup" data-workgroup="${escapeHtml(wg.id)}">${escapeHtml(wg.name)}</button>
        ${unreadDot}
        <button type="button" class="tree-gear" data-action="settings-workgroup" data-workgroup="${escapeHtml(wg.id)}" aria-label="Workgroup settings for ${escapeHtml(wg.name)}">${GEAR_ICON_SVG}</button>
      </div>`;
    }).join("");
    const wgContent = wgItems || "<div class='tree-caption'>No workgroups</div>";

    // Engagements — aggregated from all workgroups in this org
    const orgEngagements = [];
    const seenEngagementIds = new Set();
    for (const wg of visibleOrgWorkgroups) {
      const wgData = state.treeData[wg.id];
      if (!wgData?.engagements) continue;
      for (const eng of wgData.engagements) {
        if (seenEngagementIds.has(eng.id)) continue;
        seenEngagementIds.add(eng.id);
        orgEngagements.push({ eng, workgroup: wg });
      }
    }
    const orgEngagementNodes = orgEngagements.length
      ? orgEngagements.map(({ eng, workgroup: wg }) => {
          const convId = eng.source_workgroup_id === wg.id ? eng.source_conversation_id : eng.target_conversation_id;
          const key = `engagement:${wg.id}:${eng.id}`;
          const activeClass = state.activeNodeKey === key ? "active" : "";
          const statusClass = eng.status || "proposed";
          return `<div class="tree-item-row">
            <button class="tree-button ${activeClass}" data-action="open-engagement" data-workgroup="${escapeHtml(wg.id)}" data-engagement="${escapeHtml(eng.id)}" data-conversation="${escapeHtml(convId || "")}">${escapeHtml(eng.title)}<span class="task-badge ${escapeHtml(statusClass)}">${escapeHtml(eng.status)}</span></button>
          </div>`;
        }).join("")
      : "<div class='tree-caption'>No engagements</div>";

    // Members section — humans (deduplicated) then agents, matching workgroup layout
    const seenUserIds = new Set();
    const orgHumans = [];
    for (const wg of visibleOrgWorkgroups) {
      const wgData = state.treeData[wg.id];
      if (!wgData?.members) continue;
      for (const member of wgData.members) {
        if (seenUserIds.has(member.user_id)) continue;
        seenUserIds.add(member.user_id);
        orgHumans.push({ member, workgroup: wg });
      }
    }
    // Owner first, then alphabetical
    const orgRecord = state.organizations.find(o => o.id === state.bladeOrgId);
    const orgOwner = orgRecord?.owner_id || "";
    orgHumans.sort((a, b) => {
      if (a.member.user_id === orgOwner && b.member.user_id !== orgOwner) return -1;
      if (b.member.user_id === orgOwner && a.member.user_id !== orgOwner) return 1;
      return (a.member.name || a.member.email).localeCompare(b.member.name || b.member.email);
    });

    const orgAgents = [];
    for (const wg of visibleOrgWorkgroups) {
      const wgData = state.treeData[wg.id];
      if (!wgData?.agents) continue;
      for (const agent of wgData.agents) {
        if (agent.description === "__system_admin_agent__") continue;
        orgAgents.push({ agent, workgroup: wg });
      }
    }
    orgAgents.sort((a, b) => a.agent.name.localeCompare(b.agent.name));

    const orgMemberNodes = [
      ...orgHumans.map(({ member, workgroup: wg }) => {
        const name = member.name || member.email;
        const isOrgOwner = member.user_id === orgOwner;
        const roleSuffix = isOrgOwner ? " (owner)" : "";
        const selfSuffix = member.user_id === state.user?.id ? " (you)" : "";
        const label = `${escapeHtml(name)}${selfSuffix}${roleSuffix}`;
        const memberAvatar = member.picture
          ? `<span class="tree-avatar human"><img src="${escapeHtml(member.picture)}" alt="" /></span>`
          : `<span class="tree-avatar human">${generateHumanSvg(name)}</span>`;
        const isSelf = member.user_id === state.user?.id;
        const clickableClass = isSelf ? "no-click" : "";
        const action = isSelf ? "" : `data-action="open-member"`;
        const memberDm = !isSelf ? directConversationForMember(wg.id, member.user_id) : null;
        const memberUnreadDot = memberDm && isConversationUnread(memberDm) ? `<span class="unread-dot"></span>` : "";
        return `
          <div class="tree-item-row">
            <button class="tree-button member ${clickableClass}" ${action} data-workgroup="${escapeHtml(wg.id)}" data-member="${escapeHtml(member.user_id)}">
              ${memberAvatar}
              <span>${label}</span>
            </button>
            ${memberUnreadDot}
            <button type="button" class="tree-gear" data-action="settings-member" data-workgroup="${escapeHtml(wg.id)}" data-member="${escapeHtml(member.user_id)}" aria-label="Contact card for ${escapeHtml(name)}">${GEAR_ICON_SVG}</button>
          </div>
        `;
      }),
      ...orgAgents.map(({ agent, workgroup: wg }) => {
        const agentAvatar = agent.icon
          ? `<span class="tree-avatar agent"><img src="${escapeHtml(agent.icon)}" alt="" /></span>`
          : `<span class="tree-avatar agent">${generateBotSvg(agent.name)}</span>`;
        // Aggregate unread from agent's task conversations
        const wgData = state.treeData[wg.id];
        const agentTaskConvs = (wgData?.agentTasks || [])
          .filter((t) => t.agent_id === agent.id && t.conversation_id)
          .map((t) => (wgData.taskConversations || []).find((c) => c.id === t.conversation_id))
          .filter(Boolean);
        const hasUnreadTasks = agentTaskConvs.some((c) => isConversationUnread(c));
        const agentUnreadDot = hasUnreadTasks ? `<span class="unread-dot"></span>` : "";
        return `
          <div class="tree-item-row">
            <button class="tree-button member" data-action="drill-agent" data-workgroup="${escapeHtml(wg.id)}" data-agent="${escapeHtml(agent.id)}">
              ${agentAvatar}
              <span>${escapeHtml(agent.name)}</span>
              <span class="finder-kind">${escapeHtml(wg.name)}</span>
            </button>
            ${agentUnreadDot}
            <button type="button" class="tree-gear" data-action="settings-agent" data-workgroup="${escapeHtml(wg.id)}" data-agent="${escapeHtml(agent.id)}" aria-label="Agent settings for ${escapeHtml(agent.name)}">${GEAR_ICON_SVG}</button>
          </div>
        `;
      }),
    ].join("");

    const orgMemberContent = orgMemberNodes || "<div class='tree-caption'>No members</div>";

    node.innerHTML = `
      <div class="tree-section">
        <div class="tree-section-title"><span>Workgroups</span><button type="button" class="tree-tool" data-action="create-workgroup-in-org" data-org="${escapeHtml(state.bladeOrgId)}">+</button></div>
        <div class="tree-list">${wgContent}</div>
      </div>
      <div class="tree-section">
        <div class="tree-section-title"><span>Engagements</span></div>
        <div class="tree-list">${orgEngagementNodes}</div>
      </div>
      <div class="tree-section">
        <div class="tree-section-title"><span>Members</span></div>
        <div class="tree-list">${orgMemberContent}</div>
      </div>
    `;
    updateMetrics();
    return;
  }

  // ── Level 3: Workgroup Detail ──
  const workgroup = state.workgroups.find((w) => w.id === drillId);
  if (!workgroup) {
    state.bladeWorkgroupId = "";
    renderTree();
    return;
  }

  const data = state.treeData[workgroup.id];
  if (!data) {
    state.bladeWorkgroupId = "";
    renderTree();
    return;
  }

  // Update breadcrumb — Orgs › OrgName › WorkgroupName  or  Orgs › WorkgroupName
  if (breadcrumb) {
    let crumbs = `<button data-action="blade-back-root" class="blade-crumb-link">Organizations</button>`;
    if (workgroup.organization_id && workgroup.organization_name) {
      crumbs += `<span class="blade-crumb-sep">\u203A</span><button data-action="blade-back" class="blade-crumb-link">${escapeHtml(workgroup.organization_name)}</button>`;
    }
    crumbs += `<span class="blade-crumb-sep">\u203A</span><span>${escapeHtml(workgroup.name)}</span>`;
    crumbs += `<button class="tree-gear summary" data-action="settings-workgroup" data-workgroup="${escapeHtml(workgroup.id)}" aria-label="Workgroup settings for ${escapeHtml(workgroup.name)}">${GEAR_ICON_SVG}</button>`;
    breadcrumb.innerHTML = crumbs;
  }

  // Hide create form and + button in detail view
  if (createWrap) createWrap.classList.add("hidden-by-blade");
  if (addBtn) addBtn.classList.add("hidden");

  // Split admin conversation from regular jobs
  const allWorkgroupFiles = normalizeWorkgroupFiles(data.workgroup?.files);
  const adminConversation = data.jobs.find(c => c.kind === "admin");
  const regularJobs = data.jobs.filter(c => c.kind !== "admin");

  // Build a map of Job model records by conversation_id for status badge lookup
  const jobRecordsByConvId = new Map();
  for (const jr of (data.jobRecords || [])) {
    if (jr.conversation_id) jobRecordsByConvId.set(jr.conversation_id, jr);
  }

  // Jobs (excluding admin)
  const jobConvNodes = regularJobs.length
    ? regularJobs
        .map((conversation) => {
          const key = `job:${workgroup.id}:${conversation.id}`;
          const activeClass = state.activeNodeKey === key ? "active" : "";
          const displayName = jobDisplayName(conversation);
          const archived = conversation.is_archived;
          const archivedClass = archived ? " archived" : "";
          const archiveIcon = archived ? `<span class="archive-icon" title="Archived">&#x1f512;</span>` : "";
          const label = escapeHtml(displayName);
          const unreadDot = !archived && isConversationUnread(conversation) ? `<span class="unread-dot"></span>` : "";
          const jobFileCount = allWorkgroupFiles.filter(f => f.topic_id === conversation.id).length;
          const fileBadge = jobFileCount > 0 ? `<button type="button" class="tree-file-count" data-action="open-job-files" data-workgroup="${escapeHtml(workgroup.id)}" data-conversation="${escapeHtml(conversation.id)}">${jobFileCount} file${jobFileCount !== 1 ? "s" : ""}</button>` : "";
          const jobRecord = jobRecordsByConvId.get(conversation.id);
          const statusBadge = jobRecord ? `<span class="task-badge ${escapeHtml(jobRecord.status)}">${escapeHtml(jobRecord.status)}</span>` : "";
          return `
            <div class="tree-item-row${archivedClass}">
              <button class="tree-button ${activeClass}" data-action="open-job" data-workgroup="${escapeHtml(workgroup.id)}" data-conversation="${escapeHtml(conversation.id)}">${archiveIcon}${label}${statusBadge}</button>
              ${unreadDot}
              ${fileBadge}
              <button
                type="button"
                class="tree-gear"
                data-action="settings-job"
                data-workgroup="${escapeHtml(workgroup.id)}"
                data-conversation="${escapeHtml(conversation.id)}"
                aria-label="Job settings for ${escapeHtml(displayName)}"
              >${GEAR_ICON_SVG}</button>
            </div>
          `;
        })
        .join("")
    : "<div class='tree-caption'>No jobs</div>";

  // Members — unified list: humans first (owner at top), then agents (as navigators)
  const sortedHumans = [...data.members].sort((a, b) => {
    if (a.role === "owner" && b.role !== "owner") return -1;
    if (b.role === "owner" && a.role !== "owner") return 1;
    return (a.name || a.email).localeCompare(b.name || b.email);
  });
  const sortedAgents = (data.agents || [])
    .filter((agent) => agent.description !== "__system_admin_agent__")
    .sort((a, b) => a.name.localeCompare(b.name));

  const pendingInvites = isWorkgroupOwner(workgroup.id) ? (data.invites || []) : [];

  const memberNodes = [
    ...sortedHumans.map((member) => {
      const name = member.name || member.email;
      const roleSuffix = member.role === "owner" ? " (owner)" : "";
      const selfSuffix = member.user_id === state.user?.id ? " (you)" : "";
      const label = `${escapeHtml(name)}${selfSuffix}${roleSuffix}`;
      const memberAvatar = member.picture
        ? `<span class="tree-avatar human"><img src="${escapeHtml(member.picture)}" alt="" /></span>`
        : `<span class="tree-avatar human">${generateHumanSvg(name)}</span>`;
      const isSelf = member.user_id === state.user?.id;
      const key = `member:${workgroup.id}:${member.user_id}`;
      const activeClass = !isSelf && state.activeNodeKey === key ? "active" : "";
      const action = isSelf ? "" : `data-action="open-member"`;
      const clickableClass = isSelf ? "no-click" : "";
      const memberDm = !isSelf ? directConversationForMember(workgroup.id, member.user_id) : null;
      const memberUnreadDot = memberDm && isConversationUnread(memberDm) ? `<span class="unread-dot"></span>` : "";
      const memberTopicId = memberDm ? topicIdForConversation(memberDm) : "";
      const memberFileCount = memberTopicId ? allWorkgroupFiles.filter(f => f.topic_id === memberTopicId).length : 0;
      const memberFileBadge = memberFileCount > 0 ? `<button type="button" class="tree-file-count" data-action="open-dm-files" data-workgroup="${escapeHtml(workgroup.id)}" data-member="${escapeHtml(member.user_id)}">${memberFileCount} file${memberFileCount !== 1 ? "s" : ""}</button>` : "";
      return `
        <div class="tree-item-row">
          <button class="tree-button member ${clickableClass} ${activeClass}" ${action} data-workgroup="${escapeHtml(workgroup.id)}" data-member="${escapeHtml(member.user_id)}">${memberAvatar}<span>${label}</span></button>
          ${memberUnreadDot}
          ${memberFileBadge}
          <button
            type="button"
            class="tree-gear"
            data-action="settings-member"
            data-workgroup="${escapeHtml(workgroup.id)}"
            data-member="${escapeHtml(member.user_id)}"
            aria-label="Contact card for ${escapeHtml(name)}"
          >${GEAR_ICON_SVG}</button>
        </div>
      `;
    }),
    ...sortedAgents.map((agent) => {
      const agentAvatar = agent.icon
        ? `<span class="tree-avatar agent"><img src="${escapeHtml(agent.icon)}" alt="" /></span>`
        : `<span class="tree-avatar agent">${generateBotSvg(agent.name)}</span>`;
      // Aggregate unread from agent's task conversations
      const agentTaskConvs = (data.agentTasks || [])
        .filter((t) => t.agent_id === agent.id && t.conversation_id)
        .map((t) => (data.taskConversations || []).find((c) => c.id === t.conversation_id))
        .filter(Boolean);
      const hasUnreadTasks = agentTaskConvs.some((c) => isConversationUnread(c));
      const agentUnreadDot = hasUnreadTasks ? `<span class="unread-dot"></span>` : "";
      return `
        <div class="tree-item-row">
          <button class="tree-button member" data-action="drill-agent" data-workgroup="${escapeHtml(workgroup.id)}" data-agent="${escapeHtml(agent.id)}">
            ${agentAvatar}
            <span>${escapeHtml(agent.name)}</span>
          </button>
          ${agentUnreadDot}
          <button
            type="button"
            class="tree-gear"
            data-action="settings-agent"
            data-workgroup="${escapeHtml(workgroup.id)}"
            data-agent="${escapeHtml(agent.id)}"
            aria-label="Agent settings for ${escapeHtml(agent.name)}"
          >${GEAR_ICON_SVG}</button>
        </div>
      `;
    }),
    ...pendingInvites.map((inv) => {
      const invAvatar = `<span class="tree-avatar human">${generateHumanSvg(inv.email)}</span>`;
      return `
        <div class="tree-item-row invite-pending">
          <button class="tree-button member no-click" data-workgroup="${escapeHtml(workgroup.id)}">
            ${invAvatar}
            <span>${escapeHtml(inv.email)}</span>
            <span class="task-badge requested">invited</span>
          </button>
          <button
            type="button"
            class="tree-gear danger"
            data-action="cancel-invite"
            data-workgroup="${escapeHtml(workgroup.id)}"
            data-invite-id="${escapeHtml(inv.id)}"
            aria-label="Cancel invite for ${escapeHtml(inv.email)}"
          >&times;</button>
        </div>
      `;
    }),
  ].join("");

  // Engagements section
  const engagementItems = (data.engagements || []);
  const engagementNodes = engagementItems.length
    ? engagementItems.map((eng) => {
        // Find the conversation for this engagement in this workgroup
        const convId = eng.source_workgroup_id === workgroup.id ? eng.source_conversation_id : eng.target_conversation_id;
        const key = `engagement:${workgroup.id}:${eng.id}`;
        const activeClass = state.activeNodeKey === key ? "active" : "";
        const statusClass = eng.status || "proposed";
        return `
          <div class="tree-item-row">
            <button class="tree-button ${activeClass}" data-action="open-engagement" data-workgroup="${escapeHtml(workgroup.id)}" data-engagement="${escapeHtml(eng.id)}" data-conversation="${escapeHtml(convId || "")}">${escapeHtml(eng.title)}<span class="task-badge ${escapeHtml(statusClass)}">${escapeHtml(eng.status)}</span></button>
          </div>
        `;
      }).join("")
    : "<div class='tree-caption'>No engagements</div>";

  const html = `
    <div class="tree-section">
      <div class="tree-section-title"><span>Jobs</span><button type="button" class="tree-tool" data-action="create-job" data-workgroup="${escapeHtml(workgroup.id)}">+</button></div>
      <div class="tree-list">${jobConvNodes}</div>
    </div>

    <div class="tree-section">
      <div class="tree-section-title"><span>Engagements</span><button type="button" class="tree-tool" data-action="propose-engagement" data-workgroup="${escapeHtml(workgroup.id)}">+</button></div>
      <div class="tree-list">${engagementNodes}</div>
    </div>

    <div class="tree-section">
      <div class="tree-section-title"><span>Members</span>${isWorkgroupOwner(workgroup.id) ? `<button type="button" class="tree-tool" data-action="invite-member" data-workgroup="${escapeHtml(workgroup.id)}">+</button>` : ""}</div>
      <div class="tree-list">${memberNodes || "<div class='tree-caption'>No members</div>"}</div>
    </div>
  `;

  node.innerHTML = html;
  updateMetrics();
}

async function loadMyInvites() {
  try {
    state.myInvites = await api("/api/invites/mine");
  } catch {
    state.myInvites = [];
  }
}

async function loadWorkgroups() {
  state.workgroups = await api("/api/workgroups");
  await loadOrganizations();
  state.treeData = {};
  const workgroupIds = new Set(state.workgroups.map((workgroup) => workgroup.id));
  state.expandedWorkgroupIds = Object.fromEntries(
    Object.entries(state.expandedWorkgroupIds).filter(([workgroupId, expanded]) => expanded && workgroupIds.has(workgroupId))
  );
  if (state.bladeWorkgroupId && !workgroupIds.has(state.bladeWorkgroupId)) {
    state.bladeWorkgroupId = "";
    state.bladeAgentId = "";
  }
  if (state.bladeOrgId) {
    const orgStillExists = state.workgroups.some((w) => w.organization_id === state.bladeOrgId);
    if (!orgStillExists) {
      state.bladeOrgId = "";
      state.bladeAgentId = "";
    }
  }

  await Promise.all(state.workgroups.map((workgroup) => refreshWorkgroupTree(workgroup)));

  if (!state.workgroups.length) {
    state.selectedWorkgroupId = "";
    clearActiveConversationUI();
    renderTree();
    return;
  }

  // If user had no active conversation, don't force-select one
  if (!state.activeConversationId) {
    renderTree();
    return;
  }

  let targetWorkgroupId = state.selectedWorkgroupId;
  if (!targetWorkgroupId || !state.treeData[targetWorkgroupId]) {
    // The workgroup the user was viewing no longer exists — clear selection
    clearActiveConversationUI();
    renderTree();
    return;
  }

  const existingConversation = conversationById(targetWorkgroupId, state.activeConversationId);
  if (!existingConversation) {
    // The conversation the user was viewing no longer exists — clear selection
    clearActiveConversationUI();
    renderTree();
    return;
  }

  const targetNodeKey = nodeKeyForConversation(targetWorkgroupId, existingConversation);
  state.activeNodeKey = targetNodeKey || state.activeNodeKey;
  refreshActiveConversationHeader();
  renderTree();
  if (state.activeMessages.length) {
    renderMessages(state.activeMessages);
  }
}

async function selectConversation(workgroupId, conversationId, nodeKey = "") {
  closeFileOverlay();

  state.selectedWorkgroupId = workgroupId;
  state.activeConversationId = conversationId;
  state.activeNodeKey = nodeKey;
  state.usagePollCounter = 0;

  // Mark conversation as read
  const prefs = (state.user && state.user.preferences) || {};
  const lastRead = { ...(prefs.conversationLastRead || {}), [conversationId]: new Date().toISOString() };
  savePreferences({ conversationLastRead: lastRead });

  refreshActiveConversationHeader();

  renderTree();
  await loadMessages();
  loadConversationUsage(conversationId);
}

async function openMemberConversation(workgroupId, memberUserId) {
  const conversation = await api(`/api/workgroups/${workgroupId}/members/${memberUserId}/direct-conversation`, {
    method: "POST",
  });

  await refreshWorkgroupTree(state.treeData[workgroupId].workgroup);
  await selectConversation(workgroupId, conversation.id, `member:${workgroupId}:${memberUserId}`);
}


async function openAgentConversation(workgroupId, agentId) {
  const conversation = await api(`/api/workgroups/${workgroupId}/agents/${agentId}/direct-conversation`, {
    method: "POST",
  });

  await refreshWorkgroupTree(state.treeData[workgroupId].workgroup);
  await selectConversation(workgroupId, conversation.id, `agent:${workgroupId}:${agentId}`);
}

function renderMessages(messages) {
  const node = qs("messages");
  state.activeMessages = messages;
  syncThinkingState(messages);
  const pending = state.thinkingByConversation[state.activeConversationId];

  const activeConv = conversationById(state.selectedWorkgroupId, state.activeConversationId);
  const isDm = activeConv?.kind === "direct";
  qs("chat-header-actions").classList.toggle("hidden", !messages.length && !isDm);

  if (!messages.length && !pending) {
    node.innerHTML = "<p class='meta'>No messages yet.</p>";
    updateMetrics();
    return;
  }

  const messageHtml = messages
    .map((message) => {
      let rowClass = message.sender_type === "system" ? "system" : message.sender_type === "agent" ? "agent" : "user";

      // Team message styling
      if (message.sender_type === "system") {
        if (message.content.startsWith("[Tool]")) {
          rowClass += " team-tool-use";
        } else if (message.content.startsWith("[System]") || message.content.startsWith("[Job")) {
          rowClass += " team-system";
        }
      }

      const wgId = state.selectedWorkgroupId;
      const wgData = state.treeData[wgId];
      let avatarContent;
      if (message.sender_type === "agent" && message.sender_agent_id && wgData) {
        const msgAgent = wgData.agents?.find((a) => a.id === message.sender_agent_id);
        if (msgAgent?.icon) {
          avatarContent = `<img src="${escapeHtml(msgAgent.icon)}" alt="" />`;
        } else {
          const name = msgAgent?.name || agentName(wgId, message.sender_agent_id);
          avatarContent = generateBotSvg(name);
        }
      } else if (message.sender_type === "user" && message.sender_user_id && wgData) {
        const msgMember = wgData.members?.find((m) => m.user_id === message.sender_user_id);
        if (msgMember?.picture) {
          avatarContent = `<img src="${escapeHtml(msgMember.picture)}" alt="" />`;
        } else {
          const name = msgMember?.name || msgMember?.email || memberName(wgId, message.sender_user_id);
          avatarContent = generateHumanSvg(name);
        }
      } else if (message.sender_type === "system") {
        avatarContent = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#8da3a6"/><text x="16" y="16" text-anchor="middle" dominant-baseline="central" fill="#fff" font-family="sans-serif" font-weight="700" font-size="10">SYS</text></svg>`;
      } else {
        avatarContent = message.sender_type === "agent"
          ? generateBotSvg(senderLabel(wgId, message))
          : generateHumanSvg(senderLabel(wgId, message));
      }
      return `
        <article class="message-row ${rowClass}">
          <div class="avatar">${avatarContent}</div>
          <div>
            <div class="message-meta"><span class="sender">${escapeHtml(senderLabel(wgId, message))}</span>${escapeHtml(new Date(message.created_at).toLocaleString())}</div>
            <div class="message-text">${message.sender_type === "system" ? '<span class="synced-badge">[synced]</span> ' : ''}${(() => { const fc = parseFileContext(message.content); if (fc) return `<div class="message-file-context" onclick="this.classList.toggle('expanded')"><span class="message-file-context-toggle">\u{1F4CE} ${escapeHtml(fc.path)}</span><pre class="message-file-context-content">${escapeHtml(fc.fileContent)}</pre></div>${linkifyUrls(escapeHtml(fc.message))}`; return linkifyUrls(escapeHtml(message.content)); })()}</div>${message.sender_type === "agent" && isShowAgentThoughts() && state.thoughtsByMessageId[message.id] ? renderThoughtsSection(state.thoughtsByMessageId[message.id]) : ""}
          </div>
        </article>
      `;
    })
    .join("");
  const thinkingHtml = pending ? renderThinkingRows(state.selectedWorkgroupId, pending) : "";

  node.innerHTML = messageHtml + thinkingHtml;

  node.scrollTop = node.scrollHeight;
  updateMetrics();
}

async function copyChatToClipboard() {
  const messages = state.activeMessages;
  if (!messages || !messages.length) {
    flash("No messages to copy", "info");
    return;
  }
  const wgId = state.selectedWorkgroupId;
  const lines = messages.map((message) => {
    const sender = senderLabel(wgId, message);
    const time = new Date(message.created_at).toLocaleString();
    const fc = parseFileContext(message.content);
    const text = fc ? fc.message : message.content;
    return `${sender} (${time}):\n${text}`;
  });
  try {
    await navigator.clipboard.writeText(lines.join("\n\n"));
    flash("Chat copied to clipboard", "success");
  } catch {
    flash("Failed to copy to clipboard", "error");
  }
}

async function loadMessages() {
  if (!state.activeConversationId) {
    renderMessages([]);
    return [];
  }

  const messages = await api(`/api/conversations/${state.activeConversationId}/messages`);
  if (isShowAgentThoughts()) {
    const agentMsgIds = messages.filter((m) => m.sender_type === "agent").map((m) => m.id);
    if (agentMsgIds.length) await loadThoughtsForMessages(agentMsgIds);
  }
  renderMessages(messages);
  return messages;
}

async function pollMessages() {
  if (!state.activeConversationId) {
    return state.activeMessages;
  }

  const existing = state.activeMessages.filter((m) => !m.id.startsWith("local-"));
  const sinceId = existing.length ? existing[existing.length - 1].id : "";
  const url = sinceId
    ? `/api/conversations/${state.activeConversationId}/messages?since_id=${encodeURIComponent(sinceId)}`
    : `/api/conversations/${state.activeConversationId}/messages`;

  const newMessages = await api(url, { retries: 0, timeout: 10000 });
  if (!newMessages.length) {
    return state.activeMessages;
  }

  const existingIds = new Set(state.activeMessages.map((m) => m.id));
  const optimistic = state.activeMessages.filter((m) => m.id.startsWith("local-"));
  const merged = [...existing, ...newMessages.filter((m) => !existingIds.has(m.id)), ...optimistic];
  renderMessages(merged);
  return merged;
}

function formatTokenCount(count) {
  if (count >= 1_000_000) return (count / 1_000_000).toFixed(1) + "M";
  if (count >= 1_000) return (count / 1_000).toFixed(1) + "k";
  return String(count);
}

function formatDuration(ms) {
  if (ms < 1000) return ms + "ms";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return hours + "h " + minutes + "m";
  if (minutes > 0) return minutes + "m " + seconds + "s";
  return seconds + "s";
}

async function loadConversationUsage(conversationId) {
  const el = qs("active-usage");
  if (!conversationId) {
    state.conversationUsage = null;
    if (el) el.classList.add("hidden");
    return;
  }
  try {
    const data = await api(`/api/conversations/${conversationId}/usage`);
    state.conversationUsage = data;
    if (el && data.api_calls > 0) {
      el.innerHTML =
        '<span class="usage-stat"><span class="usage-label">elapsed</span><span class="usage-value">' +
        formatDuration(data.total_duration_ms) +
        '</span></span><span class="usage-dot"></span><span class="usage-stat"><span class="usage-label">cost</span><span class="usage-value">$' +
        data.estimated_cost_usd.toFixed(4) +
        '</span></span><span class="usage-dot"></span><span class="usage-stat"><span class="usage-label">tokens</span><span class="usage-value">' +
        formatTokenCount(data.total_tokens) +
        "</span></span>";
      el.classList.remove("hidden");
    } else if (el) {
      el.classList.add("hidden");
    }
  } catch {
    if (el) el.classList.add("hidden");
  }
}

const POLL_BASE_INTERVAL = 4000;
const POLL_MAX_INTERVAL = 60000;

function startPolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
  }
  state.pollConsecutiveErrors = 0;

  async function pollOnce() {
    if (!state.token) {
      state.pollTimer = setTimeout(pollOnce, POLL_BASE_INTERVAL);
      return;
    }

    try {
      const beforeLatestId = state.activeMessages.length ? state.activeMessages[state.activeMessages.length - 1].id : "";
      const shouldWatchTree =
        Boolean(state.selectedWorkgroupId) &&
        Boolean(state.activeConversationId) &&
        isAdminConversation(state.selectedWorkgroupId, state.activeConversationId);

      try {
        await api("/api/agents/tick", { method: "POST", retries: 0, timeout: 10000 });
      } catch (_) { /* tick failure must not block message/activity polling */ }
      let polledMessages = [];
      if (state.activeConversationId) {
        polledMessages = await pollMessages();
        state.usagePollCounter = (state.usagePollCounter || 0) + 1;
        if (state.usagePollCounter >= 8) {
          state.usagePollCounter = 0;
          loadConversationUsage(state.activeConversationId);
        }

        // Poll live activity when agents are thinking.
        const pending = state.thinkingByConversation[state.activeConversationId];
        if (pending) {
          try {
            const activity = await api(`/api/conversations/${state.activeConversationId}/activity`, { retries: 0, timeout: 5000 });
            const prev = JSON.stringify(state.lastLiveActivity);
            const next = JSON.stringify(activity);
            if (prev !== next) {
              state.lastLiveActivity = activity;
              pending.liveActivity = activity.length ? activity : null;
              // Reset the inactivity timer when agents are actively working.
              if (activity.length) {
                pending.lastActivityAtMs = Date.now();
              }
              renderMessages(state.activeMessages);
            }
          } catch (_) { /* skip on error */ }
        } else {
          state.lastLiveActivity = null;
        }

        // Load thoughts for new agent messages when preference is on.
        if (isShowAgentThoughts() && polledMessages.length) {
          const agentMsgIds = polledMessages
            .filter((m) => m.sender_type === "agent" && !state.thoughtsByMessageId[m.id])
            .map((m) => m.id);
          if (agentMsgIds.length) {
            await loadThoughtsForMessages(agentMsgIds);
            renderMessages(state.activeMessages);
          }
        }
      }

      if (state.fileOverlayOpen && polledMessages.length) {
        const currentLatestId = polledMessages[polledMessages.length - 1].id;
        if (currentLatestId && currentLatestId !== beforeLatestId) {
          const lastNew = polledMessages[polledMessages.length - 1];
          const senderName = senderLabel(state.selectedWorkgroupId, lastNew);
          flash(`New message from ${senderName}`, "info");
        }
      }

      // Poll invites every ~32s (8 cycles × 4s)
      state.invitePollCounter = (state.invitePollCounter || 0) + 1;
      if (state.invitePollCounter >= 8) {
        state.invitePollCounter = 0;
        const prevCount = state.myInvites.length;
        await loadMyInvites();
        if (state.myInvites.length > prevCount) {
          flash("You have new workgroup invites", "info");
        }
        renderTree();
      }

      // Keep lastRead current for the conversation the user is actively viewing
      if (state.activeConversationId && polledMessages.length) {
        const prefs = (state.user && state.user.preferences) || {};
        const curRead = prefs.conversationLastRead && prefs.conversationLastRead[state.activeConversationId];
        const latestMsg = polledMessages[polledMessages.length - 1];
        if (latestMsg && latestMsg.sender_user_id !== state.user?.id) {
          const msgTime = parseAsUTC(latestMsg.created_at);
          if (!curRead || msgTime > parseAsUTC(curRead)) {
            const lastRead = { ...(prefs.conversationLastRead || {}), [state.activeConversationId]: new Date().toISOString() };
            savePreferences({ conversationLastRead: lastRead });
          }
        }
      }

      // Refresh unread indicators — conversations only (lightweight)
      state.treePollCounter = (state.treePollCounter || 0) + 1;
      const drillWg = state.bladeWorkgroupId && state.treeData[state.bladeWorkgroupId];
      if (drillWg) {
        // Drilled into a workgroup: refresh conversations every cycle (~4s)
        try {
          const convs = await api(`/api/workgroups/${state.bladeWorkgroupId}/conversations?include_archived=true`);
          const data = state.treeData[state.bladeWorkgroupId];
          if (data) {
            const taskConvIds = new Set((data.agentTasks || []).map(t => t.conversation_id).filter(Boolean));
            data.jobs = convs.filter((c) => c.kind === "job" || c.kind === "admin");
            data.taskConversations = convs.filter(c => taskConvIds.has(c.id));
            data.directs = convs.filter((c) => c.kind === "direct" && !taskConvIds.has(c.id));
          }
          renderTree();
        } catch (_) { /* skip on error */ }
      } else if (!state.bladeWorkgroupId && state.treePollCounter >= 4) {
        // List view: refresh all workgroups every ~16s
        state.treePollCounter = 0;
        try {
          await Promise.all(state.workgroups.map(async (wg) => {
            const convs = await api(`/api/workgroups/${wg.id}/conversations?include_archived=true`);
            const data = state.treeData[wg.id];
            if (data) {
              const taskConvIds = new Set((data.agentTasks || []).map(t => t.conversation_id).filter(Boolean));
              data.jobs = convs.filter((c) => c.kind === "job" || c.kind === "admin");
              data.taskConversations = convs.filter(c => taskConvIds.has(c.id));
              data.directs = convs.filter((c) => c.kind === "direct" && !taskConvIds.has(c.id));
            }
          }));
          renderTree();
        } catch (_) { /* skip on error */ }
      }

      if (shouldWatchTree) {
        const afterLatestId = polledMessages.length ? polledMessages[polledMessages.length - 1].id : "";
        if (afterLatestId && afterLatestId !== beforeLatestId) {
          await loadWorkgroups();
        }
      }

      // Refresh workgroup files when new agent messages arrive (agents may create/edit files).
      if (!shouldWatchTree && state.selectedWorkgroupId) {
        const afterLatestId = polledMessages.length ? polledMessages[polledMessages.length - 1].id : "";
        if (afterLatestId && afterLatestId !== beforeLatestId) {
          try {
            const fresh = await api(`/api/workgroups/${state.selectedWorkgroupId}`);
            const data = state.treeData[state.selectedWorkgroupId];
            if (data) {
              data.workgroup = fresh;
              if (state.fileBrowserOpen) renderFileBrowser();
            }
          } catch (_) { /* skip on error */ }
        }
      }

      state.pollConsecutiveErrors = 0;
      state.pollTimer = setTimeout(pollOnce, POLL_BASE_INTERVAL);
    } catch (error) {
      console.error(error);
      if (error && error.status === 401) {
        return;
      }
      state.pollConsecutiveErrors = (state.pollConsecutiveErrors || 0) + 1;
      try {
        await loadWorkgroups();
      } catch (reloadError) {
        console.error(reloadError);
      }
      const backoff = Math.min(POLL_MAX_INTERVAL, POLL_BASE_INTERVAL * Math.pow(2, state.pollConsecutiveErrors));
      state.pollTimer = setTimeout(pollOnce, backoff);
    }
  }

  state.pollTimer = setTimeout(pollOnce, POLL_BASE_INTERVAL);
}

function stopPolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

document.addEventListener("visibilitychange", () => {
  if (!state.token) return;
  if (document.hidden) {
    stopPolling();
  } else {
    startPolling();
  }
});

window.addEventListener("offline", () => {
  stopPolling();
});

window.addEventListener("online", () => {
  if (state.token) {
    startPolling();
  }
});

async function loginWithGoogleCredential(credential) {
  const auth = await api("/api/auth/google", {
    method: "POST",
    body: { id_token: credential },
  });

  await setSignedIn(auth.user, auth.access_token);
  flash("Google login successful", "success");
}

async function setSignedIn(user, token) {
  state.user = user;
  state.token = token;
  sessionStorage.setItem("teaparty_token", token);
  localStorage.setItem("teaparty_token", token);

  // Apply server-side preferences
  const prefs = user.preferences || {};
  if (prefs.theme) {
    applyTheme(prefs.theme, false);
    localStorage.setItem(THEME_STORAGE_KEY, prefs.theme);
  }
  if (prefs.bladeWidth) {
    const layout = document.querySelector(".layout");
    if (layout) {
      layout.style.setProperty("--blade-width", prefs.bladeWidth + "px");
    }
  }
  if (prefs.overlayHeight) {
    document.getElementById("chat-panel").style.setProperty(
      "--overlay-height", prefs.overlayHeight + "px"
    );
  }
  if (prefs.showAgentThoughts) {
    const el = qs("thoughts-toggle");
    if (el) el.checked = true;
  }

  updateAuthUI();
  closeUserMenu();
  try {
    await loadWorkgroupTemplates();
  } catch (error) {
    console.error(error);
    state.workgroupTemplates = [];
    state.workgroupCreateTemplateKey = "";
    state.workgroupCreateFiles = [];
    state.workgroupCreateAgents = [];
    renderWorkgroupCreateEditor();
  }
  // Reset blade navigation so every sign-in starts at Organizations root
  state.bladeOrgId = "";
  state.bladeWorkgroupId = "";
  state.bladeAgentId = "";

  await loadMyInvites();
  await loadOrganizations();
  await loadWorkgroups();
  startPolling();
}

function signOut() {
  stopPolling();

  state.user = null;
  state.token = "";
  state.workgroups = [];
  state.treeData = {};
  state.workgroupTemplates = [];
  state.workgroupCreateTemplateKey = "";
  state.workgroupCreateFiles = [];
  state.workgroupCreateAgents = [];
  state.selectedWorkgroupId = "";
  state.bladeOrgId = "";
  state.bladeWorkgroupId = "";
  state.bladeAgentId = "";
  state.activeConversationId = "";
  state.activeNodeKey = "";
  state.selectedWorkgroupFileIdByWorkgroup = {};
  state.activeMessages = [];
  state.thinkingByConversation = {};
  state.thoughtsByMessageId = {};
  state.lastLiveActivity = null;
  state.fileOverlayOpen = false;
  state.fileOverlayWorkgroupId = "";
  state.fileOverlayFileId = "";
  state.fileOverlayShowRaw = false;
  state.myInvites = [];
  state.invitePollCounter = 0;

  sessionStorage.removeItem("teaparty_token");
  localStorage.removeItem("teaparty_token");

  closeFileOverlay();
  renderTree();
  renderMessages([]);
  setTextIfPresent("active-conversation", "No active conversation");
  setTextIfPresent("active-context", "Use the tree to open a job, member DM, or administration conversation.");
  renderWorkgroupCreateEditor();
  updateAuthUI();
  closeUserMenu();
  if (state.settingsOpen) {
    closeSettingsModal();
  }
}

async function bootstrapSession() {
  if (!state.token) {
    updateAuthUI();
    return;
  }

  try {
    const user = await api("/api/auth/me");
    await setSignedIn(user, state.token);
  } catch {
    signOut();
  }
}

async function loadConfig() {
  state.config = await api("/api/config");

  if (!state.config.allow_dev_auth) {
    qs("dev-login-form").classList.add("hidden");
  }
}

function initGoogleButton() {
  if (!state.config.google_client_id) {
    qs("google-login").innerHTML = "<p class='meta'>Google login disabled. Set TEAPARTY_GOOGLE_CLIENT_ID.</p>";
    return;
  }

  const tryInit = () => {
    if (!(window.google && window.google.accounts && window.google.accounts.id)) {
      setTimeout(tryInit, 200);
      return;
    }

    window.google.accounts.id.initialize({
      client_id: state.config.google_client_id,
      callback: (response) => loginWithGoogleCredential(response.credential).catch((error) => flash(error.message, "error")),
    });

    window.google.accounts.id.renderButton(qs("google-login"), {
      theme: "outline",
      size: "large",
      shape: "pill",
      text: "signin_with",
    });
  };

  tryInit();
}

function renderTaskDetail(task) {
    const panel = qs("chat-panel");
    const isSource = state.treeData[state.selectedWorkgroupId]?.crossGroupTasks?.some(
        (t) => t.id === task.id && t.source_workgroup_id === state.selectedWorkgroupId
    );
    const isTargetOwner = isWorkgroupOwner(task.target_workgroup_id) && task.target_workgroup_id === state.selectedWorkgroupId;
    const isSourceMember = task.source_workgroup_id === state.selectedWorkgroupId;
    const isTargetMember = task.target_workgroup_id === state.selectedWorkgroupId;

    const messagesHtml = (task.messages || []).map((msg) => `
        <div class="task-negotiation-message">
            <span class="task-msg-sender">${escapeHtml(msg.sender_user_id?.slice(0, 8) || "unknown")}</span>
            <span class="task-msg-time">${escapeHtml(new Date(msg.created_at).toLocaleString())}</span>
            <div class="task-msg-content">${escapeHtml(msg.content)}</div>
        </div>
    `).join("") || "<p class='meta'>No negotiation messages yet.</p>";

    let actionsHtml = "";
    if (isTargetOwner && (task.status === "requested" || task.status === "negotiating")) {
        actionsHtml += `<button type="button" class="task-action-btn accept" onclick="respondToTask('${escapeHtml(task.id)}', 'accept')">Accept</button>`;
        actionsHtml += `<button type="button" class="task-action-btn decline" onclick="respondToTask('${escapeHtml(task.id)}', 'decline')">Decline</button>`;
    }
    if (isTargetMember && task.status === "in_progress") {
        actionsHtml += `<button type="button" class="task-action-btn complete" onclick="completeTask('${escapeHtml(task.id)}')">Complete</button>`;
    }
    if (isSourceMember && task.status === "completed") {
        actionsHtml += `<button type="button" class="task-action-btn satisfied" onclick="rateTask('${escapeHtml(task.id)}', 'satisfied')">Satisfied</button>`;
        actionsHtml += `<button type="button" class="task-action-btn dissatisfied" onclick="rateTask('${escapeHtml(task.id)}', 'dissatisfied')">Dissatisfied</button>`;
    }

    const negotiateHtml = (task.status === "requested" || task.status === "negotiating") ? `
        <div class="task-negotiate-input">
            <input type="text" id="task-negotiate-content" placeholder="Type a negotiation message..." />
            <button type="button" onclick="sendTaskNegotiationMessage('${escapeHtml(task.id)}')">Send</button>
        </div>
    ` : "";

    panel.innerHTML = `
        <div class="task-detail-view">
            <div class="task-detail-header">
                <h2>${escapeHtml(task.title)}</h2>
                <span class="task-badge ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
            </div>
            <div class="task-detail-meta">
                <div><strong>From:</strong> ${escapeHtml(task.source_workgroup_name || task.source_workgroup_id?.slice(0, 8))}</div>
                <div><strong>To:</strong> ${escapeHtml(task.target_workgroup_name || task.target_workgroup_id?.slice(0, 8))}</div>
                <div><strong>Scope:</strong> ${escapeHtml(task.scope || "(none)")}</div>
                <div><strong>Requirements:</strong> ${escapeHtml(task.requirements || "(none)")}</div>
                <div><strong>Terms:</strong> ${escapeHtml(task.terms || "(none)")}</div>
            </div>
            <div class="task-actions">${actionsHtml}</div>
            <div class="task-negotiation-section">
                <h3>Negotiation</h3>
                <div class="task-negotiation-messages">${messagesHtml}</div>
                ${negotiateHtml}
            </div>
        </div>
    `;
}

async function openTask(workgroupId, taskId) {
    state.selectedWorkgroupId = workgroupId;
    state.activeTaskId = taskId;
    state.activeConversationId = "";
    state.activeNodeKey = `task:${workgroupId}:${taskId}`;
    renderTree();

    try {
        const task = await api(`/api/cross-group-tasks/${taskId}`);
        renderTaskDetail(task);
    } catch (error) {
        flash(error.message, "error");
    }
}

async function respondToTask(taskId, action) {
    try {
        const terms = action === "accept" ? prompt("Enter terms (optional):") || "" : "";
        const task = await api(`/api/cross-group-tasks/${taskId}/respond`, {
            method: "POST",
            body: { action, terms },
        });
        renderTaskDetail(task);
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
        }
        flash(`Task ${action}ed`, "success");
    } catch (error) {
        flash(error.message, "error");
    }
}

async function completeTask(taskId) {
    try {
        const summary = prompt("Completion summary (optional):") || "";
        const task = await api(`/api/cross-group-tasks/${taskId}/complete`, {
            method: "POST",
            body: { summary },
        });
        renderTaskDetail(task);
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
        }
        flash("Task completed", "success");
    } catch (error) {
        flash(error.message, "error");
    }
}

async function rateTask(taskId, action) {
    try {
        const feedback = prompt("Feedback (optional):") || "";
        const task = await api(`/api/cross-group-tasks/${taskId}/satisfaction`, {
            method: "POST",
            body: { action, feedback },
        });
        renderTaskDetail(task);
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
        }
        flash(`Task marked as ${action}`, "success");
    } catch (error) {
        flash(error.message, "error");
    }
}

async function sendTaskNegotiationMessage(taskId) {
    const input = qs("task-negotiate-content");
    const content = input?.value?.trim();
    if (!content) return;
    try {
        await api(`/api/cross-group-tasks/${taskId}/messages`, {
            method: "POST",
            body: { content },
        });
        input.value = "";
        const task = await api(`/api/cross-group-tasks/${taskId}`);
        renderTaskDetail(task);
    } catch (error) {
        flash(error.message, "error");
    }
}

async function proposeEngagement(workgroupId) {
    try {
        const directory = await api("/api/workgroup-directory");
        if (!directory.length) {
            flash("No discoverable workgroups found", "info");
            return;
        }

        const listHtml = directory.map((entry) => `
            <div class="directory-entry">
                <strong>${escapeHtml(entry.name)}</strong>
                <p class="meta">${escapeHtml(entry.service_description || "(no description)")}</p>
                <button type="button" class="tree-tool" onclick="openEngagementCreationForm('${escapeHtml(workgroupId)}', '${escapeHtml(entry.id)}', '${escapeHtml(entry.name)}')">Propose Engagement</button>
            </div>
        `).join("");

        openSettingsModal({
            title: "Service Directory",
            subtitle: "Choose a workgroup to engage with",
            formHtml: `
                <div class="directory-list">${listHtml}</div>
                <div class="settings-actions">
                    <button type="button" class="secondary" data-action="settings-cancel">Close</button>
                </div>
            `,
            onSubmit: async () => {},
        });
    } catch (error) {
        flash(error.message, "error");
    }
}

function openEngagementCreationForm(sourceWorkgroupId, targetWorkgroupId, targetName) {
    closeSettingsModal();
    openSettingsModal({
        title: "Propose Engagement",
        subtitle: `To: ${targetName}`,
        formHtml: `
            <label class="settings-field">
                <span class="settings-label">Title</span>
                <input name="title" type="text" maxlength="200" required placeholder="Engagement title" />
            </label>
            <label class="settings-field">
                <span class="settings-label">Scope</span>
                <textarea name="scope" rows="3" placeholder="What are you requesting?"></textarea>
            </label>
            <label class="settings-field">
                <span class="settings-label">Requirements</span>
                <textarea name="requirements" rows="3" placeholder="Detailed requirements"></textarea>
            </label>
            <div class="settings-actions">
                <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
                <button type="submit">Propose</button>
            </div>
        `,
        onSubmit: async (formData) => {
            const title = String(formData.get("title") || "").trim();
            const scope = String(formData.get("scope") || "").trim();
            const requirements = String(formData.get("requirements") || "").trim();
            if (!title) throw new Error("Title is required");
            await api("/api/engagements", {
                method: "POST",
                body: { target_workgroup_id: targetWorkgroupId, source_workgroup_id: sourceWorkgroupId, title, scope, requirements },
            });
            flash("Engagement proposed", "success");
            if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
                await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
                renderTree();
            }
        },
    });
}

function getActiveEngagement() {
    if (!state.selectedWorkgroupId || !state.activeConversationId) return null;
    const data = state.treeData[state.selectedWorkgroupId];
    if (!data || !data.engagements) return null;
    return data.engagements.find(
        (e) => e.source_conversation_id === state.activeConversationId || e.target_conversation_id === state.activeConversationId
    ) || null;
}

function getActiveJob() {
  if (!state.selectedWorkgroupId || !state.activeConversationId) return null;
  const data = state.treeData[state.selectedWorkgroupId];
  if (!data?.jobRecords) return null;
  return data.jobRecords.find(j => j.conversation_id === state.activeConversationId) || null;
}

async function engagementRespond(engagementId, action) {
    try {
        const terms = action === "accept" ? prompt("Enter terms (optional):") || "" : "";
        await api(`/api/engagements/${engagementId}/respond`, {
            method: "POST",
            body: { action, terms },
        });
        flash(`Engagement ${action === "accept" ? "accepted" : "declined"}`, "success");
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
            refreshActiveConversationHeader();
        }
    } catch (error) {
        flash(error.message, "error");
    }
}

async function engagementComplete(engagementId) {
    try {
        const summary = prompt("Completion summary (optional):") || "";
        await api(`/api/engagements/${engagementId}/complete`, {
            method: "POST",
            body: { summary },
        });
        flash("Engagement completed", "success");
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
            refreshActiveConversationHeader();
        }
    } catch (error) {
        flash(error.message, "error");
    }
}

async function engagementReview(engagementId, rating) {
    try {
        const feedback = prompt("Feedback (optional):") || "";
        await api(`/api/engagements/${engagementId}/review`, {
            method: "POST",
            body: { rating, feedback },
        });
        flash(`Engagement reviewed (${rating})`, "success");
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
            refreshActiveConversationHeader();
        }
    } catch (error) {
        flash(error.message, "error");
    }
}

async function engagementCancel(engagementId) {
    try {
        if (!confirm("Cancel this engagement?")) return;
        const reason = prompt("Reason (optional):") || "";
        await api(`/api/engagements/${engagementId}/cancel`, {
            method: "POST",
            body: { reason },
        });
        flash("Engagement cancelled", "success");
        if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
            await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
            renderTree();
            refreshActiveConversationHeader();
        }
    } catch (error) {
        flash(error.message, "error");
    }
}

async function browseServices(workgroupId) {
    try {
        const directory = await api("/api/workgroup-directory");
        if (!directory.length) {
            flash("No discoverable workgroups found", "info");
            return;
        }

        const listHtml = directory.map((entry) => `
            <div class="directory-entry">
                <strong>${escapeHtml(entry.name)}</strong>
                <p class="meta">${escapeHtml(entry.service_description || "(no description)")}</p>
                <button type="button" class="tree-tool" onclick="openTaskCreationForm('${escapeHtml(workgroupId)}', '${escapeHtml(entry.id)}', '${escapeHtml(entry.name)}')">Request Task</button>
            </div>
        `).join("");

        openSettingsModal({
            title: "Service Directory",
            subtitle: "Discoverable workgroups",
            formHtml: `
                <div class="directory-list">${listHtml}</div>
                <div class="settings-actions">
                    <button type="button" class="secondary" data-action="settings-cancel">Close</button>
                </div>
            `,
            onSubmit: async () => {},
        });
    } catch (error) {
        flash(error.message, "error");
    }
}

function openTaskCreationForm(sourceWorkgroupId, targetWorkgroupId, targetName) {
    closeSettingsModal();
    openSettingsModal({
        title: "Request Task",
        subtitle: `To: ${targetName}`,
        formHtml: `
            <label class="settings-field">
                <span class="settings-label">Title</span>
                <input name="title" type="text" maxlength="200" required placeholder="Task title" />
            </label>
            <label class="settings-field">
                <span class="settings-label">Scope</span>
                <textarea name="scope" rows="3" placeholder="What are you requesting?"></textarea>
            </label>
            <label class="settings-field">
                <span class="settings-label">Requirements</span>
                <textarea name="requirements" rows="3" placeholder="Detailed requirements"></textarea>
            </label>
            <div class="settings-actions">
                <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
                <button type="submit">Submit Request</button>
            </div>
        `,
        onSubmit: async (formData) => {
            const title = String(formData.get("title") || "").trim();
            const scope = String(formData.get("scope") || "").trim();
            const requirements = String(formData.get("requirements") || "").trim();
            if (!title) throw new Error("Title is required");
            await api("/api/cross-group-tasks", {
                method: "POST",
                body: { target_workgroup_id: targetWorkgroupId, title, scope, requirements },
            });
            flash("Task request submitted", "success");
            if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
                await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
                renderTree();
            }
        },
    });
}

function bindTreeEvents() {
  qs("treeview").addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const button = target.closest("button[data-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.action;

    if (action === "new-org") {
      openOrgCreateModal();
      return;
    }

    if (action === "settings-org") {
      const orgId = button.dataset.org || "";
      if (orgId) openOrgSettingsModal(orgId);
      return;
    }

    if (action === "settings-system") {
      openSystemSettingsModal();
      return;
    }

    if (action === "create-workgroup-in-org") {
      const wrapper = document.getElementById("workgroup-create-wrap");
      if (wrapper) {
        wrapper.classList.remove("hidden-by-blade");
        wrapper.classList.remove("hidden");
        renderWorkgroupCreateEditor();
      }
      return;
    }

    if (action === "drill-org") {
      const orgId = button.dataset.org || "";
      if (orgId) {
        closeFileOverlay();
        closeSettingsModal();
        clearActiveConversationUI();
        state.bladeOrgId = orgId;
        state.bladeWorkgroupId = "";
        state.bladeAgentId = "";
        renderTree();
      }
      return;
    }

    if (action === "drill-workgroup") {
      const workgroupId = button.dataset.workgroup || "";
      if (workgroupId) {
        closeFileOverlay();
        closeSettingsModal();
        clearActiveConversationUI();
        const wg = state.workgroups.find((w) => w.id === workgroupId);
        if (wg && wg.organization_id) {
          state.bladeOrgId = wg.organization_id;
        }
        state.bladeWorkgroupId = workgroupId;
        state.bladeAgentId = "";
        const wgData = state.treeData[workgroupId];
        if (wgData) {
          refreshWorkgroupTree(wgData.workgroup).then(() => renderTree());
        }
        renderTree();
      }
      return;
    }

    if (action === "drill-agent") {
      const agentId = button.dataset.agent || "";
      const wgId = button.dataset.workgroup || "";
      if (agentId && wgId) {
        closeFileOverlay();
        closeSettingsModal();
        clearActiveConversationUI();
        const wg = state.workgroups.find((w) => w.id === wgId);
        if (wg?.organization_id) state.bladeOrgId = wg.organization_id;
        state.bladeWorkgroupId = wgId;
        state.bladeAgentId = agentId;
        const wgData = state.treeData[wgId];
        if (wgData) {
          refreshWorkgroupTree(wgData.workgroup).then(() => renderTree());
        }
        renderTree();
      }
      return;
    }

    const workgroupId = button.dataset.workgroup || "";
    if (!workgroupId) {
      return;
    }

    if (action && (action.startsWith("settings-") || action.startsWith("file-") || action === "select-file" || action === "browse-services" || action === "propose-engagement" || action === "create-job" || action === "invite-member" || action === "open-file-browser" || action === "open-job-files" || action === "open-dm-files" || action === "accept-invite" || action === "decline-invite" || action === "cancel-invite" || action === "new-agent-task" || action === "open-agent-task")) {
      event.preventDefault();
      event.stopPropagation();
    }

    try {
      if (action === "open-job" && !button.dataset.job) {
        const conversationId = button.dataset.conversation || "";
        if (conversationId) {
          await selectConversation(workgroupId, conversationId, `job:${workgroupId}:${conversationId}`);
        }
        return;
      }

      if (action === "open-member") {
        const memberId = button.dataset.member || "";
        if (!memberId) {
          return;
        }
        await openMemberConversation(workgroupId, memberId);
      }

      if (action === "settings-workgroup") {
        await ensureWorkgroupConfigFile(workgroupId);
      }

      if (action === "settings-tools") {
        await ensureToolsManifestFile(workgroupId);
      }

      if (action === "settings-job") {
        const conversationId = button.dataset.conversation || "";
        if (!conversationId) {
          return;
        }
        const jobData = state.treeData[workgroupId];
        const conversation = jobData?.jobs.find((c) => c.id === conversationId);
        if (conversation) {
          await openConfigAndAdmin(workgroupId, `job: ${jobDisplayName(conversation)}`, conversation);
        }
      }

      if (action === "settings-agent") {
        const agentId = button.dataset.agent || "";
        if (!agentId) {
          return;
        }
        await openAgentSettings(workgroupId, agentId);
      }

      if (action === "settings-member") {
        const memberId = button.dataset.member || "";
        if (memberId) {
          openMemberContactCard(workgroupId, memberId);
        }
      }

      if (action === "select-file") {
        const fileId = button.dataset.fileId || "";
        if (!fileId) {
          return;
        }
        state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = fileId;
        updateFileSelection(workgroupId, fileId);
        openFileOverlay(workgroupId, fileId);
      }

      if (action === "file-add") {
        addWorkgroupFile(workgroupId);
      }

      if (action === "file-edit") {
        editWorkgroupFile(workgroupId);
      }

      if (action === "file-rename") {
        renameWorkgroupFile(workgroupId);
      }

      if (action === "file-delete") {
        deleteWorkgroupFile(workgroupId);
      }

      if (action === "folder-delete") {
        const folderPath = button.dataset.folderPath || "";
        if (folderPath) {
          deleteWorkgroupFolder(workgroupId, folderPath);
        }
      }

      if (action === "open-task") {
        const taskId = button.dataset.task || "";
        if (taskId) {
          openTask(workgroupId, taskId);
        }
      }

      if (action === "open-engagement") {
        const conversationId = button.dataset.conversation || "";
        const engagementId = button.dataset.engagement || "";
        if (conversationId) {
          state.activeEngagementId = engagementId;
          await selectConversation(workgroupId, conversationId, `engagement:${workgroupId}:${engagementId}`);
        }
      }

      if (action === "open-job") {
        const jobId = button.dataset.job;
        const conversationId = button.dataset.conversation;
        if (conversationId) {
          state.activeNodeKey = `job:${workgroupId}:${jobId}`;
          selectWorkgroup(workgroupId);
          await openConversation(workgroupId, conversationId);
        }
        return;
      }

      if (action === "propose-engagement") {
        proposeEngagement(workgroupId);
      }

      if (action === "browse-services") {
        browseServices(workgroupId);
      }

      if (action === "open-file-browser") {
        openFileBrowser(workgroupId);
      }

      if (action === "open-job-files") {
        const conversationId = button.dataset.conversation || "";
        if (conversationId) {
          const nodeKey = `job:${workgroupId}:${conversationId}`;
          await selectConversation(workgroupId, conversationId, nodeKey);
          openFileBrowser(workgroupId);
        }
      }

      if (action === "open-dm-files") {
        const agentId = button.dataset.agent || "";
        const memberId = button.dataset.member || "";
        if (agentId) {
          await openAgentConversation(workgroupId, agentId);
        } else if (memberId) {
          await openMemberConversation(workgroupId, memberId);
        }
        openFileBrowser(workgroupId);
      }

      if (action === "create-job") {
        await createJobPrompt(workgroupId);
      }

      if (action === "invite-member") {
        await inviteMemberPrompt(workgroupId);
      }

      if (action === "accept-invite") {
        const token = button.dataset.token || "";
        if (token) {
          await api(`/api/workgroups/${workgroupId}/invites/${token}/accept`, { method: "POST" });
          flash("Invite accepted!", "success");
          await loadMyInvites();
          await loadWorkgroups();
        }
      }

      if (action === "decline-invite") {
        const token = button.dataset.token || "";
        if (token && confirm("Decline this invite?")) {
          await api(`/api/workgroups/${workgroupId}/invites/${token}/decline`, { method: "POST" });
          flash("Invite declined", "info");
          await loadMyInvites();
          renderTree();
        }
      }

      if (action === "cancel-invite") {
        const inviteId = button.dataset.inviteId || "";
        if (inviteId && confirm("Cancel this invite?")) {
          await api(`/api/workgroups/${workgroupId}/invites/${inviteId}`, { method: "DELETE" });
          flash("Invite cancelled", "info");
          await refreshWorkgroupTree(state.treeData[workgroupId].workgroup);
          renderTree();
        }
      }

      if (action === "new-agent-task") {
        const agentId = button.dataset.agent || "";
        if (agentId) {
          await createAgentTaskPrompt(workgroupId, agentId);
        }
      }

      if (action === "open-agent-task") {
        const taskId = button.dataset.taskId || "";
        const conversationId = button.dataset.conversation || "";
        if (conversationId) {
          await selectConversation(workgroupId, conversationId, `task:${workgroupId}:${taskId}`);
        }
      }
    } catch (error) {
      flash(error.message, "error");
    }
  });

  qs("treeview").addEventListener("dblclick", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const button = target.closest('button[data-action="select-file"]');
    if (!button) {
      return;
    }
    const workgroupId = button.dataset.workgroup || "";
    const fileId = button.dataset.fileId || "";
    if (!workgroupId || !fileId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = fileId;
    updateFileSelection(workgroupId, fileId);
  });

  // Breadcrumb navigation (blade-back and settings-workgroup from breadcrumb)
  const breadcrumbEl = document.getElementById("blade-breadcrumb");
  if (breadcrumbEl) {
    breadcrumbEl.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const button = target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      if (action === "blade-back-root") {
        closeFileOverlay();
        closeSettingsModal();
        clearActiveConversationUI();
        state.bladeOrgId = "";
        state.bladeWorkgroupId = "";
        state.bladeAgentId = "";
        renderTree();
      } else if (action === "blade-back") {
        closeFileOverlay();
        closeSettingsModal();
        clearActiveConversationUI();
        if (state.bladeAgentId) {
          // L4 → L2: agent detail back to org detail
          if (state.bladeWorkgroupId) {
            const wg = state.workgroups.find((w) => w.id === state.bladeWorkgroupId);
            if (wg?.organization_id) state.bladeOrgId = wg.organization_id;
          }
          state.bladeWorkgroupId = "";
          state.bladeAgentId = "";
        } else if (state.bladeWorkgroupId) {
          const wg = state.workgroups.find((w) => w.id === state.bladeWorkgroupId);
          state.bladeWorkgroupId = "";
          state.bladeAgentId = "";
          if (wg && wg.organization_id) {
            state.bladeOrgId = wg.organization_id;
          } else {
            state.bladeOrgId = "";
          }
        } else {
          state.bladeOrgId = "";
        }
        renderTree();
      } else if (action === "settings-agent") {
        const wgId = button.dataset.workgroup || "";
        const agentId = button.dataset.agent || "";
        if (wgId && agentId) openAgentSettings(wgId, agentId);
      } else if (action === "settings-org") {
        const orgId = button.dataset.org || "";
        if (orgId) openOrgSettingsModal(orgId);
      } else if (action === "settings-system") {
        openSystemSettingsModal();
      } else if (action === "settings-workgroup") {
        const workgroupId = button.dataset.workgroup || "";
        if (!workgroupId) return;
        try {
          await ensureWorkgroupConfigFile(workgroupId);
        } catch (error) {
          flash(error.message, "error");
        }
      } else if (action === "settings-tools") {
        const workgroupId = button.dataset.workgroup || "";
        if (!workgroupId) return;
        try {
          await ensureToolsManifestFile(workgroupId);
        } catch (error) {
          flash(error.message, "error");
        }
      }
    });
  }
}

function bindEvents() {
  const themeToggle = qs("theme-toggle");
  themeToggle.addEventListener("change", () => {
    applyTheme(themeToggle.checked ? "dark" : "light");
  });

  const thoughtsToggle = qs("thoughts-toggle");
  thoughtsToggle.addEventListener("change", () => {
    savePreferences({ showAgentThoughts: thoughtsToggle.checked });
    if (thoughtsToggle.checked) loadThoughtsForMessages();
    renderMessages(state.activeMessages);
  });

  qs("settings-close").addEventListener("click", () => {
    requestSettingsClose({ saveIfDirty: true }).catch((error) => {
      flash(error.message || "Failed to close settings", "error");
    });
  });

  // --- Chat header action buttons ---
  qs("toggle-files-btn").addEventListener("click", () => {
    if (state.fileBrowserOpen) {
      closeFileOverlay();
    } else if (state.selectedWorkgroupId) {
      openFileBrowser(state.selectedWorkgroupId);
    }
  });

  qs("toggle-toolbar-btn").addEventListener("click", () => {
    state.toolbarVisible = !state.toolbarVisible;
    refreshActiveConversationHeader();
  });

  qs("chat-menu-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    const dropdown = qs("chat-menu-dropdown");
    const opening = dropdown.classList.contains("hidden");
    dropdown.classList.toggle("hidden");
    if (opening) {
      // Update archive button label
      const archiveBtn = qs("chat-archive-btn");
      if (archiveBtn) {
        const archived = isActiveConversationArchived();
        archiveBtn.textContent = archived ? "Unarchive" : "Archive";
        archiveBtn.dataset.action = archived ? "chat-unarchive" : "chat-archive";
      }
    }
  });

  qs("chat-menu-dropdown").addEventListener("click", async (e) => {
    const button = e.target.closest("button[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    const dropdown = qs("chat-menu-dropdown");
    dropdown.classList.add("hidden");

    if (action === "chat-copy") {
      copyChatToClipboard();
    } else if (action === "chat-archive" || action === "chat-unarchive") {
      const wgId = state.selectedWorkgroupId;
      const convId = state.activeConversationId;
      if (!wgId || !convId) return;
      const archiving = action === "chat-archive";
      try {
        await api(`/api/workgroups/${wgId}/conversations/${convId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_archived: archiving }),
        });
        const wgData = state.treeData[wgId];
        if (wgData) {
          await refreshWorkgroupTree(wgData.workgroup);
        }
        refreshActiveConversationHeader();
        flash(archiving ? "Archived" : "Unarchived", "success");
      } catch (err) {
        flash(err.message || "Failed to update archive status", "error");
      }
    } else if (action === "chat-clear-history") {
      const wgId = state.selectedWorkgroupId;
      const convId = state.activeConversationId;
      if (!wgId || !convId) return;
      const confirmed = window.confirm("Clear all messages in this conversation? This cannot be undone.");
      if (!confirmed) return;
      try {
        const result = await api(`/api/workgroups/${wgId}/conversations/${convId}/messages`, {
          method: "DELETE",
        });
        delete state.thinkingByConversation[convId];
        await loadMessages();
        const deleted = Number(result?.deleted_messages || 0);
        flash(deleted > 0 ? `Cleared ${deleted} message${deleted === 1 ? "" : "s"}` : "History already empty", "success");
      } catch (err) {
        flash(err.message || "Failed to clear history", "error");
      }
    }
  });

  qs("file-overlay-close").addEventListener("click", closeFileOverlay);

  qs("file-overlay").addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const button = target.closest("button[data-action]");
    if (!button) return;
    const action = button.dataset.action;

    if (!state.fileBrowserOpen) return;

    if (action === "browser-drill") {
      const folder = button.dataset.folder;
      if (folder) {
        state.fileBrowserPath = [...state.fileBrowserPath, folder];
        state.fileBrowserFileId = "";
        renderFileBrowser();
      }
    }

    if (action === "browser-navigate") {
      const depth = parseInt(button.dataset.depth, 10);
      state.fileBrowserPath = state.fileBrowserPath.slice(0, depth);
      state.fileBrowserFileId = "";
      renderFileBrowser();
    }

    if (action === "browser-open-file") {
      const fileId = button.dataset.fileId;
      if (fileId) {
        state.fileBrowserFileId = fileId;
        renderFileBrowser();
      }
    }

    // For composite mode, resolve effective workgroup from .templates/ → admin wg
    const isComposite = state.fileBrowserScope === "root" || state.fileBrowserScope === "org";
    let wgId = state.fileBrowserWorkgroupId;
    if (isComposite && !wgId) {
      const currentPath = state.fileBrowserPath.join("/");
      if (currentPath.startsWith(".templates")) {
        const adminWg = state.workgroups.find(w => w.name === "Administration" && !w.organization_id);
        if (adminWg) wgId = adminWg.id;
      }
    }
    if (!wgId) return;

    if (action === "browser-add-file") {
      browserAddFile(wgId);
    }
    if (action === "browser-new-folder") {
      browserNewFolder(wgId);
    }
    if (action === "browser-rename-file") {
      const fileId = button.dataset.fileId;
      if (fileId) browserRenameFile(wgId, fileId);
    }
    if (action === "browser-copy-file") {
      const fileId = button.dataset.fileId;
      if (fileId) browserCopyFile(wgId, fileId);
    }
    if (action === "browser-delete-file") {
      const fileId = button.dataset.fileId;
      if (fileId) browserDeleteFile(wgId, fileId);
    }
    if (action === "browser-rename-folder") {
      const folderPath = button.dataset.folderPath;
      if (folderPath) browserRenameFolder(wgId, folderPath);
    }
    if (action === "browser-copy-folder") {
      const folderPath = button.dataset.folderPath;
      if (folderPath) browserCopyFolder(wgId, folderPath);
    }
    if (action === "browser-delete-folder") {
      const folderPath = button.dataset.folderPath;
      if (folderPath) deleteWorkgroupFolder(wgId, folderPath);
    }
  });

  qs("chat-tool-buttons").addEventListener("click", (event) => {
    const btn = event.target.closest(".chat-tool-btn");
    if (!btn) return;
    const toolName = btn.dataset.toolName || "";
    if (!toolName) return;
    const input = qs("message-content");
    input.value = toolName.replace(/^custom:/, "") + " ";
    input.focus();
  });

  qs("file-overlay-edit").addEventListener("click", () => {
    if (state.fileOverlayMemberContext) {
      saveMemberContactCard();
    } else if (state.fileOverlayViewMode === "form" && state.fileOverlayParsedJson !== null) {
      saveJsonFormOverlay();
    } else {
      editWorkgroupFile(state.fileOverlayWorkgroupId);
    }
  });

  qs("file-overlay-delete").addEventListener("click", () => {
    const workgroupId = state.fileOverlayWorkgroupId;
    const fileId = state.fileOverlayFileId;
    if (!workgroupId || !fileId) {
      return;
    }
    const data = state.treeData[workgroupId];
    if (!data) {
      return;
    }
    const files = normalizeWorkgroupFiles(data.workgroup.files);
    const file = files.find((item) => item.id === fileId);
    if (!file) {
      return;
    }
    const confirmed = window.confirm(`Delete file "${file.path}"?`);
    if (!confirmed) {
      return;
    }
    const remaining = files.filter((item) => item.id !== fileId);
    saveWorkgroupFiles(workgroupId, remaining)
      .then(() => {
        delete state.selectedWorkgroupFileIdByWorkgroup[workgroupId];
        closeFileOverlay();
        renderTree();
        flash("File deleted", "success");
      })
      .catch((error) => {
        flash(error.message || "Failed to delete file", "error");
      });
  });

  qs("file-overlay-raw-toggle").addEventListener("click", () => {
    if (state.fileOverlayParsedJson !== null) {
      const newMode = state.fileOverlayViewMode === "form" ? "raw" : "form";
      setFileOverlayViewMode(newMode);
      const isOwner = isWorkgroupOwner(state.fileOverlayWorkgroupId);
      updateFileOverlayEditButton(isOwner, newMode === "form", true);
    } else {
      state.fileOverlayShowRaw = !state.fileOverlayShowRaw;
      const pre = qs("file-overlay-content");
      const rendered = qs("file-overlay-rendered");
      const rawToggle = qs("file-overlay-raw-toggle");

      if (state.fileOverlayShowRaw) {
        pre.classList.remove("hidden");
        rendered.classList.add("hidden");
        rawToggle.textContent = "Rendered";
      } else {
        pre.classList.add("hidden");
        rendered.innerHTML = renderMarkdown(pre.textContent);
        rendered.classList.remove("hidden");
        rawToggle.textContent = "Raw";
      }
    }
  });

  qs("user-menu-button").addEventListener("click", () => {
    toggleUserMenu();
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    if (target.closest('[data-action="clear-file-context"]')) {
      closeFileOverlay();
      return;
    }

    const menu = qs("user-menu-dropdown");
    const button = qs("user-menu-button");
    if (!menu.contains(target) && !button.contains(target)) {
      closeUserMenu();
    }

    // Close chat menu dropdown on click-outside
    const chatDropdown = qs("chat-menu-dropdown");
    const chatMenuBtn = qs("chat-menu-btn");
    if (chatDropdown && chatMenuBtn && !chatDropdown.contains(target) && !chatMenuBtn.contains(target)) {
      chatDropdown.classList.add("hidden");
    }
  });

  qs("settings-modal").addEventListener("click", (event) => {
    if (event.target === qs("settings-modal")) {
      requestSettingsClose({ saveIfDirty: true }).catch((error) => {
        flash(error.message || "Failed to close settings", "error");
      });
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (state.settingsOpen) {
        requestSettingsClose({ saveIfDirty: true }).catch((error) => {
          flash(error.message || "Failed to close settings", "error");
        });
      } else if (state.fileOverlayOpen || state.fileBrowserOpen) {
        closeFileOverlay();
      }
    }
  });

  qs("logout-button").addEventListener("click", () => {
    signOut();
    flash("Logged out", "info");
  });

  qs("new-workgroup-toggle").addEventListener("click", () => {
    const wrapper = qs("workgroup-create-wrap");
    const opening = wrapper.classList.contains("hidden");
    wrapper.classList.toggle("hidden");
    if (opening) {
      renderWorkgroupCreateEditor();
    }
  });

  qs("workgroup-template").addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) {
      return;
    }

    const nextTemplateKey = target.value;
    if (!nextTemplateKey || nextTemplateKey === state.workgroupCreateTemplateKey) {
      return;
    }
    applyTemplateToCreateDraft(nextTemplateKey);
  });

  qs("workgroup-create-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!state.token) {
      flash("Login first", "error");
      return;
    }

    const name = qs("workgroup-name").value.trim();
    if (!name) {
      flash("Workgroup name cannot be empty", "error");
      return;
    }

    try {
      const createPayload = { name };
      if (state.workgroupCreateTemplateKey) {
        createPayload.template_key = state.workgroupCreateTemplateKey;
      }
      if (!state.bladeOrgId) {
        flash("Select an organization first", "error");
        return;
      }
      createPayload.organization_id = state.bladeOrgId;

      const group = await api("/api/workgroups", {
        method: "POST",
        body: createPayload,
      });

      qs("workgroup-name").value = "";
      resetWorkgroupCreateDraft();
      qs("workgroup-create-wrap").classList.add("hidden");

      const workgroup = state.workgroups.find((item) => item.id === group.id) || group;
      state.workgroups = [group, ...state.workgroups.filter((item) => item.id !== group.id)];
      await refreshWorkgroupTree(workgroup);
      renderTree();

      state.bladeOrgId = group.organization_id;
      state.bladeWorkgroupId = group.id;
      const adminId = adminConversationId(group.id);
      if (adminId) {
        await selectConversation(group.id, adminId, `job:${group.id}:${adminId}`);
      }

      flash("Workgroup created", "success");
    } catch (error) {
      flash(error.message, "error");
    }
  });

  qs("message-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!state.activeConversationId) {
      flash("Select a conversation first", "error");
      return;
    }

    const content = qs("message-content").value.trim();
    if (!content) {
      flash("Message cannot be empty", "error");
      return;
    }

    let fullContent = content;
    if (state.fileOverlayOpen && state.fileOverlayFileId) {
      const wgData = state.treeData[state.fileOverlayWorkgroupId];
      const files = normalizeWorkgroupFiles(wgData?.workgroup?.files);
      const file = files.find(f => f.id === state.fileOverlayFileId);
      if (file) {
        fullContent = `[file: ${file.path}]\n<<<\n${file.content}\n>>>\n\n${content}`;
      }
    }

    const destructiveAdminPost =
      isAdminConversation(state.selectedWorkgroupId, state.activeConversationId) && isDestructiveAdminCommand(content);
    const deleteWorkgroupPost =
      isAdminConversation(state.selectedWorkgroupId, state.activeConversationId) && isDeleteWorkgroupCommand(content);

    const optimisticId = `local-${crypto.randomUUID()}`;
    const optimisticMessage = {
      id: optimisticId,
      conversation_id: state.activeConversationId,
      sender_type: "user",
      sender_user_id: state.user?.id || null,
      sender_agent_id: null,
      content,
      requires_response: false,
      response_to_message_id: null,
      created_at: new Date().toISOString(),
    };
    state.activeMessages = [...state.activeMessages, optimisticMessage];
    renderMessages(state.activeMessages);
    sessionStorage.setItem("draft-message", content);
    qs("message-content").value = "";

    let posted = null;
    try {
      const envelope = await api(`/api/conversations/${state.activeConversationId}/messages`, {
        method: "POST",
        body: { content: fullContent },
        headers: { "X-Idempotency-Key": crypto.randomUUID() },
      });

      posted = envelope?.posted;
      sessionStorage.removeItem("draft-message");
      const withoutOptimistic = state.activeMessages.filter((message) => message.id !== optimisticId);
      if (posted && posted.conversation_id === state.activeConversationId) {
        const alreadyExists = withoutOptimistic.some((message) => message.id === posted.id);
        const nextMessages = alreadyExists ? withoutOptimistic : [...withoutOptimistic, posted];
        if (!deleteWorkgroupPost) {
          startThinkingForMessage(posted);
        } else if (state.activeConversationId) {
          delete state.thinkingByConversation[state.activeConversationId];
        }
        renderMessages(nextMessages);
      } else {
        renderMessages(withoutOptimistic);
      }

    } catch (error) {
      const withoutOptimistic = state.activeMessages.filter((message) => message.id !== optimisticId);
      renderMessages(withoutOptimistic);
      qs("message-content").value = sessionStorage.getItem("draft-message") || "";
      sessionStorage.removeItem("draft-message");
      flash(error.message, "error");
      return;
    }

    try {
      if (state.selectedWorkgroupId && state.treeData[state.selectedWorkgroupId]) {
        await refreshWorkgroupTree(state.treeData[state.selectedWorkgroupId].workgroup);
        renderTree();
      } else {
        await loadWorkgroups();
      }

      if (posted && state.activeConversationId && !deleteWorkgroupPost) {
        await loadMessages();
        loadConversationUsage(state.activeConversationId);
      }
    } catch (refreshError) {
      console.error(refreshError);
      try {
        await loadWorkgroups();
      } catch (reloadError) {
        console.error(reloadError);
      }
    }

    if (deleteWorkgroupPost) {
      clearActiveConversationUI();
      scheduleDestructiveAdminRefresh([120, 650, 1700, 3200]);
    } else if (destructiveAdminPost) {
      scheduleDestructiveAdminRefresh();
    }
  });

  qs("dev-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const auth = await api("/api/auth/dev-login", {
        method: "POST",
        body: {
          email: qs("dev-email").value.trim(),
          name: qs("dev-name").value.trim(),
        },
      });
      await setSignedIn(auth.user, auth.access_token);
      flash("Dev login successful", "success");
    } catch (error) {
      flash(error.message, "error");
    }
  });

  // Blade resize handle
  {
    const handle = document.getElementById("blade-resize-handle");
    const layout = document.querySelector(".layout");
    const MIN_WIDTH = 200;
    const MAX_WIDTH = 600;

    let dragging = false;

    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = true;
      handle.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
    });

    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const rect = layout.getBoundingClientRect();
      const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX - rect.left));
      layout.style.setProperty("--blade-width", width + "px");
    });

    handle.addEventListener("pointerup", (e) => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      handle.releasePointerCapture(e.pointerId);
      const currentWidth = parseInt(layout.style.getPropertyValue("--blade-width"), 10);
      if (currentWidth) {
        savePreferences({ bladeWidth: currentWidth });
      }
    });
  }

  // File overlay resize handle
  {
    const handle = document.getElementById("file-overlay-resize-handle");
    const chatPanel = document.getElementById("chat-panel");
    const MIN_HEIGHT = 100;
    const MAX_FRAC = 0.85;

    let dragging = false;

    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = true;
      handle.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
    });

    handle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const chatRect = chatPanel.getBoundingClientRect();
      const headerEl = chatPanel.querySelector(".chat-header");
      const headerH = headerEl ? headerEl.getBoundingClientRect().height : 0;
      const composerEl = document.getElementById("message-form");
      const composerH = composerEl.getBoundingClientRect().height;
      const maxH = (chatRect.height - headerH - composerH) * MAX_FRAC;
      const height = Math.min(maxH, Math.max(MIN_HEIGHT, e.clientY - chatRect.top - headerH));
      chatPanel.style.setProperty("--overlay-height", height + "px");
    });

    handle.addEventListener("pointerup", (e) => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      handle.releasePointerCapture(e.pointerId);
      const val = parseInt(chatPanel.style.getPropertyValue("--overlay-height"), 10);
      if (val) savePreferences({ overlayHeight: val });
    });
  }

  // Drag-and-drop file upload into chat
  {
    const chatPanel = qs("chat-panel");
    let dragCounter = 0;

    chatPanel.addEventListener("dragenter", (e) => {
      e.preventDefault();
      dragCounter++;
      chatPanel.classList.add("drag-over");
    });

    chatPanel.addEventListener("dragover", (e) => {
      e.preventDefault();
    });

    chatPanel.addEventListener("dragleave", (e) => {
      e.preventDefault();
      dragCounter--;
      if (dragCounter <= 0) {
        dragCounter = 0;
        chatPanel.classList.remove("drag-over");
      }
    });

    chatPanel.addEventListener("drop", async (e) => {
      e.preventDefault();
      dragCounter = 0;
      chatPanel.classList.remove("drag-over");

      const droppedFiles = e.dataTransfer?.files;
      if (!droppedFiles || droppedFiles.length === 0) return;

      if (!state.token || !state.user) {
        flash("Sign in first", "error");
        return;
      }

      if (!state.activeConversationId || !state.selectedWorkgroupId) {
        flash("Select a conversation first", "error");
        return;
      }

      const workgroupId = state.selectedWorkgroupId;
      const MAX_SIZE = 200 * 1024;

      for (const file of droppedFiles) {
        if (file.size > MAX_SIZE) {
          flash(`File too large: ${file.name} (max 200KB)`, "error");
          continue;
        }

        try {
          const isImage = file.type.startsWith("image/");
          const content = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
            if (isImage) {
              reader.readAsDataURL(file);
            } else {
              reader.readAsText(file);
            }
          });

          const path = `jobs/uploads/${file.name}`;
          const data = state.treeData[workgroupId];
          if (!data) {
            flash("Workgroup not loaded", "error");
            break;
          }

          const files = normalizeWorkgroupFiles(data.workgroup.files);
          const existingIndex = files.findIndex((item) => item.path === path);

          let updatedFiles;
          let fileId;
          if (existingIndex !== -1) {
            fileId = files[existingIndex].id;
            updatedFiles = files.map((item) =>
              item.path === path ? { ...item, content } : item,
            );
          } else {
            fileId = newWorkgroupFileId();
            updatedFiles = [...files, { id: fileId, path, content }];
          }

          await saveWorkgroupFiles(workgroupId, updatedFiles);
          state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = fileId;
          renderTree();
          openFileOverlay(workgroupId, fileId);
          flash(`File uploaded: ${file.name}`, "success");
        } catch (err) {
          flash(err.message || `Failed to upload ${file.name}`, "error");
        }
      }
    });
  }

  bindTreeEvents();
}

function insertMarkdownSyntax(textarea, action) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = textarea.value.substring(start, end);

  const templates = {
    bold: { before: "**", after: "**", placeholder: "bold text" },
    italic: { before: "_", after: "_", placeholder: "italic text" },
    heading: { before: "## ", after: "", placeholder: "Heading" },
    link: { before: "[", after: "](url)", placeholder: "link text" },
    code: { before: "`", after: "`", placeholder: "code" },
    codeblock: { before: "```\n", after: "\n```", placeholder: "code block" },
    ul: { before: "- ", after: "", placeholder: "list item" },
    ol: { before: "1. ", after: "", placeholder: "list item" },
  };

  const tmpl = templates[action];
  if (!tmpl) {
    return;
  }

  const text = selected || tmpl.placeholder;
  const replacement = tmpl.before + text + tmpl.after;
  textarea.setRangeText(replacement, start, end, "select");

  if (!selected) {
    textarea.selectionStart = start + tmpl.before.length;
    textarea.selectionEnd = start + tmpl.before.length + tmpl.placeholder.length;
  }

  textarea.focus();
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function bindMdToolbar(form) {
  const toolbar = form.querySelector(".md-toolbar");
  if (!toolbar) {
    return;
  }

  toolbar.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-md-action]");
    if (!btn) {
      return;
    }

    const action = btn.dataset.mdAction;
    const textarea = form.querySelector("textarea[name='content']");
    const preview = form.querySelector(".md-editor-preview");

    if (action === "preview") {
      if (preview.classList.contains("hidden")) {
        preview.innerHTML = renderMarkdown(textarea.value);
        preview.classList.remove("hidden");
        textarea.classList.add("hidden");
        btn.textContent = "Edit";
      } else {
        preview.classList.add("hidden");
        textarea.classList.remove("hidden");
        btn.textContent = "Preview";
        textarea.focus();
      }
      return;
    }

    if (!textarea.classList.contains("hidden")) {
      if (preview && !preview.classList.contains("hidden")) {
        preview.classList.add("hidden");
        textarea.classList.remove("hidden");
        const previewBtn = toolbar.querySelector("[data-md-action='preview']");
        if (previewBtn) {
          previewBtn.textContent = "Preview";
        }
      }
      insertMarkdownSyntax(textarea, action);
    }
  });
}

async function init() {
  applyTheme(resolveInitialTheme(), false);

  if (typeof marked !== "undefined") {
    const renderer = new marked.Renderer();
    renderer.link = function ({ href, title, text }) {
      const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
      return `<a href="${escapeHtml(href)}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    };
    marked.setOptions({ renderer });
  }

  renderWorkgroupCreateEditor();
  bindEvents();
  await loadConfig();
  initGoogleButton();
  await bootstrapSession();
  updateMetrics();
}

init().catch((error) => {
  flash(error.message, "error");
  console.error(error);
});
