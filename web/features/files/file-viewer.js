// File content viewer for the Files tab.
// Displays file content based on type: markdown, JSON form, image, or raw text.
// Handles edit/save/delete for workgroup owners.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import {
  escapeHtml,
  normalizeWorkgroupFiles,
  isMarkdownFile,
  isJsonFile,
  isImageFile,
  isDataUrl,
  isAgentConfigPath,
  isWorkgroupConfigPath,
  isAgentConfigShape,
  tryParseJson,
} from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { renderMarkdown } from '../../components/shared/markdown.js';
import { renderJsonForm, renderAgentConfigForm, renderWorkgroupConfigForm, collectJsonFromForm } from './json-form.js';

// ---- Module state ----
let _store = null;
let _workgroupId = '';
let _file = null;       // currently displayed file object
let _viewMode = 'raw';  // 'raw' | 'form'
let _editing = false;
let _showRaw = false;
let _parsedJson = null;

// ---- Container refs ----
const viewerEl = () => document.getElementById('file-viewer');
const dividerEl = () => document.getElementById('file-divider');
const contentEl = () => document.getElementById('file-content');
const renderedEl = () => document.getElementById('file-rendered');
const formEl = () => document.getElementById('file-form');
const rawToggleBtn = () => document.getElementById('file-raw-toggle');
const editBtn = () => document.getElementById('file-edit-btn');
const deleteBtn = () => document.getElementById('file-delete-btn');

// ---- Helpers ----

function isOwner() {
  const s = _store.get();
  const user = s.auth.user;
  if (!user || !_workgroupId) return false;
  const wg = s.data.workgroups.find(w => w.id === _workgroupId);
  return wg?.owner_id === user.id || user.is_system_admin;
}

async function saveFiles(files) {
  const result = await api(`/api/workgroups/${_workgroupId}/files`, {
    method: 'PUT',
    body: { files },
    retries: 0,
  });
  _store.update(s => {
    const wg = s.data.workgroups.find(w => w.id === _workgroupId);
    if (wg) wg.files = files;
  });
  return result;
}

// ---- View mode switching ----

function setViewMode(mode) {
  _viewMode = mode;
  const pre = contentEl();
  const form = formEl();
  const rawBtn = rawToggleBtn();
  if (!pre || !form) return;

  if (mode === 'form') {
    pre.classList.add('hidden');
    form.classList.remove('hidden');
    if (rawBtn) rawBtn.textContent = 'Raw';
  } else {
    pre.classList.remove('hidden');
    form.classList.add('hidden');
    if (rawBtn) rawBtn.textContent = 'Form';
  }
}

function updateEditButton(fileIsOwner, isFormMode, isJsonParsed) {
  const btn = editBtn();
  if (!btn) return;
  if (fileIsOwner && isFormMode && isJsonParsed) {
    btn.textContent = 'Save';
    btn.classList.remove('hidden');
  } else if (fileIsOwner) {
    btn.textContent = 'Edit';
    btn.classList.remove('hidden');
  } else {
    btn.classList.add('hidden');
  }
}

// ---- Edit mode ----

function enterEditMode() {
  if (!_file) return;
  _editing = true;

  const displayPath = _file._originalPath || _file.path;
  const pre = contentEl();

  if (isMarkdownFile(displayPath)) {
    // Replace pre with a textarea for editing
    const ta = document.createElement('textarea');
    ta.className = 'file-edit-textarea';
    ta.value = _file.content;
    ta.id = 'file-edit-textarea';
    pre.replaceWith(ta);

    const btn = editBtn();
    if (btn) btn.textContent = 'Save';
  } else {
    // Plain text editing in pre (contenteditable)
    pre.contentEditable = 'true';
    pre.classList.add('editing');
    const btn = editBtn();
    if (btn) btn.textContent = 'Save';
  }
}

