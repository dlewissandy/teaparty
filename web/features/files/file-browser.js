// File browser for the Files tab of the right panel.
// Renders breadcrumbs, directory listing, and toolbar.
// Emits bus events when a file is selected or the path changes.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import {
  escapeHtml,
  normalizeWorkgroupFiles,
  normalizePathEntry,
  newWorkgroupFileId,
  urlLabel,
} from '../../core/utils.js';
import { ICON } from '../../core/constants.js';
import { flash } from '../../components/shared/flash.js';

// ---- file-tree builder (local, no state dependency) ----

function buildFileTree(fileEntries) {
  const root = { folders: new Map(), files: [] };

  for (const file of fileEntries) {
    if (/^https?:\/\//i.test(file.path)) {
      root.files.push({
        id: file.id,
        name: urlLabel(file.path),
        path: file.path,
        content: file.content,
        isLink: true,
        _source: file._source,
        _sourceWorkgroupId: file._sourceWorkgroupId,
      });
      continue;
    }

    const normalized = normalizePathEntry(file.path);
    if (!normalized) continue;

    const parts = normalized.split('/').filter(Boolean);
    if (!parts.length) continue;

    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const seg = parts[i];
      if (!node.folders.has(seg)) {
        node.folders.set(seg, { folders: new Map(), files: [] });
      }
      node = node.folders.get(seg);
    }

    const filename = parts[parts.length - 1];
    node.files.push({
      id: file.id,
      name: filename,
      path: normalized,
      content: file.content,
      isLink: false,
      _source: file._source,
      _sourceWorkgroupId: file._sourceWorkgroupId,
    });
  }

  return root;
}

// ---- Save helper ----

async function saveWorkgroupFiles(store, workgroupId, files) {
  const result = await api(`/api/workgroups/${workgroupId}/files`, {
    method: 'PUT',
    body: { files },
    retries: 0,
  });
  // Patch local store data
  store.update(s => {
    const wg = s.data.workgroups.find(w => w.id === workgroupId);
    if (wg) wg.files = files;
  });
  return result;
}

// ---- Module state (mutable, local) ----
let _store = null;
let _path = [];             // current directory path segments
let _selectedFileId = '';   // currently selected file id
let _workgroupId = '';      // active workgroup id

// ---- Container refs ----
const breadcrumbsEl = () => document.getElementById('file-breadcrumbs');
const toolbarEl = () => document.getElementById('file-toolbar');
const listingEl = () => document.getElementById('file-listing');

// ---- Helpers ----

function getAllFiles() {
  const s = _store.get();
  if (!_workgroupId) return [];
  const wg = s.data.workgroups.find(w => w.id === _workgroupId);
  return normalizeWorkgroupFiles(wg?.files);
}

function isOwner() {
  const s = _store.get();
  const user = s.auth.user;
  if (!user) return false;
  const wg = s.data.workgroups.find(w => w.id === _workgroupId);
  return wg?.owner_id === user.id || user.is_system_admin;
}

// ---- Rendering ----

function renderBreadcrumbs() {
  const el = breadcrumbsEl();
  if (!el) return;

  const parts = [];

  if (_path.length > 0 || _selectedFileId) {
    parts.push(`<button class="file-browser-crumb" data-crumb-depth="0">Files</button>`);
  } else {
    parts.push(`<span class="file-browser-crumb-current">Files</span>`);
  }

  for (let i = 0; i < _path.length; i++) {
    parts.push(`<span class="file-browser-sep">\u203A</span>`);
    const isLast = i === _path.length - 1 && !_selectedFileId;
    if (isLast) {
      parts.push(`<span class="file-browser-crumb-current">${escapeHtml(_path[i])}</span>`);
    } else {
      parts.push(`<button class="file-browser-crumb" data-crumb-depth="${i + 1}">${escapeHtml(_path[i])}</button>`);
    }
  }

  if (_selectedFileId) {
    const allFiles = getAllFiles();
    const file = allFiles.find(f => f.id === _selectedFileId);
    if (file) {
      const fileName = file.path.split('/').pop() || file.path;
      parts.push(`<span class="file-browser-sep">\u203A</span>`);
      parts.push(`<span class="file-browser-crumb-current">${escapeHtml(fileName)}</span>`);
    }
  }

  el.innerHTML = `<div class="file-browser-breadcrumbs">${parts.join('')}</div>`;
}

