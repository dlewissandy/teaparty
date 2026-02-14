const state = {
  token: localStorage.getItem("teaparty_token") || "",
  user: null,
  config: null,
  workgroups: [],
  treeData: {},
  workgroupTemplates: [],
  workgroupCreateTemplateKey: "",
  workgroupCreateFiles: [],
  workgroupCreateAgents: [],
  selectedWorkgroupId: "",
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
  crossGroupTasks: [],
  activeTaskId: "",
  workgroupDirectory: [],
  conversationUsage: null,
  usagePollCounter: 0,
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

  const input = el.querySelector("input") || el;
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
  const headers = { ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  let body = options.body;
  if (body && typeof body === "object" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  const response = await fetch(path, { ...options, headers, body });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || `Request failed: ${response.status}`);
    error.status = response.status;

    if (response.status === 401 && state.token) {
      signOut();
      flash("Session expired. Sign in again.", "info");
    }

    throw error;
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
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
  const topicCount = selected ? selected.topics.length + selected.directs.length : 0;
  setTextIfPresent("metric-conversations", String(topicCount));

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

function topicDisplayName(conversation) {
  const explicit = (conversation?.name || "").trim();
  if (explicit) {
    return explicit;
  }
  const fallback = (conversation?.topic || "").trim();
  return fallback || "topic";
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

    seenIds.add(id);
    normalized.push({ id, path, content });
  }
  return normalized;
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
      const lockedKeys = file.path.endsWith("workgroup.json")
        ? new Set(["id", "owner_id", "created_at"])
        : null;
      renderJsonForm(parsed.data, !isOwner, lockedKeys);
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
    const admin = wgData.topics.find((c) => c.kind === "admin");
    if (admin) {
      await selectConversation(workgroupId, admin.id, `topic:${workgroupId}:${admin.id}`);
    }
  }
  openConfigOverlay(workgroupId, label, configData);
}

function closeFileOverlay() {
  qs("file-overlay").classList.add("hidden");
  state.fileOverlayOpen = false;
  state.fileOverlayShowRaw = false;
  state.fileOverlayViewMode = "raw";
  state.fileOverlayParsedJson = null;
  state.fileOverlayLastContent = "";

  const rendered = qs("file-overlay-rendered");
  rendered.innerHTML = "";
  rendered.classList.add("hidden");

  const form = qs("file-overlay-form");
  form.innerHTML = "";
  form.classList.add("hidden");

  const editBtn = qs("file-overlay-edit");
  editBtn.textContent = "Edit";

  qs("file-overlay-delete").classList.add("hidden");

  qs("file-overlay-content").classList.remove("hidden");
  qs("file-overlay-raw-toggle").classList.add("hidden");

  qs("composer-file-context").classList.add("hidden");
}