async function saveEdit() {
  if (!_file || !_workgroupId) return;

  const displayPath = _file._originalPath || _file.path;
  let newContent = _file.content;

  if (_viewMode === 'form' && _parsedJson !== null) {
    // Save from JSON form
    const data = collectJsonFromForm(document.getElementById('file-form'));
    if (data === null) return;
    newContent = JSON.stringify(data, null, 2);
  } else if (isMarkdownFile(displayPath)) {
    const ta = document.getElementById('file-edit-textarea');
    if (ta) newContent = ta.value;
  } else {
    const pre = contentEl();
    if (pre) newContent = pre.textContent;
  }

  const s = _store.get();
  const wg = s.data.workgroups.find(w => w.id === _workgroupId);
  const allFiles = normalizeWorkgroupFiles(wg?.files);
  const updated = allFiles.map(f => f.id === _file.id ? { ...f, content: newContent } : f);

  try {
    await saveFiles(updated);
    _file = { ..._file, content: newContent };
    _editing = false;
    flash('File updated', 'success');
    displayFile(_file, _workgroupId);
  } catch (err) {
    flash(err.message || 'Failed to save file', 'error');
  }
}

async function doDelete() {
  if (!_file || !_workgroupId) return;
  if (!window.confirm(`Delete "${_file._originalPath || _file.path}"?`)) return;

  const s = _store.get();
  const wg = s.data.workgroups.find(w => w.id === _workgroupId);
  const allFiles = normalizeWorkgroupFiles(wg?.files);
  const remaining = allFiles.filter(f => f.id !== _file.id);

  try {
    await saveFiles(remaining);
    flash('File deleted', 'success');
    hide();
    bus.emit('file:deselected');
  } catch (err) {
    flash(err.message || 'Failed to delete file', 'error');
  }
}

// ---- Display a file ----

function displayFile(file, workgroupId) {
  _file = file;
  _workgroupId = workgroupId;
  _editing = false;
  _showRaw = false;

  const viewer = viewerEl();
  const divider = dividerEl();
  const pre = contentEl();
  const rendered = renderedEl();
  const form = formEl();
  const rawBtn = rawToggleBtn();
  const editBtnEl = editBtn();
  const delBtn = deleteBtn();

  if (!viewer || !pre || !rendered || !form) return;

  const fileIsOwner = isOwner();
  const displayPath = file._originalPath || file.path;

  pre.textContent = file.content;
  _parsedJson = null;

  // Restore pre if it was replaced with a textarea (from edit mode)
  const existingTa = document.getElementById('file-edit-textarea');
  if (existingTa) {
    const newPre = document.createElement('pre');
    newPre.id = 'file-content';
    newPre.className = 'file-content';
    existingTa.replaceWith(newPre);
  }
  pre.contentEditable = 'false';
  pre.classList.remove('editing');

  if (isJsonFile(displayPath)) {
    const parsed = tryParseJson(file.content);
    _parsedJson = parsed.ok ? parsed.data : null;

    if (parsed.ok) {
      rendered.innerHTML = '';
      rendered.classList.add('hidden');

      if (isAgentConfigPath(displayPath) && isAgentConfigShape(parsed.data)) {
        renderAgentConfigForm(form, parsed.data, !fileIsOwner);
      } else if (isWorkgroupConfigPath(displayPath)) {
        renderWorkgroupConfigForm(form, parsed.data, !fileIsOwner, new Set(['id', 'owner_id', 'created_at']), _store, _workgroupId);
      } else {
        const lockedKeys = displayPath.endsWith('workgroup.json')
          ? new Set(['id', 'owner_id', 'created_at'])
          : null;
        renderJsonForm(form, parsed.data, !fileIsOwner, lockedKeys);
      }

      if (rawBtn) { rawBtn.classList.remove('hidden'); rawBtn.textContent = 'Raw'; }
      setViewMode('form');
      updateEditButton(fileIsOwner, true, true);
    } else {
      form.innerHTML = '';
      form.classList.add('hidden');
      rendered.innerHTML = '';
      rendered.classList.add('hidden');
      pre.classList.remove('hidden');
      if (rawBtn) rawBtn.classList.add('hidden');
      _viewMode = 'raw';
      _parsedJson = null;
      if (editBtnEl) {
        editBtnEl.textContent = 'Edit';
        editBtnEl.classList.toggle('hidden', !fileIsOwner);
      }
    }
  } else if (isMarkdownFile(displayPath)) {
    form.innerHTML = '';
    form.classList.add('hidden');
    _parsedJson = null;
    _viewMode = 'raw';
    _showRaw = false;
    pre.classList.add('hidden');
    rendered.innerHTML = renderMarkdown(file.content);
    rendered.classList.remove('hidden');
    if (rawBtn) { rawBtn.textContent = 'Raw'; rawBtn.classList.remove('hidden'); }
    if (editBtnEl) {
      editBtnEl.textContent = 'Edit';
      editBtnEl.classList.toggle('hidden', !fileIsOwner);
    }
  } else if (isImageFile(displayPath) || isDataUrl(file.content)) {
    form.innerHTML = '';
    form.classList.add('hidden');
    _parsedJson = null;
    _viewMode = 'raw';
    pre.classList.add('hidden');
    rendered.innerHTML = `<img src="${escapeHtml(file.content)}" alt="${escapeHtml(displayPath)}" class="file-panel-image" />`;
    rendered.classList.remove('hidden');
    if (rawBtn) rawBtn.classList.add('hidden');
    if (editBtnEl) editBtnEl.classList.add('hidden');
  } else {
    form.innerHTML = '';
    form.classList.add('hidden');
    _parsedJson = null;
    _viewMode = 'raw';
    pre.classList.remove('hidden');
    rendered.innerHTML = '';
    rendered.classList.add('hidden');
    if (rawBtn) rawBtn.classList.add('hidden');
    if (editBtnEl) {
      editBtnEl.textContent = 'Edit';
      editBtnEl.classList.toggle('hidden', !fileIsOwner);
    }
  }

  if (delBtn) delBtn.classList.toggle('hidden', !fileIsOwner);

  if (viewer) viewer.classList.remove('hidden');
  if (divider) divider.classList.remove('hidden');
}