function renderToolbar() {
  const el = toolbarEl();
  if (!el) return;

  if (!_workgroupId || !isOwner() || _selectedFileId) {
    el.innerHTML = '';
    return;
  }

  const currentPath = _path.join('/');
  el.innerHTML = `
    <div class="file-browser-toolbar">
      <button type="button" class="file-browser-toolbar-btn" data-browser-action="add-file">+ File</button>
      <button type="button" class="file-browser-toolbar-btn" data-browser-action="new-folder">+ Folder</button>
    </div>
  `;
}

function renderListing(node) {
  const el = listingEl();
  if (!el) return;

  const owner = isOwner();

  const folders = Array.from(node.folders.entries())
    .sort((a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: 'base' }));
  const files = [...node.files]
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));

  if (!folders.length && !files.length) {
    el.innerHTML = '<div class="finder-empty">Empty folder</div>';
    return;
  }

  let html = '';

  const folderIconSvg = ICON.folder;
  const fileIconSvg = ICON.file;
  const linkIconSvg = ICON.link;

  for (const [folderName, folderNode] of folders) {
    const childCount = folderNode.folders.size + folderNode.files.length;
    const itemLabel = childCount + ' item' + (childCount !== 1 ? 's' : '');
    const fullPath = [..._path, folderName].join('/');

    const ownerActions = owner ? `
      <button type="button" data-browser-action="rename-folder" data-folder-path="${escapeHtml(fullPath)}">Rename</button>
      <button type="button" data-browser-action="delete-folder" data-folder-path="${escapeHtml(fullPath)}">Delete</button>
    ` : '';

    const actions = `<span class="file-browser-actions">
      <button type="button" data-browser-action="download-folder" data-folder-path="${escapeHtml(fullPath)}">Download</button>
      ${ownerActions}
    </span>`;

    html += `<div class="file-browser-row">
      <button class="file-browser-item" data-browser-action="drill" data-folder="${escapeHtml(folderName)}">
        <span class="finder-icon folder">${folderIconSvg}</span>
        <span class="file-browser-name">${escapeHtml(folderName)}</span>
        <span class="file-browser-meta">${itemLabel}</span>
      </button>
      ${actions}
    </div>`;
  }

  for (const file of files) {
    const iconSvg = file.isLink ? linkIconSvg : fileIconSvg;
    const iconClass = file.isLink ? 'link' : 'file';

    const ownerActions = owner ? `
      <button type="button" data-browser-action="rename-file" data-file-id="${escapeHtml(file.id)}">Rename</button>
      <button type="button" data-browser-action="delete-file" data-file-id="${escapeHtml(file.id)}">Delete</button>
    ` : '';

    const actions = `<span class="file-browser-actions">
      <button type="button" data-browser-action="download-file" data-file-id="${escapeHtml(file.id)}">Download</button>
      ${ownerActions}
    </span>`;

    html += `<div class="file-browser-row">
      <button class="file-browser-item" data-browser-action="open-file" data-file-id="${escapeHtml(file.id)}">
        <span class="finder-icon ${iconClass}">${iconSvg}</span>
        <span class="file-browser-name">${escapeHtml(file.name)}</span>
        <span class="file-browser-meta">File</span>
      </button>
      ${actions}
    </div>`;
  }

  el.innerHTML = html;
}

function render() {
  const allFiles = getAllFiles();
  const tree = buildFileTree(allFiles);

  // Navigate to current path node
  let node = tree;
  for (const seg of _path) {
    if (node.folders.has(seg)) {
      node = node.folders.get(seg);
    } else {
      _path = [];
      node = tree;
      break;
    }
  }

  renderBreadcrumbs();
  renderToolbar();
  renderListing(node);
}

