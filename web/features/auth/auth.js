// Authentication: login, logout, session bootstrap.
// Ported from modules/auth.js to use the reactive store.

import { api, initApi } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { THEME_STORAGE_KEY } from '../../core/constants.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

export function initAuth(store) {
  _store = store;
  initApi(store, () => {
    signOut();
    flash('Session expired. Sign in again.', 'info');
  });
}

export function updateAuthUI() {
  const s = _store.get();
  const online = Boolean(s.auth.user && s.auth.token);

  // Sidebar: toggle auth gate vs content
  const sidebarAuthGate = document.getElementById('sidebar-auth-gate');
  const sidebarContent = document.getElementById('sidebar-content');
  if (sidebarAuthGate) sidebarAuthGate.classList.toggle('hidden', online);
  if (sidebarContent) sidebarContent.classList.toggle('hidden', !online);

  // Org rail: hide bottom buttons when signed out
  const railBottom = document.querySelector('.org-rail-bottom');
  if (railBottom) railBottom.classList.toggle('hidden', !online);
  const railOrgs = document.getElementById('org-rail-orgs');
  if (railOrgs) railOrgs.classList.toggle('hidden', !online);

  // Main content: hide everything when signed out
  const chatView = document.getElementById('chat-view');
  const homeView = document.getElementById('home-view');
  const authGate = document.getElementById('auth-gate');

  if (!online) {
    if (chatView) chatView.classList.add('hidden');
    if (homeView) homeView.classList.add('hidden');
    if (authGate) authGate.classList.add('hidden');
  } else {
    if (authGate) authGate.classList.add('hidden');
    const dashboard = document.getElementById('home-dashboard');
    if (dashboard) dashboard.classList.toggle('hidden', !online);
    if (!s.nav.activeConversationId) {
      if (chatView) chatView.classList.add('hidden');
      if (homeView) homeView.classList.remove('hidden');
    }
  }

  // User avatar in org rail
  const avatarEl = document.getElementById('org-rail-user-avatar');
  if (avatarEl && online && s.auth.user) {
    const name = s.auth.user.name || s.auth.user.email || 'U';
    const initial = name[0]?.toUpperCase() || '?';
    if (s.auth.user.picture) {
      avatarEl.innerHTML = `<img src="${s.auth.user.picture}" alt="" />`;
    } else {
      avatarEl.textContent = initial;
    }
  } else if (avatarEl) {
    avatarEl.textContent = '?';
  }

  // Dev login form visibility
  const sidebarDevForm = document.getElementById('sidebar-dev-login');
  if (sidebarDevForm && s.auth.config && !s.auth.config.allow_dev_auth) {
    sidebarDevForm.classList.add('hidden');
  }

  bus.emit('auth:changed', { online });
}

export async function loginWithGoogleCredential(credential) {
  const auth = await api('/api/auth/google', {
    method: 'POST',
    body: { id_token: credential },
  });
  await setSignedIn(auth.user, auth.access_token);
  flash('Signed in with Google', 'success');
}

export async function setSignedIn(user, token) {
  _store.update(s => {
    s.auth.user = user;
    s.auth.token = token;
  });

  sessionStorage.setItem('teaparty_token', token);
  localStorage.setItem('teaparty_token', token);

  // Apply server-side preferences
  const prefs = user.preferences || {};
  if (prefs.theme) {
    applyThemeFromPrefs(prefs.theme);
  }
  if (prefs.showAgentThoughts) {
    const el = document.getElementById('thoughts-toggle');
    if (el) el.checked = true;
  }

  updateAuthUI();
  bus.emit('auth:signed-in', { user, token });
}

function applyThemeFromPrefs(theme) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  document.body.setAttribute('data-theme', normalized);
  localStorage.setItem(THEME_STORAGE_KEY, normalized);
  const toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.checked = normalized === 'dark';
}

export function signOut() {
  _store.update(s => {
    s.auth.user = null;
    s.auth.token = '';
    s.nav.activeOrgId = '';
    s.nav.activeWorkgroupId = '';
    s.nav.activeConversationId = '';
    s.data.organizations = [];
    s.data.workgroups = [];
    s.data.treeData = {};
    s.data.templates = [];
    s.data.invites = [];
    s.data.homeSummary = null;
    s.conversation.messages = [];
    s.conversation.usage = null;
    s.conversation.teamRoster = [];
    s.conversation.thinkingByConversation = {};
    s.conversation.thoughtsByMessageId = {};
    s.panels.rightPanelOpen = false;
  });

  sessionStorage.removeItem('teaparty_token');
  localStorage.removeItem('teaparty_token');

  updateAuthUI();
  bus.emit('auth:signed-out');
}

export async function bootstrapSession() {
  const token = _store.get().auth.token;
  if (!token) {
    updateAuthUI();
    return;
  }

  try {
    const user = await api('/api/auth/me');
    await setSignedIn(user, token);
  } catch {
    signOut();
  }
}

export async function loadConfig() {
  const config = await api('/api/config');
  _store.update(s => { s.auth.config = config; });
  updateAuthUI();
}

export function initGoogleButton() {
  const config = _store.get().auth.config;
  if (!config?.google_client_id) {
    const el = document.getElementById('google-login');
    if (el) el.innerHTML = "<p class='meta'>Google login disabled.</p>";
    return;
  }

  const tryInit = () => {
    if (!(window.google?.accounts?.id)) {
      setTimeout(tryInit, 200);
      return;
    }
    window.google.accounts.id.initialize({
      client_id: config.google_client_id,
      callback: (response) =>
        loginWithGoogleCredential(response.credential).catch(e => flash(e.message, 'error')),
    });
    const el = document.getElementById('google-login');
    if (el) {
      window.google.accounts.id.renderButton(el, {
        theme: 'outline', size: 'large', shape: 'pill', text: 'signin_with',
      });
    }
  };
  tryInit();
}

// Theme management
export function resolveInitialTheme() {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === 'dark' || stored === 'light') return stored;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(theme, persist = true) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  document.body.setAttribute('data-theme', normalized);
  const toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.checked = normalized === 'dark';
  if (persist) {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
    savePreferences({ theme: normalized });
  }
}

export function toggleTheme() {
  const current = document.body.getAttribute('data-theme');
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

let _savePrefsTimer = null;
export function savePreferences(patch) {
  const s = _store.get();
  if (!s.auth.user || !s.auth.token) return;
  _store.update(st => {
    st.auth.user.preferences = { ...(st.auth.user.preferences || {}), ...patch };
  });
  clearTimeout(_savePrefsTimer);
  _savePrefsTimer = setTimeout(async () => {
    try {
      const updated = await api('/api/auth/me/preferences', {
        method: 'PATCH',
        body: { preferences: patch },
      });
      _store.update(st => { st.auth.user = updated; });
    } catch (e) {
      console.error('Failed to save preferences', e);
    }
  }, 400);
}

export function isShowAgentThoughts() {
  return Boolean(_store.get().auth.user?.preferences?.showAgentThoughts);
}
