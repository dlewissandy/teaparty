// Right panel tabbed container.
// Manages show/hide and tab switching for the Files / Info panel.

import { bus } from '../../core/bus.js';

export function initRightPanel(store) {
  const panel = document.getElementById('right-panel');
  const app = document.getElementById('app');
  const closeBtn = document.getElementById('right-panel-close');
  if (!panel || !app) return;
  const tabBtns = panel.querySelectorAll('.right-panel-tab');
  const tabContents = panel.querySelectorAll('.right-panel-content');

  // --- helpers ---

  function openPanel() {
    store.update(s => { s.panels.rightPanelOpen = true; });
  }

  function closePanel() {
    store.update(s => { s.panels.rightPanelOpen = false; });
  }

  function setTab(tab) {
    store.update(s => { s.panels.rightPanelTab = tab; });
  }

  // --- render ---

  function render(s) {
    const { rightPanelOpen, rightPanelTab } = s.panels;
    const width = rightPanelOpen ? '360px' : '0px';
    app.style.setProperty('--right-panel-width', width);

    // Tab buttons
    tabBtns.forEach(btn => {
      const active = btn.dataset.tab === rightPanelTab;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });

    // Tab content panels
    tabContents.forEach(el => {
      el.classList.toggle('hidden', el.dataset.tab !== rightPanelTab);
    });
  }

  // --- wire up ---

  closeBtn?.addEventListener('click', closePanel);

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => setTab(btn.dataset.tab));
  });

  // Bus events from chat header buttons
  bus.on('panel:toggle-files', () => {
    const s = store.get();
    if (s.panels.rightPanelOpen && s.panels.rightPanelTab === 'files') {
      closePanel();
    } else {
      setTab('files');
      openPanel();
    }
  });

  bus.on('panel:toggle-info', () => {
    const s = store.get();
    if (s.panels.rightPanelOpen && s.panels.rightPanelTab === 'info') {
      closePanel();
    } else {
      setTab('info');
      openPanel();
    }
  });

  store.on('panels', render);
  render(store.get());
}