// ---- File operations ----

async function addFile() {
  const pathPrefix = _path.length ? _path.join('/') + '/' : '';
  const pathInput = window.prompt('File path:', pathPrefix);
  if (!pathInput || !pathInput.trim()) return;

  const path = normalizePathEntry(pathInput.trim());
  if (!path) { flash('Invalid file path', 'error'); return; }

  const allFiles = getAllFiles();
  if (allFiles.some(f => f.path === path)) {
    flash('A file with that path already exists', 'error');
    return;
  }

  const newFile = { id: newWorkgroupFileId(), path, content: '', topic_id: '' };
  try {
    await saveWorkgroupFiles(_store, _workgroupId, [...allFiles, newFile]);
    flash('File added', 'success');
    render();
    selectFile(newFile.id);
  } catch (err) {
    flash(err.message || 'Failed to add file', 'error');
  }
}

async function newFolder() {
  const name = window.prompt('Folder name:');
  if (!name || !name.trim()) return;
  const folderName = normalizePathEntry(name.trim());
  if (!folderName) { flash('Invalid folder name', 'error'); return; }

  const currentPath = _path.join('/');
  const prefix = currentPath ? currentPath + '/' + folderName + '/' : folderName + '/';
  const pathInput = window.prompt('First file in ' + folderName + ':', prefix);
  if (!pathInput || !pathInput.trim()) return;

  const path = normalizePathEntry(pathInput.trim());
  if (!path) { flash('Invalid file path', 'error'); return; }

  const allFiles = getAllFiles();
  if (allFiles.some(f => f.path === path)) {
    flash('A file with that path already exists', 'error');
    return;
  }

  const newFile = { id: newWorkgroupFileId(), path, content: '', topic_id: '' };
  try {
    await saveWorkgroupFiles(_store, _workgroupId, [...allFiles, newFile]);
    flash('Folder and file created', 'success');
    render();
  } catch (err) {
    flash(err.message || 'Failed to create folder', 'error');
  }
}

async function renameFile(fileId) {
  const allFiles = getAllFiles();
  const file = allFiles.find(f => f.id === fileId);
  if (!file) return;

  const newPath = window.prompt('New path:', file.path);
  if (!newPath || !newPath.trim()) return;

  const normalized = normalizePathEntry(newPath.trim());
  if (!normalized) { flash('Invalid path', 'error'); return; }
  if (allFiles.some(f => f.id !== fileId && f.path === normalized)) {
    flash('A file with that path already exists', 'error');
    return;
  }

  const updated = allFiles.map(f => f.id === fileId ? { ...f, path: normalized } : f);
  try {
    await saveWorkgroupFiles(_store, _workgroupId, updated);
    flash('File renamed', 'success');
    render();
  } catch (err) {
    flash(err.message || 'Failed to rename file', 'error');
  }
}

async function deleteFile(fileId) {
  const allFiles = getAllFiles();
  const file = allFiles.find(f => f.id === fileId);
  if (!file) return;

  if (!window.confirm(`Delete "${file.path}"?`)) return;

  const remaining = allFiles.filter(f => f.id !== fileId);
  try {
    await saveWorkgroupFiles(_store, _workgroupId, remaining);
    if (_selectedFileId === fileId) {
      _selectedFileId = '';
      bus.emit('file:deselected');
    }
    flash('File deleted', 'success');
    render();
  } catch (err) {
    flash(err.message || 'Failed to delete file', 'error');
  }
}

