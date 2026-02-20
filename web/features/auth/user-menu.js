// User menu dropdown component (attached to org rail user button).

import { escapeHtml } from '../../core/utils.js';
import { signOut, applyTheme, savePreferences } from './auth.js';

let _store = null;

export function initUserMenu(store) {
  _store = store;

  const btn = document.getElementById('org-rail-user');
  const menu = document.getElementById('user-menu');
  if (!btn || !menu) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isHidden = menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !isHidden);
    btn.setAttribute('aria-expanded', String(isHidden));
  });

  // Close on outside click
  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target) && e.target !== btn) {
      menu.classList.add('hidden');
      btn.setAttribute('aria-expanded', 'false');
    }
  });

  // Theme toggle
  const themeToggle = document.getElementById('theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('change', () => {
      applyTheme(themeToggle.checked ? 'dark' : 'light');
    });
  }

  // Thoughts toggle
  const thoughtsToggle = document.getElementById('thoughts-toggle');
  if (thoughtsToggle) {
    thoughtsToggle.addEventListener('change', () => {
      savePreferences({ showAgentThoughts: thoughtsToggle.checked });
    });
  }

  // Logout button
  const logoutBtn = document.getElementById('logout-button');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      menu.classList.add('hidden');
      signOut();
    });
  }

  // Update menu content when auth changes
  _store.on('auth.user', () => updateMenuContent());
}

function updateMenuContent() {
  const s = _store.get();
  const nameEl = document.getElementById('user-menu-name');
  const emailEl = document.getElementById('user-menu-email');
  if (nameEl) nameEl.textContent = s.auth.user?.name || '';
  if (emailEl) emailEl.textContent = s.auth.user?.email || '';
}

export function closeUserMenu() {
  const menu = document.getElementById('user-menu');
  const btn = document.getElementById('org-rail-user');
  if (menu) menu.classList.add('hidden');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}
