// TeaParty App - Entry Point
// Creates the reactive store, initializes all features, bootstraps auth.

import { createStore } from './core/store.js';
import { initSSE } from './core/sse.js';
import { bus } from './core/bus.js';
import { escapeHtml } from './core/utils.js';
import { api } from './core/api.js';

import { flash } from './components/shared/flash.js';
import { initIdentity } from './components/shared/identity.js';

import {
  initAuth, loadConfig, initGoogleButton, bootstrapSession,
  resolveInitialTheme, applyTheme, setSignedIn, savePreferences,
} from './features/auth/auth.js';
import { initUserMenu } from './features/auth/user-menu.js';

import { initOrgRail } from './features/nav/org-rail.js';
import { initSidebar } from './features/nav/sidebar.js';
import { initQuickSwitcher } from './features/nav/quick-switcher.js';
import { initDirectory } from './features/nav/directory.js';

import { initChatPanel } from './features/chat/chat-panel.js';
import { initAgentProfile } from './features/agents/agent-profile.js';

import { initRightPanel } from './features/files/right-panel.js';

import { initSettings } from './features/settings/settings.js';
import { initNotifications } from './features/notifications/notifications.js';
import { initHome } from './features/home/home.js';
import { initEngagements } from './features/engagements/engagements.js';
import { initPartnerships } from './features/partnerships/partnerships.js';

import {
  initDataLoading, loadWorkgroupTemplates,
  loadMyInvites, loadPartnerships, loadAllPartnerships, startPolling, selectConversation,
} from './features/data/data-loading.js';

// ─── Nav persistence ─────────────────────────────────────────────────────────

const NAV_STORAGE_KEY = 'teaparty_nav';

function loadSavedNav() {
  try {
    return JSON.parse(localStorage.getItem(NAV_STORAGE_KEY)) || {};
  } catch { return {}; }
}

const savedNav = loadSavedNav();

// ─── Store ────────────────────────────────────────────────────────────────────

const store = createStore({
  auth: {
    token: sessionStorage.getItem('teaparty_token') || localStorage.getItem('teaparty_token') || '',
    user: null,
    config: null,
  },
  nav: {
    activeOrgId: savedNav.activeOrgId || '',
    activeWorkgroupId: savedNav.activeWorkgroupId || '',
    activeConversationId: savedNav.activeConversationId || '',
    sidebarSelection: savedNav.sidebarSelection || '',
    drawerOpen: false,
  },
  conversation: {
    messages: [],
    usage: null,
    teamRoster: [],
    thinkingByConversation: {},
    thoughtsByMessageId: {},
  },
  data: {
    organizations: [],
    workgroups: [],
    treeData: {},
    homeSummary: null,
    templates: [],
    invites: [],
    partnerships: [],
  },
  panels: {
    rightPanelOpen: false,
    rightPanelTab: 'files',
    quickSwitcherOpen: false,
  },
  ui: {
    settingsOpen: false,
    mobilePanel: 'chat',
  },
});

// Persist nav state to localStorage on changes
function persistNav() {
  const n = store.get().nav;
  localStorage.setItem(NAV_STORAGE_KEY, JSON.stringify({
    activeOrgId: n.activeOrgId,
    activeWorkgroupId: n.activeWorkgroupId,
    activeConversationId: n.activeConversationId,
    sidebarSelection: n.sidebarSelection,
  }));
}
store.on('nav.activeOrgId', persistNav);
store.on('nav.activeWorkgroupId', persistNav);
store.on('nav.activeConversationId', persistNav);
store.on('nav.sidebarSelection', persistNav);

