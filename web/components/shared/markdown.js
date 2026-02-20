// Markdown rendering helper using marked + DOMPurify.

import { escapeHtml } from '../../core/utils.js';

export function renderMarkdown(raw) {
  if (typeof window.marked !== 'undefined' && typeof window.DOMPurify !== 'undefined') {
    return window.DOMPurify.sanitize(window.marked.parse(raw));
  }
  return `<pre>${escapeHtml(raw)}</pre>`;
}
