// Utility functions ported from modules/utils.js.

export function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function linkifyUrls(escaped) {
  return escaped.replace(
    /\bhttps?:\/\/[^\s<>&"')\]]+/g,
    (url) => `<a href="${url.replace(/&amp;/g, '&')}" target="_blank" rel="noopener noreferrer">${url}</a>`,
  );
}

export function parseFileContext(text) {
  const match = text.match(/^\[file: (.+?)\]\n<<<\n([\s\S]*?)\n>>>\n\n([\s\S]*)$/);
  if (match) return { path: match[1], fileContent: match[2], message: match[3] };
  return null;
}

export function isMarkdownFile(filePath) { return /\.md$/i.test(filePath); }
export function isJsonFile(filePath) { return /\.json$/i.test(filePath); }
export function isImageFile(filePath) { return /\.(png|jpe?g|gif|svg|webp|bmp|ico)$/i.test(filePath); }
export function isDataUrl(content) { return /^data:image\//.test(content); }
export function isAgentConfigPath(p) { return /^agents\/[^/]+\.json$/i.test(p); }
export function isWorkgroupConfigPath(p) { return p === 'workgroup.json'; }

export function isAgentConfigShape(d) {
  return d && typeof d === 'object' && !Array.isArray(d)
    && 'name' in d && 'model' in d && 'temperature' in d;
}

export function tryParseJson(content) {
  try { return { ok: true, data: JSON.parse(content) }; }
  catch { return { ok: false, data: null }; }
}

export function normalizePathEntry(value) {
  return value.replaceAll('\\', '/').replace(/\/+/g, '/').replace(/^\/+/, '').replace(/\/+$/, '');
}

export function urlLabel(value) {
  try {
    const parsed = new URL(value);
    const parts = parsed.pathname.split('/').filter(Boolean);
    const leaf = parts.length ? parts[parts.length - 1] : '';
    return leaf ? `${parsed.hostname}/${leaf}` : parsed.hostname;
  } catch { return value; }
}

export function fileBrowserSlug(name) {
  return String(name || '').replace(/[/\\]/g, '_').replace(/\.\./g, '_');
}

export function slugify(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

export function newWorkgroupFileId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `file-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function parseAsUTC(str) {
  if (!str) return new Date(NaN);
  if (!/Z|[+-]\d{2}:\d{2}$/.test(str)) return new Date(str + 'Z');
  return new Date(str);
}

export function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function formatTokenCount(count) {
  if (count >= 1_000_000) return (count / 1_000_000).toFixed(1) + 'M';
  if (count >= 1_000) return (count / 1_000).toFixed(1) + 'k';
  return String(count);
}

export function formatDuration(ms) {
  if (ms < 1000) return ms + 'ms';
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return hours + 'h ' + minutes + 'm';
  if (minutes > 0) return minutes + 'm ' + seconds + 's';
  return seconds + 's';
}

export function toolDisplayLabel(name) {
  return name.replace(/^custom:/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function jobDisplayName(conversation) {
  const explicit = (conversation?.name || '').trim();
  if (explicit) return explicit;
  return (conversation?.topic || '').trim() || 'job';
}

export function normalizeWorkgroupFiles(files) {
  if (!Array.isArray(files)) return [];
  const normalized = [];
  const seenIds = new Set();
  for (const item of files) {
    let id = '', path = '', content = '';
    if (typeof item === 'string') {
      path = item.trim();
    } else if (item && typeof item === 'object') {
      id = String(item.id || '').trim();
      path = String(item.path || '').trim();
      content = typeof item.content === 'string' ? item.content : String(item.content || '');
    }
    if (!path) continue;
    if (!id) id = `legacy:${path}`;
    if (seenIds.has(id)) {
      let suffix = 2;
      while (seenIds.has(`${id}:${suffix}`)) suffix++;
      id = `${id}:${suffix}`;
    }
    const topic_id = (item && typeof item === 'object') ? String(item.topic_id || '') : '';
    seenIds.add(id);
    normalized.push({ id, path, content, topic_id });
  }
  return normalized;
}

export function highlightMentions(html) {
  return html.replace(/@([\w.-]+)/g, (match, name) =>
    `<span class="mention-highlight">@${escapeHtml(name)}</span>`
  );
}