// ─── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  // Theme first (prevents flash of wrong colors)
  applyTheme(resolveInitialTheme(), false);

  // Configure marked.js renderer
  if (typeof window.marked !== 'undefined') {
    const renderer = new window.marked.Renderer();
    renderer.link = function ({ href, title, text }) {
      const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
      return `<a href="${escapeHtml(href)}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    };
    window.marked.setOptions({ renderer });
  }

  // Initialize shared services
  initIdentity(store);
  initSSE(store);

  // Initialize features
  initAuth(store);
  initUserMenu(store);
  initOrgRail(store);
  initSidebar(store);
  initQuickSwitcher(store);
  initDirectory(store);
  initChatPanel(store);
  initAgentProfile(store);
  initRightPanel(store);
  initSettings(store);
  initNotifications(store);
  initHome(store);
  initEngagements(store);
  initPartnerships(store);
  initDataLoading(store);

  // Wire up sidebar dev login form
  const sidebarDevForm = document.getElementById('sidebar-dev-login');
  if (sidebarDevForm) {
    sidebarDevForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('sidebar-dev-email').value.trim();
      const name = document.getElementById('sidebar-dev-name').value.trim();
      if (!email) return;
      try {
        const data = await api('/api/auth/dev-login', {
          method: 'POST',
          body: { email, name },
        });
        await setSignedIn(data.user, data.access_token);
        flash('Signed in', 'success');
      } catch (err) {
        flash(err.message || 'Login failed', 'error');
      }
    });
  }

  // Wire up nav conversation selection
  bus.on('nav:conversation-selected', async ({ workgroupId, conversationId }) => {
    await selectConversation(workgroupId, conversationId);
  });

  // Wire up workgroup selection — navigate to first job conversation
  bus.on('nav:workgroup-selected', async ({ workgroupId }) => {
    const s = store.get();
    const tree = s.data.treeData[workgroupId];
    if (!tree) return;
    const jobs = tree.jobs || [];
    if (jobs.length) {
      await selectConversation(workgroupId, jobs[0].id);
    }
  });

  // Wire up right panel toggles from chat header
  const btnFiles = document.getElementById('btn-toggle-files');
  const btnInfo = document.getElementById('btn-toggle-info');
  if (btnFiles) {
    btnFiles.addEventListener('click', () => bus.emit('panel:toggle-files'));
  }
  if (btnInfo) {
    btnInfo.addEventListener('click', () => bus.emit('panel:toggle-info'));
  }

  // Mobile nav
  document.querySelectorAll('.mobile-nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = btn.dataset.panel;
      store.update(s => { s.ui.mobilePanel = panel; });
      document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.toggle('active', b === btn));

      if (panel === 'sidebar') {
        store.update(s => { s.nav.drawerOpen = true; });
        document.getElementById('sidebar')?.classList.add('drawer-open');
        document.getElementById('drawer-backdrop')?.classList.remove('hidden');
      } else if (panel === 'files') {
        bus.emit('panel:toggle-files');
      } else if (panel === 'notifications') {
        document.getElementById('org-rail-bell')?.click();
      }
    });
  });

  // Drawer backdrop close
  document.getElementById('drawer-backdrop')?.addEventListener('click', () => {
    store.update(s => { s.nav.drawerOpen = false; });
    document.getElementById('sidebar')?.classList.remove('drawer-open');
    document.getElementById('drawer-backdrop')?.classList.add('hidden');
  });

  // Auto-select org on initial load (restore last or pick first).
  // Don't auto-select if user intentionally navigated to home.
  // If we restored nav state from localStorage, skip auto-selection.
  let _hasAutoSelected = !!store.get().nav.activeOrgId;
  store.on('data.organizations', () => {
    const s = store.get();
    if (s.nav.activeOrgId) return; // already selected
    if (_hasAutoSelected) return; // user went home; don't override
    const orgs = s.data.organizations || [];
    if (!orgs.length) return;

    _hasAutoSelected = true;
    const savedOrgId = s.auth.user?.preferences?.lastOrgId;
    const target = (savedOrgId && orgs.find(o => o.id === savedOrgId)) ? savedOrgId : orgs[0].id;
    store.update(s => { s.nav.activeOrgId = target; });
    store.notify('nav.activeOrgId');
    bus.emit('nav:org-selected', { orgId: target });
  });

  // Persist selected org to preferences and load partnerships
  store.on('nav.activeOrgId', () => {
    const s = store.get();
    if (s.auth.user && s.auth.token) {
      if (s.nav.activeOrgId) {
        savePreferences({ lastOrgId: s.nav.activeOrgId });
        loadPartnerships(s.nav.activeOrgId);
      } else {
        // Home view: load partnerships across all orgs
        loadAllPartnerships();
      }
    }
  });

  // Bootstrap
  await loadConfig();
  initGoogleButton();
  await bootstrapSession();

  // If authenticated, start data loading
  if (store.get().auth.token) {
    await loadWorkgroupTemplates();
    await loadMyInvites();
    startPolling();

    // If nav state was restored from localStorage, kick off data for the active org/conversation
    const restoredNav = store.get().nav;
    if (restoredNav.activeOrgId) {
      loadPartnerships(restoredNav.activeOrgId);
    }
    if (restoredNav.activeConversationId && restoredNav.activeWorkgroupId) {
      await selectConversation(restoredNav.activeWorkgroupId, restoredNav.activeConversationId);
    }
  }
}

init().catch(error => {
  flash(error.message, 'error');
  console.error('Init error:', error);
});