async function renameFolder(folderPath) {
  const parts = folderPath.split('/');
  const oldName = parts[parts.length - 1];
  const newName = window.prompt('New folder name:', oldName);
  if (!newName || !newName.trim()) return;

  const normalized = normalizePathEntry(newName.trim());
  if (!normalized) { flash('Invalid folder name', 'error'); return; }

  const parentPath = parts.slice(0, -1).join('/');
  const newFolderPath = parentPath ? parentPath + '/' + normalized : normalized;
  if (newFolderPath === folderPath) return;

  const allFiles = getAllFiles();
  const prefix = folderPath + '/';
  const newPrefix = newFolderPath + '/';

  if (allFiles.some(f => !f.path.startsWith(prefix) && f.path.startsWith(newPrefix))) {
    flash('A folder with that name already exists', 'error');
    return;
  }

  const updated = allFiles.map(f => {
    if (f.path === folderPath || f.path.startsWith(prefix)) {
      return { ...f, path: newFolderPath + f.path.slice(folderPath.length) };
    }
    return f;
  });

  try {
    await saveWorkgroupFiles(_store, _workgroupId, updated);
    // Update local path if browsing inside renamed folder
    const currentPath = _path.join('/');
    if (currentPath === folderPath || currentPath.startsWith(folderPath + '/')) {
      _path = newFolderPath.split('/').concat(_path.slice(folderPath.split('/').length));
    }
    flash('Folder renamed', 'success');
    render();
  } catch (err) {
    flash(err.message || 'Failed to rename folder', 'error');
  }
}

async function deleteFolder(folderPath) {
  if (!window.confirm(`Delete folder "${folderPath}" and all its contents?`)) return;

  const allFiles = getAllFiles();
  const prefix = folderPath + '/';
  const remaining = allFiles.filter(f => f.path !== folderPath && !f.path.startsWith(prefix));

  try {
    await saveWorkgroupFiles(_store, _workgroupId, remaining);
    // Navigate up if we're inside deleted folder
    const currentPath = _path.join('/');
    if (currentPath === folderPath || currentPath.startsWith(folderPath + '/')) {
      _path = folderPath.split('/').slice(0, -1);
    }
    flash('Folder deleted', 'success');
    render();
  } catch (err) {
    flash(err.message || 'Failed to delete folder', 'error');
  }
}

function downloadFile(fileId) {
  const allFiles = getAllFiles();
  const file = allFiles.find(f => f.id === fileId);
  if (!file) { flash('File not found', 'error'); return; }

  const filename = file.path.split('/').pop() || 'download.txt';
  const blob = new Blob([file.content || ''], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadFolder(folderPath) {
  const allFiles = getAllFiles();
  const prefix = folderPath + '/';
  const matching = allFiles.filter(f => f.path.startsWith(prefix));
  if (!matching.length) { flash('No files in this folder', 'info'); return; }

  const entries = matching.map(f => ({
    name: f.path.slice(prefix.length),
    data: new TextEncoder().encode(f.content || ''),
  }));

  const blob = _buildZip(entries);
  const folderName = folderPath.split('/').pop() || 'folder';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = folderName + '.zip';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  flash(`Downloaded ${matching.length} file${matching.length !== 1 ? 's' : ''}`, 'success');
}

function _buildZip(entries) {
  const localHeaders = [];
  const centralHeaders = [];
  let offset = 0;

  for (const { name, data } of entries) {
    const nameBytes = new TextEncoder().encode(name);
    const crc = _crc32(data);

    const local = new Uint8Array(30 + nameBytes.length + data.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0, true);
    lv.setUint16(8, 0, true);
    lv.setUint16(10, 0, true);
    lv.setUint16(12, 0, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, data.length, true);
    lv.setUint32(22, data.length, true);
    lv.setUint16(26, nameBytes.length, true);
    lv.setUint16(28, 0, true);
    local.set(nameBytes, 30);
    local.set(data, 30 + nameBytes.length);
    localHeaders.push(local);

    const central = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0, true);
    cv.setUint16(10, 0, true);
    cv.setUint16(12, 0, true);
    cv.setUint16(14, 0, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, data.length, true);
    cv.setUint32(24, data.length, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint16(30, 0, true);
    cv.setUint16(32, 0, true);
    cv.setUint16(34, 0, true);
    cv.setUint16(36, 0, true);
    cv.setUint32(38, 0, true);
    cv.setUint32(42, offset, true);
    central.set(nameBytes, 46);
    centralHeaders.push(central);

    offset += local.length;
  }

  const centralOffset = offset;
  let centralSize = 0;
  for (const c of centralHeaders) centralSize += c.length;

  const eocd = new Uint8Array(22);
  const ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(4, 0, true);
  ev.setUint16(6, 0, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, centralSize, true);
  ev.setUint32(16, centralOffset, true);
  ev.setUint16(20, 0, true);

  const parts = [...localHeaders, ...centralHeaders, eocd];
  const totalSize = parts.reduce((s, p) => s + p.length, 0);
  const result = new Uint8Array(totalSize);
  let pos = 0;
  for (const part of parts) { result.set(part, pos); pos += part.length; }
  return new Blob([result], { type: 'application/zip' });
}

function _crc32(data) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xEDB88320 : 0);
    }
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