function refreshFileOverlayIfOpen() {
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
      const lockedKeys = file.path.endsWith("workgroup.json")
        ? new Set(["id", "owner_id", "created_at"])
        : null;
      renderJsonForm(parsed.data, !isOwner, lockedKeys);
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
            placeholder="tools: summarize_topic, suggest_next_step"
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

function directTopicKeyForCurrentUser(otherUserId) {
  if (!state.user) {
    return "";
  }
  const pair = [state.user.id, otherUserId].sort();
  return `dm:${pair[0]}:${pair[1]}`;
}

function adminConversationId(workgroupId) {
  const data = state.treeData[workgroupId];
  const admin = data?.topics.find((item) => item.kind === "admin");
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
    return `topic:${workgroupId}:${conversation.id}`;
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

  const admin = data.topics.find((item) => item.kind === "admin");
  if (admin) {
    return admin;
  }
  if (data.topics.length) {
    return data.topics[0];
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
  setTextIfPresent("active-context", "Use the tree to open a topic, member DM, or administration conversation.");
  const usageEl = qs("active-usage");
  if (usageEl) usageEl.classList.add("hidden");
  const toolBar = qs("chat-tool-buttons");
  if (toolBar) { toolBar.innerHTML = ""; toolBar.classList.add("hidden"); }
}

function isDestructiveAdminCommand(content) {
  const normalized = content.trim().toLowerCase();
  return /(?:^|\s)(remove|delete)\s+(?:the\s+)?(?:member|user|participant|agent|topic|conversation|channel|workgroup)\b/.test(normalized);
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

  const topic = data.topics.find((item) => item.id === conversationId);
  if (topic) {
    if (topic.kind === "admin") {
      return `Administration · ${data.workgroup.name}`;
    }
    return `#${topicDisplayName(topic)}`;
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
  return data.topics.find((item) => item.id === conversationId) || data.directs.find((item) => item.id === conversationId) || null;
}


function conversationContextLabel(workgroupId, conversationId) {
  const workgroupName = state.treeData[workgroupId]?.workgroup.name || workgroupId;
  const base = `Workgroup: ${workgroupName}`;
  const conversation = conversationById(workgroupId, conversationId);
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

  if (conversation.kind === "topic") {
    const topicAgents = (data.agents || []).filter((item) => item.description !== "__system_admin_agent__");
    const mentionedAgentIds = topicAgents
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

  if (Date.now() - pending.startedAtMs > 60000) {
    delete state.thinkingByConversation[conversationId];
    return;
  }

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
    delete state.thinkingByConversation[conversationId];
  }
}


function renderThinkingRows(workgroupId, pending) {
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

  return null;
}

function refreshActiveConversationHeader() {
  if (!state.selectedWorkgroupId || !state.activeConversationId) {
    return;
  }
  setTextIfPresent("active-conversation", conversationLabel(state.selectedWorkgroupId, state.activeConversationId));
  setTextIfPresent("active-context", conversationContextLabel(state.selectedWorkgroupId, state.activeConversationId));

  const toolBar = qs("chat-tool-buttons");
  if (!toolBar) return;

  const agent = getConversationAgent(state.selectedWorkgroupId, state.activeConversationId);
  if (agent && agent.tool_names && agent.tool_names.length) {
    toolBar.innerHTML = agent.tool_names
      .map((name) => `<button type="button" class="chat-tool-btn" data-tool-name="${escapeHtml(name)}">${escapeHtml(toolDisplayLabel(name))}</button>`)
      .join("");
    toolBar.classList.remove("hidden");
  } else {
    toolBar.innerHTML = "";
    toolBar.classList.add("hidden");
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

function applyTopicUpdateInState(workgroupId, updatedConversation) {
  const data = state.treeData[workgroupId];
  if (!data) {
    return;
  }
  data.topics = data.topics.map((conversation) => (conversation.id === updatedConversation.id ? updatedConversation : conversation));
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
      const updated = await api(`/api/workgroups/${workgroupId}`, {
        method: "PATCH",
        body: { name, is_discoverable: isDiscoverable, service_description: serviceDescription },
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
    subtitle: data.workgroup.name,
    onSubmit: async ({ path, content }) => {
      const files = normalizeWorkgroupFiles(data.workgroup.files);
      const exists = files.some((item) => item.path === path);
      if (exists) {
        throw new Error("A file with that path already exists");
      }
      const newFile = { id: newWorkgroupFileId(), path, content };
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
    subtitle: `${data.workgroup.name} · ${selected.path}`,
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
    subtitle: `${data.workgroup.name} · ${selected.path}`,
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
      renderTree();
      flash(`Folder "${folderPath}" deleted (${matchingFiles.length} file${matchingFiles.length === 1 ? "" : "s"})`, "success");
    })
    .catch((error) => {
      flash(error.message || "Failed to delete folder", "error");
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

  const admin = data.topics.find((c) => c.kind === "admin");
  if (admin) {
    await selectConversation(workgroupId, admin.id, `topic:${workgroupId}:${admin.id}`);
  }

  state.expandedWorkgroupIds[workgroupId] = true;
  state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = file.id;
  openFileOverlay(workgroupId, file.id);
}

async function createTopicPrompt(workgroupId) {
  const topicName = prompt("Topic name:");
  if (!topicName || !topicName.trim()) {
    return;
  }
  const name = topicName.trim();
  try {
    const result = await api(`/api/workgroups/${workgroupId}/conversations`, {
      method: "POST",
      body: {
        kind: "topic",
        topic: name,
        name: name,
        description: "",
        participant_user_ids: [],
        participant_agent_ids: [],
      },
    });
    const data = state.treeData[workgroupId];
    if (data) {
      await refreshWorkgroupTree(data.workgroup);
      renderTree();
    }
    if (result?.id) {
      await selectConversation(workgroupId, result.id, `topic:${workgroupId}:${result.id}`);
    }
    flash(`Topic "${name}" created`, "success");
  } catch (error) {
    flash(error.message || "Failed to create topic", "error");
  }
}

function openTopicSettings(workgroupId, conversationId) {
  const data = state.treeData[workgroupId];
  const conversation = data?.topics.find((item) => item.id === conversationId);
  if (!data || !conversation) {
    flash("Topic not found", "error");
    return;
  }

  const editable = conversation.kind === "topic";
  const canClearHistory = editable && isWorkgroupOwner(workgroupId);
  const disabledAttr = editable ? "" : "disabled";
  const note = editable
    ? canClearHistory
      ? ""
      : "<p class='meta settings-note'>Only workgroup owners can clear topic history.</p>"
    : "<p class='meta settings-note'>Administration topic settings are managed by the system.</p>";
  const clearHistoryButton = editable
    ? `<button type="button" class="danger" data-action="clear-topic-history" ${canClearHistory ? "" : "disabled"}>Clear history</button>`
    : "";

  openSettingsModal({
    title: "Topic settings",
    subtitle: `${data.workgroup.name} · ${topicDisplayName(conversation)}`,
    formHtml: `
      <label class="settings-field">
        <span class="settings-label">Topic key</span>
        <input name="topic" type="text" required maxlength="120" value="${escapeHtml(conversation.topic || "")}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Display name</span>
        <input name="name" type="text" required maxlength="120" value="${escapeHtml(topicDisplayName(conversation))}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="4" ${disabledAttr}>${escapeHtml(conversation.description || "")}</textarea>
      </label>
      ${note}
      <div class="settings-actions">
        ${clearHistoryButton}
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
        throw new Error("Topic key cannot be empty");
      }
      if (!name) {
        throw new Error("Display name cannot be empty");
      }

      const updated = await api(`/api/workgroups/${workgroupId}/conversations/${conversationId}`, {
        method: "PATCH",
        body: { topic, name, description },
      });
      applyTopicUpdateInState(workgroupId, updated);
      flash("Topic settings saved", "success");
    },
    onRender: (form) => {
      const clearButton = form.querySelector("[data-action='clear-topic-history']");
      if (!(clearButton instanceof HTMLButtonElement)) {
        return;
      }

      clearButton.addEventListener("click", async () => {
        if (!canClearHistory) {
          return;
        }

        const confirmed = window.confirm(
          `Clear all messages for "${topicDisplayName(conversation)}"? This cannot be undone.`,
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
              ? `Cleared ${deletedMessages} message${deletedMessages === 1 ? "" : "s"} from topic history`
              : "Topic history is already empty",
            "success",
          );
        } catch (error) {
          flash(error.message || "Failed to clear topic history", "error");
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

  const [availableTools, learnings] = await Promise.all([
    api(`/api/workgroups/${workgroupId}/tools`).catch(() => []),
    api(`/api/workgroups/${workgroupId}/agents/${agentId}/learnings`).catch(() => null),
  ]);

  const editable = isWorkgroupOwner(workgroupId);
  const disabledAttr = editable ? "" : "disabled";
  const ownerNote = editable ? "" : "<p class='meta settings-note'>Only workgroup owners can edit agent settings.</p>";
  const clearConversationAction = editable
    ? '<button type="button" class="danger" data-action="settings-clear-agent-conversation">Clear conversation</button>'
    : "";

  const currentIcon = agent.icon || "";
  const iconPreviewContent = currentIcon
    ? `<img src="${escapeHtml(currentIcon)}" alt="" />`
    : generateBotSvg(agent.name);
  const iconUploadHtml = `
    <div class="settings-field">
      <span class="settings-label">Icon</span>
      <div class="icon-upload-wrap">
        <div class="icon-upload-preview" id="agent-icon-preview">${iconPreviewContent}</div>
        <div class="icon-upload-controls">
          <input type="file" accept="image/*" id="agent-icon-file" ${disabledAttr} />
          <input type="hidden" name="icon" id="agent-icon-data" value="${escapeHtml(currentIcon)}" />
          ${currentIcon ? `<button type="button" class="secondary" id="agent-icon-remove" ${disabledAttr} style="font-size:0.75rem;padding:4px 8px;">Remove</button>` : ""}
        </div>
      </div>
    </div>
  `;

  openSettingsModal({
    title: "Agent settings",
    subtitle: `${data.workgroup.name} · ${agent.name}`,
    formHtml: `
      ${iconUploadHtml}
      <label class="settings-field">
        <span class="settings-label">Name</span>
        <input name="name" type="text" required maxlength="80" value="${escapeHtml(agent.name)}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Role</span>
        <input name="role" type="text" value="${escapeHtml(agent.role || "")}" ${disabledAttr} />
      </label>
      <label class="settings-field">
        <span class="settings-label">Description</span>
        <textarea name="description" rows="3" ${disabledAttr}>${escapeHtml(agent.description || "")}</textarea>
      </label>
      <label class="settings-field">
        <span class="settings-label">Personality</span>
        <textarea name="personality" rows="3" ${disabledAttr}>${escapeHtml(agent.personality || "")}</textarea>
      </label>
      <label class="settings-field">
        <span class="settings-label">Backstory</span>
        <textarea name="backstory" rows="3" ${disabledAttr}>${escapeHtml(agent.backstory || "")}</textarea>
      </label>
      <div class="settings-grid">
        <label class="settings-field">
          <span class="settings-label">Model</span>
          <input name="model" type="text" value="${escapeHtml(agent.model || "")}" ${disabledAttr} />
        </label>
        <label class="settings-field">
          <span class="settings-label">Temperature</span>
          <input name="temperature" type="number" step="0.01" min="0" max="2" value="${escapeHtml(String(agent.temperature ?? 0.7))}" ${disabledAttr} />
        </label>
        <label class="settings-field">
          <span class="settings-label">Verbosity</span>
          <input name="verbosity" id="agent-verbosity" type="range" step="0.05" min="0" max="1" value="${escapeHtml(
            String(agent.verbosity ?? 0.5),
          )}" ${disabledAttr} />
          <span class="meta">Current: <strong id="agent-verbosity-value">${escapeHtml(
            Number(agent.verbosity ?? 0.5).toFixed(2),
          )}</strong> (low = terse, high = detailed)</span>
        </label>
        <label class="settings-field">
          <span class="settings-label">Response threshold</span>
          <input name="response_threshold" type="number" step="0.01" min="0" max="1" value="${escapeHtml(
            String(agent.response_threshold ?? 0.55),
          )}" ${disabledAttr} />
        </label>
        <label class="settings-field">
          <span class="settings-label">Follow-up minutes</span>
          <input name="follow_up_minutes" type="number" step="1" min="1" max="10080" value="${escapeHtml(
            String(agent.follow_up_minutes ?? 60),
          )}" ${disabledAttr} />
        </label>
      </div>
      <div class="settings-field">
        <span class="settings-label">Tools</span>
        <div class="tool-picker">
          ${(() => {
            const agentToolNames = agent.tool_names || [];
            const knownNames = new Set(availableTools.map((t) => t.name));
            const unknownTools = agentToolNames.filter((n) => !knownNames.has(n));
            const toolItems = availableTools
              .map((t) => {
                const checked = agentToolNames.includes(t.name) ? "checked" : "";
                const typeClass = t.tool_type === "custom" ? " custom" : t.tool_type === "webhook" ? " webhook" : "";
                return `<label class="tool-picker-item">
                  <input type="checkbox" name="tool_names" value="${escapeHtml(t.name)}" ${checked} ${disabledAttr} />
                  <div>
                    <span class="tool-picker-name">${escapeHtml(t.display_name || t.name)}</span>
                    <span class="tool-picker-type${typeClass}">${escapeHtml(t.tool_type || "builtin")}</span>
                    ${t.description ? `<span class="tool-picker-desc meta">${escapeHtml(t.description)}</span>` : ""}
                  </div>
                </label>`;
              })
              .join("");
            const unknownItems = unknownTools
              .map((n) => {
                return `<label class="tool-picker-item">
                  <input type="checkbox" name="tool_names" value="${escapeHtml(n)}" checked ${disabledAttr} />
                  <div>
                    <span class="tool-picker-name" style="font-style:italic">${escapeHtml(n)}</span>
                    <span class="tool-picker-type unknown">unknown</span>
                  </div>
                </label>`;
              })
              .join("");
            const all = toolItems + unknownItems;
            return all || '<div class="tool-picker-empty">No tools available</div>';
          })()}
        </div>
      </div>
      ${(() => {
        if (!learnings) return "";
        const { learning_state, sentiment_state, memories, recent_signals } = learnings;
        const hasBiases = learning_state && Object.keys(learning_state).length > 0;
        const hasSentiment = sentiment_state && Object.keys(sentiment_state).length > 0;
        const hasMemories = memories && memories.length > 0;
        const hasSignals = recent_signals && recent_signals.length > 0;
        if (!hasBiases && !hasSentiment && !hasMemories && !hasSignals) {
          return `<div class="learnings-section"><span class="settings-label">Learnings</span><div class="learnings-empty">No learnings recorded yet.</div></div>`;
        }

        let html = '<div class="learnings-section"><span class="settings-label">Learnings</span>';

        if (hasBiases || hasSentiment) {
          html += '<div class="learnings-subsection"><span class="meta" style="font-weight:600">Current Disposition</span><div class="learnings-biases">';
          if (hasBiases) {
            for (const [k, v] of Object.entries(learning_state)) {
              html += `<div class="learnings-bias-item"><span class="learnings-bias-label">${escapeHtml(k.replace(/_/g, " "))}</span><span class="learnings-bias-value">${escapeHtml(typeof v === "number" ? v.toFixed(3) : String(v))}</span></div>`;
            }
          }
          if (hasSentiment) {
            for (const [k, v] of Object.entries(sentiment_state)) {
              html += `<div class="learnings-bias-item"><span class="learnings-bias-label">${escapeHtml(k.replace(/_/g, " "))}</span><span class="learnings-bias-value">${escapeHtml(typeof v === "number" ? v.toFixed(3) : String(v))}</span></div>`;
            }
          }
          html += '</div></div>';
        }

        if (hasMemories) {
          html += '<div class="learnings-subsection"><span class="meta" style="font-weight:600">Long-term Memories</span><div class="learnings-list">';
          for (const m of memories) {
            const typeClass = { insight: "insight", correction: "correction", pattern: "pattern", domain_knowledge: "domain-knowledge" }[m.memory_type] || "";
            html += `<div class="learnings-item"><div class="learnings-item-header"><span class="learnings-type ${escapeHtml(typeClass)}">${escapeHtml(m.memory_type.replace(/_/g, " "))}</span><span class="learnings-meta">${Math.round(m.confidence * 100)}% confidence</span></div><div class="learnings-content">${escapeHtml(m.content)}</div>${m.source_summary ? `<div class="learnings-meta">${escapeHtml(m.source_summary)}</div>` : ""}</div>`;
          }
          html += '</div></div>';
        }

        if (hasSignals) {
          html += '<div class="learnings-subsection"><span class="meta" style="font-weight:600">Recent Signals</span><div class="learnings-list">';
          for (const s of recent_signals) {
            const brief = Object.entries(s.value || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
            const ts = new Date(s.created_at).toLocaleString();
            html += `<div class="learnings-item compact"><div class="learnings-item-header"><span class="learnings-type signal">${escapeHtml(s.signal_type.replace(/_/g, " "))}</span><span class="learnings-meta">${escapeHtml(ts)}</span></div>${brief ? `<div class="learnings-content">${escapeHtml(brief)}</div>` : ""}</div>`;
          }
          html += '</div></div>';
        }

        html += '</div>';
        return html;
      })()}
      ${ownerNote}
      <div class="settings-actions">
        ${clearConversationAction}
        <button type="button" class="secondary" data-action="settings-cancel">Cancel</button>
        <button type="submit" ${disabledAttr}>Save</button>
      </div>
    `,
    onSubmit: async (formData) => {
      if (!editable) {
        return;
      }

      const temperature = Number(formData.get("temperature"));
      const responseThreshold = Number(formData.get("response_threshold"));
      const followUpMinutes = Number.parseInt(String(formData.get("follow_up_minutes") || ""), 10);
      if (!Number.isFinite(temperature)) {
        throw new Error("Temperature must be a number");
      }
      const verbosity = Number(formData.get("verbosity"));
      if (!Number.isFinite(verbosity)) {
        throw new Error("Verbosity must be a number");
      }
      if (!Number.isFinite(responseThreshold)) {
        throw new Error("Response threshold must be a number");
      }
      if (!Number.isFinite(followUpMinutes)) {
        throw new Error("Follow-up minutes must be a number");
      }

      const iconValue = String(formData.get("icon") || "");
      const payload = {
        name: String(formData.get("name") || "").trim(),
        role: String(formData.get("role") || "").trim(),
        description: String(formData.get("description") || "").trim(),
        personality: String(formData.get("personality") || "").trim(),
        backstory: String(formData.get("backstory") || "").trim(),
        model: String(formData.get("model") || "").trim(),
        temperature,
        verbosity,
        response_threshold: responseThreshold,
        follow_up_minutes: followUpMinutes,
        tool_names: formData.getAll("tool_names"),
        icon: iconValue,
      };

      if (!payload.name) {
        throw new Error("Agent name cannot be empty");
      }
      if (!payload.model) {
        throw new Error("Model cannot be empty");
      }

      const updated = await api(`/api/workgroups/${workgroupId}/agents/${agentId}`, {
        method: "PATCH",
        body: payload,
      });
      applyAgentUpdateInState(workgroupId, updated);
      flash("Agent settings saved", "success");
    },
    onRender: (form) => {
      const slider = form.querySelector("#agent-verbosity");
      const valueNode = form.querySelector("#agent-verbosity-value");
      if (slider && valueNode) {
        const sync = () => {
          valueNode.textContent = Number(slider.value).toFixed(2);
        };
        sync();
        slider.addEventListener("input", sync);
      }

      const iconFileInput = form.querySelector("#agent-icon-file");
      const iconDataInput = form.querySelector("#agent-icon-data");
      const iconPreview = form.querySelector("#agent-icon-preview");
      const iconRemoveBtn = form.querySelector("#agent-icon-remove");

      if (iconFileInput && iconDataInput && iconPreview) {
        iconFileInput.addEventListener("change", () => {
          const file = iconFileInput.files?.[0];
          if (!file) return;
          const reader = new FileReader();
          reader.onload = () => {
            const img = new Image();
            img.onload = () => {
              const canvas = document.createElement("canvas");
              canvas.width = 64;
              canvas.height = 64;
              const ctx = canvas.getContext("2d");
              ctx.drawImage(img, 0, 0, 64, 64);
              const dataUrl = canvas.toDataURL("image/png");
              iconDataInput.value = dataUrl;
              iconPreview.innerHTML = `<img src="${dataUrl}" alt="" />`;
              if (iconRemoveBtn) iconRemoveBtn.style.display = "";
            };
            img.src = reader.result;
          };
          reader.readAsDataURL(file);
        });
      }

      if (iconRemoveBtn && iconDataInput && iconPreview) {
        iconRemoveBtn.addEventListener("click", () => {
          iconDataInput.value = "";
          iconPreview.innerHTML = generateBotSvg(agent.name);
          iconRemoveBtn.style.display = "none";
          if (iconFileInput) iconFileInput.value = "";
        });
      }

      const clearButton = form.querySelector("[data-action='settings-clear-agent-conversation']");
      if (!clearButton) {
        return;
      }
      clearButton.addEventListener("click", async () => {
        const confirmed = window.confirm(
          `Clear all messages in your conversation with ${agent.name}? This cannot be undone.`,
        );
        if (!confirmed) {
          return;
        }

        const originalLabel = clearButton.textContent || "Clear conversation";
        clearButton.disabled = true;
        clearButton.textContent = "Clearing...";
        try {
          const cleared = await api(`/api/workgroups/${workgroupId}/agents/${agentId}/clear-conversation`, {
            method: "POST",
          });

          const treeData = state.treeData[workgroupId];
          if (treeData) {
            await refreshWorkgroupTree(treeData.workgroup);
            renderTree();
          }

          const isActiveAgentConversation =
            state.selectedWorkgroupId === workgroupId &&
            state.activeNodeKey === `agent:${workgroupId}:${agentId}` &&
            Boolean(state.activeConversationId);

          if (isActiveAgentConversation && state.activeConversationId) {
            delete state.thinkingByConversation[state.activeConversationId];
            await loadMessages();
          }

          const deletedMessages = Number(cleared?.deleted_messages || 0);
          if (deletedMessages > 0) {
            const suffix = deletedMessages === 1 ? "" : "s";
            flash(`Cleared ${deletedMessages} message${suffix}`, "success");
          } else {
            flash("No messages to clear", "info");
          }
        } catch (error) {
          flash(error.message || "Failed to clear conversation", "error");
        } finally {
          clearButton.disabled = false;
          clearButton.textContent = originalLabel;
        }
      });
    },
  });
}

async function refreshWorkgroupTree(workgroup) {
  const [conversations, members, agents, crossGroupTasks] = await Promise.all([
    api(`/api/workgroups/${workgroup.id}/conversations`),
    api(`/api/workgroups/${workgroup.id}/members`),
    api(`/api/workgroups/${workgroup.id}/agents?include_hidden=true`),
    api(`/api/workgroups/${workgroup.id}/cross-group-tasks`).catch(() => []),
  ]);

  const topics = conversations.filter((item) => item.kind === "topic" || item.kind === "admin");
  const directs = conversations.filter((item) => item.kind === "direct");

  state.treeData[workgroup.id] = {
    workgroup,
    topics,
    directs,
    members,
    agents,
    crossGroupTasks: crossGroupTasks || [],
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
  if (!state.workgroups.length) {
    node.innerHTML = "<p class='tree-caption'>No workgroups yet.</p>";
    updateMetrics();
    return;
  }

  const html = state.workgroups
    .map((workgroup) => {
      const data = state.treeData[workgroup.id];
      if (!data) {
        return "";
      }

      const isExpanded =
        workgroup.id === state.selectedWorkgroupId || Boolean(state.expandedWorkgroupIds[workgroup.id]);
      const groupOpen = isExpanded ? "open" : "";

      const topicNodes = data.topics.length
        ? data.topics
            .map((conversation) => {
              const key = `topic:${workgroup.id}:${conversation.id}`;
              const activeClass = state.activeNodeKey === key ? "active" : "";
              const isAdmin = conversation.kind === "admin";
              const classes = `tree-button ${isAdmin ? "admin " : ""}${activeClass}`.trim();
              const displayName = topicDisplayName(conversation);
              const label = isAdmin ? escapeHtml(displayName) : `# ${escapeHtml(displayName)}`;
              return `
                <div class="tree-item-row">
                  <button class="${classes}" data-action="open-topic" data-workgroup="${escapeHtml(workgroup.id)}" data-conversation="${escapeHtml(conversation.id)}">${label}</button>
                  <button
                    type="button"
                    class="tree-gear"
                    data-action="settings-topic"
                    data-workgroup="${escapeHtml(workgroup.id)}"
                    data-conversation="${escapeHtml(conversation.id)}"
                    aria-label="Topic settings for ${escapeHtml(displayName)}"
                  >${GEAR_ICON_SVG}</button>
                </div>
              `;
            })
            .join("")
        : "<div class='tree-caption'>No topics</div>";

      const taskList = data.crossGroupTasks || [];
      const taskNodes = taskList.length
        ? taskList.map((task) => {
            const direction = task.target_workgroup_id === workgroup.id ? "incoming" : "outgoing";
            const key = `task:${workgroup.id}:${task.id}`;
            const activeClass = state.activeNodeKey === key ? "active" : "";
            return `
              <button class="tree-button ${activeClass}" data-action="open-task" data-workgroup="${escapeHtml(workgroup.id)}" data-task="${escapeHtml(task.id)}">
                <span class="task-direction">[${direction}]</span>
                ${escapeHtml(task.title)}
                <span class="task-badge ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
              </button>
            `;
          }).join("")
        : "<div class='tree-caption'>No cross-group tasks</div>";

      const humanNodes = data.members
        .map((member) => {
          const name = member.name || member.email;
          const roleSuffix = member.role === "owner" ? " (owner)" : "";
          const selfSuffix = member.user_id === state.user?.id ? " (you)" : "";
          const label = `${escapeHtml(name)}${selfSuffix}${roleSuffix}`;
          const memberAvatar = member.picture
            ? `<span class="tree-avatar human"><img src="${escapeHtml(member.picture)}" alt="" /></span>`
            : `<span class="tree-avatar human">${generateHumanSvg(name)}</span>`;

          if (member.user_id === state.user?.id) {
            return `<div class="tree-member-row">${memberAvatar}<span>${label}</span></div>`;
          }

          const key = `member:${workgroup.id}:${member.user_id}`;
          const activeClass = state.activeNodeKey === key ? "active" : "";
          return `<button class="tree-button member ${activeClass}" data-action="open-member" data-workgroup="${escapeHtml(workgroup.id)}" data-member="${escapeHtml(member.user_id)}">${memberAvatar}<span>${label}</span></button>`;
        })
        .join("");

      const agentNodes = (data.agents || [])
        .filter((agent) => agent.description !== "__system_admin_agent__")
        .map((agent) => {
          const key = `agent:${workgroup.id}:${agent.id}`;
          const activeClass = state.activeNodeKey === key ? "active" : "";
          const agentAvatar = agent.icon
            ? `<span class="tree-avatar agent"><img src="${escapeHtml(agent.icon)}" alt="" /></span>`
            : `<span class="tree-avatar agent">${generateBotSvg(agent.name)}</span>`;
          return `
            <div class="tree-item-row">
              <button class="tree-button member ${activeClass}" data-action="open-agent" data-workgroup="${escapeHtml(workgroup.id)}" data-agent="${escapeHtml(agent.id)}">
                ${agentAvatar}
                <span>${escapeHtml(agent.name)}</span>
              </button>
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
        })
        .join("");
      const workgroupFiles = normalizeWorkgroupFiles(data.workgroup?.files);
      const selectedFileId = state.selectedWorkgroupFileIdByWorkgroup[workgroup.id] || "";
      const selectedFile = workgroupFiles.find((item) => item.id === selectedFileId) || null;
      const canManageFiles = isWorkgroupOwner(workgroup.id);
      const canEditSelectedFile = canManageFiles && Boolean(selectedFileId);
      const fileOwnerNote = canManageFiles ? "" : "<div class='finder-owner-note'>Only workgroup owners can manage files.</div>";
      const fileTools = `
        <div class="file-tools">
          <button type="button" class="tree-tool" data-action="file-add" data-workgroup="${escapeHtml(workgroup.id)}" ${
            canManageFiles ? "" : "disabled"
          }>Add</button>
          <button type="button" class="tree-tool" data-action="file-edit" data-workgroup="${escapeHtml(workgroup.id)}" ${
            canEditSelectedFile ? "" : "disabled"
          }>Edit</button>
          <button type="button" class="tree-tool" data-action="file-rename" data-workgroup="${escapeHtml(workgroup.id)}" ${
            canEditSelectedFile ? "" : "disabled"
          }>Rename</button>
          <button type="button" class="tree-tool danger" data-action="file-delete" data-workgroup="${escapeHtml(workgroup.id)}" ${
            canEditSelectedFile ? "" : "disabled"
          }>Delete</button>
        </div>
      `;
      const fileNodes = workgroupFiles.length
        ? renderWorkgroupFileTreeNode(buildWorkgroupFileTree(workgroupFiles), workgroup.id, selectedFileId, 0, "", canManageFiles)
        : "<div class='finder-empty'>No files in this workgroup</div>";
      const fileCountLabel = `${workgroupFiles.length} item${workgroupFiles.length === 1 ? "" : "s"}`;
      const fileStatus = selectedFile ? `Selected: ${selectedFile.path}` : fileCountLabel;

      return `
        <details class="tree-workgroup" data-workgroup="${escapeHtml(workgroup.id)}" ${groupOpen}>
          <summary>
            <span class="tree-workgroup-name">${escapeHtml(workgroup.name)}</span>
            <span class="tree-summary-right">
              <span class="tree-caption">${escapeHtml(workgroup.id.slice(0, 8))}</span>
              <button
                type="button"
                class="tree-gear summary"
                data-action="settings-workgroup"
                data-workgroup="${escapeHtml(workgroup.id)}"
                aria-label="Workgroup settings for ${escapeHtml(workgroup.name)}"
              >${GEAR_ICON_SVG}</button>
            </span>
          </summary>

          <div class="tree-section">
            <div class="tree-section-title"><span>Topics</span><button type="button" class="tree-tool" data-action="create-topic" data-workgroup="${escapeHtml(workgroup.id)}">+</button></div>
            <div class="tree-list">${topicNodes}</div>
          </div>

          <div class="tree-section">
            <div class="tree-section-title">Tasks</div>
            <div class="tree-list">${taskNodes}</div>
            <button type="button" class="tree-tool" data-action="browse-services" data-workgroup="${escapeHtml(workgroup.id)}">Browse Services</button>
          </div>

          <div class="tree-section">
            <div class="tree-section-title">Members</div>
            <div class="tree-subtitle">Humans</div>
            <div class="tree-list">${humanNodes || "<div class='tree-caption'>No human members</div>"}</div>
            <div class="tree-subtitle">Agents</div>
            <div class="tree-list">${agentNodes || "<div class='tree-caption'>No agents</div>"}</div>
          </div>

          <div class="tree-section">
            <div class="tree-section-title">Files</div>
            <div class="finder-panel">
              <div class="finder-toolbar">
                ${fileTools}
                ${fileOwnerNote}
              </div>
              <div class="finder-columns">
                <span>Name</span>
                <span>Kind</span>
              </div>
              <div class="workgroup-files-tree blade finder-tree">${fileNodes}</div>
              <div class="finder-status" title="${escapeHtml(fileStatus)}">${escapeHtml(fileStatus)}</div>
            </div>
          </div>
        </details>
      `;
    })
    .join("");

  node.innerHTML = html;
  updateMetrics();
}

async function loadWorkgroups() {
  state.workgroups = await api("/api/workgroups");
  state.treeData = {};
  const workgroupIds = new Set(state.workgroups.map((workgroup) => workgroup.id));
  state.expandedWorkgroupIds = Object.fromEntries(
    Object.entries(state.expandedWorkgroupIds).filter(([workgroupId, expanded]) => expanded && workgroupIds.has(workgroupId))
  );

  await Promise.all(state.workgroups.map((workgroup) => refreshWorkgroupTree(workgroup)));

  if (!state.workgroups.length) {
    state.selectedWorkgroupId = "";
    clearActiveConversationUI();
    renderTree();
    return;
  }

  let targetWorkgroupId = state.selectedWorkgroupId;
  if (!targetWorkgroupId || !state.treeData[targetWorkgroupId]) {
    targetWorkgroupId = state.workgroups[0].id;
  }

  const existingConversation =
    targetWorkgroupId === state.selectedWorkgroupId
      ? conversationById(targetWorkgroupId, state.activeConversationId)
      : null;
  const targetConversation = existingConversation || fallbackConversation(targetWorkgroupId);

  if (!targetConversation) {
    state.selectedWorkgroupId = targetWorkgroupId;
    clearActiveConversationUI();
    renderTree();
    return;
  }

  const targetNodeKey = nodeKeyForConversation(targetWorkgroupId, targetConversation);
  const selectionChanged =
    state.selectedWorkgroupId !== targetWorkgroupId || state.activeConversationId !== targetConversation.id;
  if (selectionChanged) {
    await selectConversation(targetWorkgroupId, targetConversation.id, targetNodeKey);
    return;
  }

  state.selectedWorkgroupId = targetWorkgroupId;
  state.activeNodeKey = targetNodeKey || state.activeNodeKey;
  refreshActiveConversationHeader();
  renderTree();
  if (state.activeConversationId && state.activeMessages.length) {
    renderMessages(state.activeMessages);
  }
}

async function selectConversation(workgroupId, conversationId, nodeKey = "") {
  if (state.fileOverlayOpen) {
    closeFileOverlay();
  }

  state.selectedWorkgroupId = workgroupId;
  state.activeConversationId = conversationId;
  state.activeNodeKey = nodeKey;
  state.usagePollCounter = 0;

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

  qs("copy-chat").classList.toggle("hidden", !messages.length);

  if (!messages.length && !pending) {
    node.innerHTML = "<p class='meta'>No messages yet.</p>";
    updateMetrics();
    return;
  }

  const messageHtml = messages
    .map((message) => {
      const rowClass = message.sender_type === "system" ? "system" : message.sender_type === "agent" ? "agent" : "user";
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
            <div class="message-text">${message.sender_type === "system" ? '<span class="synced-badge">[synced]</span> ' : ''}${(() => { const fc = parseFileContext(message.content); if (fc) return `<div class="message-file-context" onclick="this.classList.toggle('expanded')"><span class="message-file-context-toggle">\u{1F4CE} ${escapeHtml(fc.path)}</span><pre class="message-file-context-content">${escapeHtml(fc.fileContent)}</pre></div>${escapeHtml(fc.message)}`; return escapeHtml(message.content); })()}</div>
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
  renderMessages(messages);
  return messages;
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
      el.textContent =
        formatTokenCount(data.total_tokens) +
        " tokens | ~$" +
        data.estimated_cost_usd.toFixed(4) +
        " | " +
        data.api_calls +
        " API call" +
        (data.api_calls !== 1 ? "s" : "");
      el.classList.remove("hidden");
    } else if (el) {
      el.classList.add("hidden");
    }
  } catch {
    if (el) el.classList.add("hidden");
  }
}

function startPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }

  state.pollTimer = setInterval(async () => {
    if (!state.token) {
      return;
    }

    try {
      const beforeLatestId = state.activeMessages.length ? state.activeMessages[state.activeMessages.length - 1].id : "";
      const shouldWatchTree =
        Boolean(state.selectedWorkgroupId) &&
        Boolean(state.activeConversationId) &&
        isAdminConversation(state.selectedWorkgroupId, state.activeConversationId);

      await api("/api/agents/tick", { method: "POST" });
      let polledMessages = [];
      if (state.activeConversationId) {
        polledMessages = await loadMessages();
        state.usagePollCounter = (state.usagePollCounter || 0) + 1;
        if (state.usagePollCounter >= 8) {
          state.usagePollCounter = 0;
          loadConversationUsage(state.activeConversationId);
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

      if (shouldWatchTree) {
        const afterLatestId = polledMessages.length ? polledMessages[polledMessages.length - 1].id : "";
        if (afterLatestId && afterLatestId !== beforeLatestId) {
          await loadWorkgroups();
        }
      }
    } catch (error) {
      console.error(error);
      if (error && error.status === 401) {
        return;
      }
      try {
        await loadWorkgroups();
      } catch (reloadError) {
        console.error(reloadError);
      }
    }
  }, 4000);
}

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
  await loadWorkgroups();
  startPolling();
}

function signOut() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  state.user = null;
  state.token = "";
  state.workgroups = [];
  state.treeData = {};
  state.workgroupTemplates = [];
  state.workgroupCreateTemplateKey = "";
  state.workgroupCreateFiles = [];
  state.workgroupCreateAgents = [];
  state.selectedWorkgroupId = "";
  state.activeConversationId = "";
  state.activeNodeKey = "";
  state.selectedWorkgroupFileIdByWorkgroup = {};
  state.activeMessages = [];
  state.thinkingByConversation = {};
  state.fileOverlayOpen = false;
  state.fileOverlayWorkgroupId = "";
  state.fileOverlayFileId = "";
  state.fileOverlayShowRaw = false;

  localStorage.removeItem("teaparty_token");

  closeFileOverlay();
  renderTree();
  renderMessages([]);
  setTextIfPresent("active-conversation", "No active conversation");
  setTextIfPresent("active-context", "Use the tree to open a topic, member DM, or administration conversation.");
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
  qs("treeview").addEventListener(
    "toggle",
    (event) => {
      const target = event.target;
      if (!(target instanceof HTMLDetailsElement) || !target.classList.contains("tree-workgroup")) {
        return;
      }

      const workgroupId = target.dataset.workgroup || "";
      if (!workgroupId) {
        return;
      }

      if (target.open) {
        // Accordion: close every other workgroup
        state.expandedWorkgroupIds = { [workgroupId]: true };
        document.querySelectorAll("details.tree-workgroup").forEach((el) => {
          if (el !== target && el.open) {
            el.open = false;
          }
        });
        // Close file preview if it belonged to a now-closed workgroup
        if (state.fileOverlayOpen && state.fileOverlayWorkgroupId !== workgroupId) {
          closeFileOverlay();
        }
      } else {
        delete state.expandedWorkgroupIds[workgroupId];
        // Close file preview if it belongs to this workgroup
        if (state.fileOverlayOpen && state.fileOverlayWorkgroupId === workgroupId) {
          closeFileOverlay();
        }
      }
    },
    true
  );

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
    const workgroupId = button.dataset.workgroup || "";
    if (!workgroupId) {
      return;
    }

    if (action && (action.startsWith("settings-") || action.startsWith("file-") || action === "select-file" || action === "browse-services" || action === "create-topic")) {
      event.preventDefault();
      event.stopPropagation();
    }

    try {
      if (action === "open-topic") {
        const conversationId = button.dataset.conversation || "";
        if (conversationId) {
          await selectConversation(workgroupId, conversationId, `topic:${workgroupId}:${conversationId}`);
        }
      }

      if (action === "open-member") {
        const memberId = button.dataset.member || "";
        if (!memberId) {
          return;
        }
        await openMemberConversation(workgroupId, memberId);
      }

      if (action === "open-agent") {
        const agentId = button.dataset.agent || "";
        if (!agentId) {
          return;
        }
        await openAgentConversation(workgroupId, agentId);
      }

      if (action === "settings-workgroup") {
        const wgData = state.treeData[workgroupId];
        if (wgData) {
          const admin = wgData.topics.find((c) => c.kind === "admin");
          if (admin) {
            await selectConversation(workgroupId, admin.id, `topic:${workgroupId}:${admin.id}`);
          }
          const files = normalizeWorkgroupFiles(wgData.workgroup?.files);
          const configFile = files.find((f) => f.path === "workgroup.json");
          if (configFile) {
            state.expandedWorkgroupIds[workgroupId] = true;
            state.selectedWorkgroupFileIdByWorkgroup[workgroupId] = configFile.id;
            openFileOverlay(workgroupId, configFile.id);
          } else {
            openConfigOverlay(workgroupId, "workgroup.json", wgData.workgroup);
          }
        }
      }

      if (action === "settings-topic") {
        const conversationId = button.dataset.conversation || "";
        if (!conversationId) {
          return;
        }
        const topicData = state.treeData[workgroupId];
        const conversation = topicData?.topics.find((c) => c.id === conversationId);
        if (conversation) {
          await openConfigAndAdmin(workgroupId, `topic: ${topicDisplayName(conversation)}`, conversation);
        }
      }

      if (action === "settings-agent") {
        const agentId = button.dataset.agent || "";
        if (!agentId) {
          return;
        }
        const agentData = state.treeData[workgroupId];
        const agent = agentData?.agents?.find((a) => a.id === agentId);
        if (agent) {
          await openConfigAndAdmin(workgroupId, `agent: ${agent.name}`, agent);
        }
      }

      if (action === "select-file") {
        const fileId = button.dataset.fileId || "";
        if (!fileId) {
          return;
        }
        state.expandedWorkgroupIds[workgroupId] = true;
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

      if (action === "browse-services") {
        browseServices(workgroupId);
      }

      if (action === "create-topic") {
        await createTopicPrompt(workgroupId);
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
}

function bindEvents() {
  const themeToggle = qs("theme-toggle");
  themeToggle.addEventListener("change", () => {
    applyTheme(themeToggle.checked ? "dark" : "light");
  });

  qs("settings-close").addEventListener("click", () => {
    requestSettingsClose({ saveIfDirty: true }).catch((error) => {
      flash(error.message || "Failed to close settings", "error");
    });
  });

  qs("copy-chat").addEventListener("click", copyChatToClipboard);

  qs("file-overlay-close").addEventListener("click", closeFileOverlay);

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
    if (state.fileOverlayViewMode === "form" && state.fileOverlayParsedJson !== null) {
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
      } else if (state.fileOverlayOpen) {
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

      const adminId = adminConversationId(group.id);
      if (adminId) {
        await selectConversation(group.id, adminId, `topic:${group.id}:${adminId}`);
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

    const optimisticId = `local-${Date.now()}`;
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
    qs("message-content").value = "";

    let posted = null;
    try {
      const envelope = await api(`/api/conversations/${state.activeConversationId}/messages`, {
        method: "POST",
        body: { content: fullContent },
      });

      posted = envelope?.posted;
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
          const content = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
            reader.readAsText(file);
          });

          const path = `topics/uploads/${file.name}`;
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