function hide() {
  _file = null;
  _workgroupId = '';
  _editing = false;
  _parsedJson = null;

  const viewer = viewerEl();
  const divider = dividerEl();
  const pre = contentEl();
  const rendered = renderedEl();
  const form = formEl();

  if (pre) { pre.textContent = ''; pre.classList.add('hidden'); }
  if (rendered) { rendered.innerHTML = ''; rendered.classList.add('hidden'); }
  if (form) { form.innerHTML = ''; form.classList.add('hidden'); }

  const rawBtn = rawToggleBtn();
  const editBtnEl = editBtn();
  const delBtn = deleteBtn();
  if (rawBtn) rawBtn.classList.add('hidden');
  if (editBtnEl) editBtnEl.classList.add('hidden');
  if (delBtn) delBtn.classList.add('hidden');

  if (viewer) viewer.classList.add('hidden');
  if (divider) divider.classList.add('hidden');
}

// ---- Init ----

export function initFileViewer(store) {
  _store = store;

  // Wire up action buttons
  const rawBtn = rawToggleBtn();
  if (rawBtn) {
    rawBtn.addEventListener('click', () => {
      if (!_file) return;
      const displayPath = _file._originalPath || _file.path;

      if (isMarkdownFile(displayPath)) {
        _showRaw = !_showRaw;
        const pre = contentEl();
        const rendered = renderedEl();
        if (_showRaw) {
          if (rendered) rendered.classList.add('hidden');
          if (pre) { pre.textContent = _file.content; pre.classList.remove('hidden'); }
          rawBtn.textContent = 'Rendered';
        } else {
          if (pre) pre.classList.add('hidden');
          if (rendered) { rendered.innerHTML = renderMarkdown(_file.content); rendered.classList.remove('hidden'); }
          rawBtn.textContent = 'Raw';
        }
      } else if (isJsonFile(displayPath)) {
        setViewMode(_viewMode === 'form' ? 'raw' : 'form');
        updateEditButton(isOwner(), _viewMode === 'form', _parsedJson !== null);
      }
    });
  }

  const editBtnEl = editBtn();
  if (editBtnEl) {
    editBtnEl.addEventListener('click', async () => {
      if (!_file) return;

      if (editBtnEl.textContent === 'Save') {
        await saveEdit();
      } else {
        // Enter edit mode
        if (_viewMode === 'form' && _parsedJson !== null) {
          // Form is already editable (readonly=false render on owner). Just update button.
          editBtnEl.textContent = 'Save';
        } else {
          enterEditMode();
        }
      }
    });
  }

  const delBtn = deleteBtn();
  if (delBtn) {
    delBtn.addEventListener('click', doDelete);
  }

  // Bus events
  bus.on('file:selected', ({ file, workgroupId }) => {
    displayFile(file, workgroupId);
  });

  bus.on('file:deselected', () => {
    hide();
  });
}