// ---- File selection ----

function selectFile(fileId) {
  _selectedFileId = fileId;
  render();

  const allFiles = getAllFiles();
  const file = allFiles.find(f => f.id === fileId);
  if (file) {
    bus.emit('file:selected', { file, workgroupId: _workgroupId });
  }
}

// ---- Init ----

export function initFileBrowser(store) {
  _store = store;

  // Delegate click events on the listing
  const listingContainer = document.getElementById('file-listing');
  if (listingContainer) {
    listingContainer.addEventListener('click', e => {
      const item = e.target.closest('[data-browser-action]');
      if (!item) return;

      const action = item.dataset.browserAction;
      switch (action) {
        case 'drill': {
          const folderName = item.dataset.folder;
          _path = [..._path, folderName];
          _selectedFileId = '';
          render();
          break;
        }
        case 'open-file': {
          const fileId = item.dataset.fileId;
          selectFile(fileId);
          break;
        }
        case 'add-file':
          addFile();
          break;
        case 'new-folder':
          newFolder();
          break;
        case 'rename-file':
          renameFile(item.dataset.fileId);
          break;
        case 'delete-file':
          deleteFile(item.dataset.fileId);
          break;
        case 'download-file':
          downloadFile(item.dataset.fileId);
          break;
        case 'rename-folder':
          renameFolder(item.dataset.folderPath);
          break;
        case 'delete-folder':
          deleteFolder(item.dataset.folderPath);
          break;
        case 'download-folder':
          downloadFolder(item.dataset.folderPath);
          break;
      }
    });
  }

  // Toolbar clicks (rendered into #file-toolbar)
  const toolbarContainer = document.getElementById('file-toolbar');
  if (toolbarContainer) {
    toolbarContainer.addEventListener('click', e => {
      const btn = e.target.closest('[data-browser-action]');
      if (!btn) return;
      if (btn.dataset.browserAction === 'add-file') addFile();
      if (btn.dataset.browserAction === 'new-folder') newFolder();
    });
  }

  // Breadcrumb navigation
  const breadcrumbContainer = document.getElementById('file-breadcrumbs');
  if (breadcrumbContainer) {
    breadcrumbContainer.addEventListener('click', e => {
      const btn = e.target.closest('[data-crumb-depth]');
      if (!btn) return;
      const depth = parseInt(btn.dataset.crumbDepth, 10);
      _path = _path.slice(0, depth);
      _selectedFileId = '';
      bus.emit('file:deselected');
      render();
    });
  }

  // Bus: open file browser for a workgroup
  bus.on('files:open', ({ workgroupId, path = [] } = {}) => {
    _workgroupId = workgroupId || '';
    _path = path;
    _selectedFileId = '';
    render();
  });

  // Refresh when workgroup data changes
  store.on('data', () => {
    if (_workgroupId) render();
  });

  // Listen for nav changes to update workgroup context
  store.on('nav', s => {
    const wgId = s.nav.activeWorkgroupId;
    if (wgId && wgId !== _workgroupId) {
      _workgroupId = wgId;
      _path = [];
      _selectedFileId = '';
      render();
    }
  });
}
