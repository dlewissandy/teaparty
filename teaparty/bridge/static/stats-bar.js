/**
 * StatsBar — paged ticker stats strip, one parameterized component mounted
 * on every non-excluded page.  Issue #406.
 *
 * Usage:
 *   StatsBar.mount(container, { scope, label, agent_filter?, session_filter?,
 *                               workgroup_filter? });
 *   StatsBar.unmount(container);
 *
 * The component:
 *  1. Inserts a compact horizontal strip into container.
 *  2. Fetches baseline from GET /api/telemetry/stats/{scope}?agent=...&session=...
 *  3. Subscribes to `telemetry_event` messages on window._teapartyWS.
 *  4. Updates stats incrementally — no backend round-trip per event.
 *  5. Shows PAGE_SIZE stats at a time, cycling pages every PAGE_INTERVAL_MS.
 *  6. Clicking the strip navigates to stats.html scoped to the same context.
 *
 * Note on workgroup_filter: workgroup-level telemetry filtering requires
 * knowing which agents belong to a workgroup at query time.  The telemetry
 * store (#405) records events by scope and agent_name but has no workgroup
 * field.  When workgroup_filter is present the bar shows parent-scope stats.
 */

var StatsBar = (function () {
  'use strict';

  var PAGE_SIZE        = 5;
  var PAGE_INTERVAL_MS = 10000;
  var FADE_MS          = 200;

  // Per-container state — key: DOM element, value: state object.
  var _mounted = new WeakMap();

  // Marker referenced by single-codepath enforcement test (AC11).
  var _statsBarState = null; // eslint-disable-line no-unused-vars

  // ── Stat definitions ────────────────────────────────────────────────────────
  // Single source of truth for which stats appear and in what order.
  // Config-independent: same list for every scope.

  var STAT_DEFS = [
    { key: 'turns',        label: 'Turns',          fmt: _fmtInt,      cls: 'green'  },
    { key: 'cost',         label: 'Cost',            fmt: _fmtCost,     cls: 'purple' },
    { key: 'tokens',       label: 'Tokens',          fmt: _fmtTokens,   cls: null     },
    { key: 'proc_ms',      label: 'Proc Time',       fmt: _fmtDuration, cls: null     },
    { key: 'jobs_started', label: 'Jobs Started',    fmt: _fmtInt,      cls: null     },
    { key: 'sess_closed',  label: 'Completed',       fmt: _fmtInt,      cls: 'green'  },
    { key: 'withdrawals',  label: 'Withdrawals',     fmt: _fmtInt,      cls: 'yellow' },
    { key: 'backtracks',   label: 'Backtracks',      fmt: _fmtInt,      cls: 'yellow' },
    { key: 'esc_proxy',    label: 'Esc\u2192Proxy',  fmt: _fmtInt,      cls: null     },
    { key: 'esc_human',    label: 'Esc\u2192Human',  fmt: _fmtInt,      cls: 'red'    },
    { key: 'tool_retries', label: 'Tool Retries',    fmt: _fmtInt,      cls: 'orange' },
    { key: 'errors',       label: 'Errors',          fmt: _fmtInt,      cls: 'red'    },
    { key: 'conv_started', label: 'Conv Started',    fmt: _fmtInt,      cls: null     },
    { key: 'conv_closed',  label: 'Conv Closed',     fmt: _fmtInt,      cls: null     },
  ];

  // ── Formatters ───────────────────────────────────────────────────────────────

  function _fmtInt(n) { return String(n || 0); }

  function _fmtCost(n) {
    n = +(n || 0);
    return n < 0.01 ? '$' + n.toFixed(4) : '$' + n.toFixed(2);
  }

  function _fmtTokens(n) {
    n = n || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000)    return (n / 1000).toFixed(1) + 'K';
    return String(n);
  }

  function _fmtDuration(ms) {
    ms = ms || 0;
    if (ms === 0) return '0s';
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    var m = Math.floor(ms / 60000);
    var s = Math.floor((ms % 60000) / 1000);
    if (ms < 3600000) return m + 'm' + (s > 0 ? s + 's' : '');
    var h = Math.floor(ms / 3600000);
    m = Math.floor((ms % 3600000) / 60000);
    return h + 'h' + (m > 0 ? m + 'm' : '');
  }

  // ── Cells ────────────────────────────────────────────────────────────────────

  function _zeroCells() {
    return {
      turns: 0, cost: 0, tokens: 0, proc_ms: 0,
      jobs_started: 0, sess_closed: 0, withdrawals: 0, backtracks: 0,
      esc_proxy: 0, esc_human: 0, tool_retries: 0, errors: 0,
      conv_started: 0, conv_closed: 0,
    };
  }

  function _parseCells(data) {
    return {
      turns:        parseInt(data.turn_count, 10)            || 0,
      cost:         parseFloat(data.total_cost)              || 0,
      tokens:       parseInt(data.total_tokens, 10)          || 0,
      proc_ms:      parseInt(data.processing_ms, 10)         || 0,
      jobs_started: parseInt(data.jobs_started, 10)          || 0,
      sess_closed:  parseInt(data.sessions_closed, 10)       || 0,
      withdrawals:  parseInt(data.withdrawals, 10)           || 0,
      backtracks:   parseInt(data.backtrack_count, 10)       || 0,
      esc_proxy:    parseInt(data.escalations_proxy, 10)     || 0,
      esc_human:    parseInt(data.escalations_human, 10)     || 0,
      tool_retries: parseInt(data.tool_retries, 10)          || 0,
      errors:       parseInt(data.errors, 10)                || 0,
      conv_started: parseInt(data.conversations_started, 10) || 0,
      conv_closed:  parseInt(data.conversations_closed, 10)  || 0,
    };
  }

  // ── Scope matching ────────────────────────────────────────────────────────────

  function _matchesScope(event, config) {
    if (config.scope !== null && event.scope !== config.scope) return false;
    if (config.agent_filter && event.agent_name !== config.agent_filter) return false;
    if (config.session_filter && event.session_id !== config.session_filter) return false;
    return true;
  }

  // ── Incremental cell update ───────────────────────────────────────────────────

  function _applyEvent(cells, event) {
    var et = event.event_type;
    var data = event.data || {};
    if (et === 'turn_complete') {
      cells.turns  += 1;
      cells.cost    = _round6(cells.cost + (parseFloat(data.cost_usd) || 0));
      cells.tokens += (parseInt(data.input_tokens,      10) || 0)
                    + (parseInt(data.output_tokens,     10) || 0)
                    + (parseInt(data.cache_read_tokens, 10) || 0);
      cells.proc_ms += (parseInt(data.duration_ms, 10) || 0);
    } else if (et === 'job_created') {
      cells.jobs_started += 1;
    } else if (et === 'session_complete' || et === 'session_closed') {
      cells.sess_closed += 1;
    } else if (et === 'session_withdrawn') {
      cells.withdrawals += 1;
    } else if (et === 'phase_backtrack') {
      cells.backtracks += 1;
    } else if (et === 'proxy_answered') {
      cells.esc_proxy += 1;
    } else if (et === 'proxy_escalated_to_human') {
      cells.esc_human += 1;
    } else if (et === 'tool_call_retry') {
      cells.tool_retries += 1;
    } else if (et === 'turn_error') {
      cells.errors += 1;
    } else if (et === 'session_create') {
      cells.conv_started += 1;
    } else if (et === 'close_conversation') {
      cells.conv_closed += 1;
    }
  }

  function _affectedKeys(eventType) {
    if (eventType === 'turn_complete')            return ['turns', 'cost', 'tokens', 'proc_ms'];
    if (eventType === 'job_created')              return ['jobs_started'];
    if (eventType === 'session_complete'
     || eventType === 'session_closed')           return ['sess_closed'];
    if (eventType === 'session_withdrawn')        return ['withdrawals'];
    if (eventType === 'phase_backtrack')          return ['backtracks'];
    if (eventType === 'proxy_answered')           return ['esc_proxy'];
    if (eventType === 'proxy_escalated_to_human') return ['esc_human'];
    if (eventType === 'tool_call_retry')          return ['tool_retries'];
    if (eventType === 'turn_error')               return ['errors'];
    if (eventType === 'session_create')           return ['conv_started'];
    if (eventType === 'close_conversation')       return ['conv_closed'];
    return [];
  }

  function _round6(n) { return Math.round(n * 1000000) / 1000000; }

  // ── Pages ─────────────────────────────────────────────────────────────────────

  function _makePages() {
    var pages = [];
    for (var i = 0; i < STAT_DEFS.length; i += PAGE_SIZE) {
      pages.push(STAT_DEFS.slice(i, i + PAGE_SIZE));
    }
    return pages;
  }

  // ── DOM construction ──────────────────────────────────────────────────────────

  function _buildBar(container, config, state) {
    var bar = document.createElement('div');
    bar.className = 'stats-bar';
    bar.title = 'Click for ' + (config.label || 'stats') + ' detail view';
    bar.onclick = function () { window.location.href = _buildClickUrl(config); };

    var ticker = document.createElement('div');
    ticker.className = 'stats-ticker';
    bar.appendChild(ticker);

    var nav = document.createElement('div');
    nav.className = 'stats-ticker-nav';
    state.pages.forEach(function () {
      var dot = document.createElement('span');
      dot.className = 'stats-ticker-dot';
      nav.appendChild(dot);
    });
    bar.appendChild(nav);

    container.innerHTML = '';
    container.appendChild(bar);
    state.barEl    = bar;
    state.tickerEl = ticker;
    state.navEl    = nav;

    _renderPage(state);
  }

  function _renderPage(state) {
    var page = state.pages[state.page] || [];

    // Update nav dots.
    if (state.navEl) {
      var dots = state.navEl.children;
      for (var i = 0; i < dots.length; i++) {
        dots[i].className = 'stats-ticker-dot' + (i === state.page ? ' active' : '');
      }
    }

    if (!state.tickerEl) return;
    state.tickerEl.innerHTML = '';

    page.forEach(function (def) {
      var cell = document.createElement('div');
      cell.className = 'stats-bar-cell';

      var val = document.createElement('div');
      val.className = 'stats-bar-cell-value'
        + (def.cls ? ' stats-bar-cell-value--' + def.cls : '');
      val.textContent = def.fmt(state.cells[def.key]);

      var lbl = document.createElement('div');
      lbl.className = 'stats-bar-cell-label';
      lbl.textContent = def.label;

      cell.appendChild(val);
      cell.appendChild(lbl);
      state.tickerEl.appendChild(cell);
    });
  }

  function _advancePage(state) {
    if (!state.tickerEl) return;
    var ticker = state.tickerEl;
    ticker.classList.add('fading');
    setTimeout(function () {
      state.page = (state.page + 1) % state.pages.length;
      _renderPage(state);
      ticker.classList.remove('fading');
    }, FADE_MS);
  }

  // ── Navigation URL ────────────────────────────────────────────────────────────

  function _buildClickUrl(config) {
    var params = [];
    if (config.scope !== null && config.scope !== undefined) {
      params.push('scope=' + encodeURIComponent(config.scope));
    }
    if (config.agent_filter) {
      params.push('agent=' + encodeURIComponent(config.agent_filter));
    }
    if (config.session_filter) {
      params.push('session=' + encodeURIComponent(config.session_filter));
    }
    return 'stats.html' + (params.length ? '?' + params.join('&') : '');
  }

  // ── Baseline fetch ────────────────────────────────────────────────────────────

  function _fetchUrl(config) {
    var s = (config.scope !== null && config.scope !== undefined)
      ? config.scope : 'all';
    var params = [];
    if (config.agent_filter) {
      params.push('agent=' + encodeURIComponent(config.agent_filter));
    }
    if (config.session_filter) {
      params.push('session=' + encodeURIComponent(config.session_filter));
    }
    return '/api/telemetry/stats/' + encodeURIComponent(s)
      + (params.length ? '?' + params.join('&') : '');
  }

  // ── WebSocket subscription ────────────────────────────────────────────────────

  function _makeWsListener(state) {
    return function (msgEvent) {
      var event;
      try { event = JSON.parse(msgEvent.data); } catch (e) { return; }
      if (event.type !== 'telemetry_event') return;
      if (!_matchesScope(event, state.config)) return;

      var affected = _affectedKeys(event.event_type);
      if (!affected.length) return;
      _applyEvent(state.cells, event);

      // Re-render current page only if an affected key is visible on it.
      var currentDefs = state.pages[state.page] || [];
      var visible = currentDefs.some(function (def) {
        return affected.indexOf(def.key) !== -1;
      });
      if (visible) _renderPage(state);
    };
  }

  function _subscribeWS(state) {
    var ws = window._teapartyWS;
    if (!ws) return;
    state.wsListener = _makeWsListener(state);
    ws.addEventListener('message', state.wsListener);
  }

  // ── Public API ────────────────────────────────────────────────────────────────

  /**
   * Mount a paged ticker stats bar into container.
   *
   * config: {
   *   scope: string | null,   // null = org-wide
   *   label: string,
   *   agent_filter?: string,
   *   session_filter?: string,
   *   workgroup_filter?: string,  // informational only — see module header
   * }
   */
  function mount(container, config) {
    unmount(container);

    var state = {
      config:    config,
      cells:     _zeroCells(),
      pages:     _makePages(),
      page:      0,
      barEl:     null,
      tickerEl:  null,
      navEl:     null,
      timer:     null,
      wsListener: null,
    };

    _buildBar(container, config, state);

    // Auto-advance pages.
    if (state.pages.length > 1) {
      state.timer = setInterval(function () {
        _advancePage(state);
      }, PAGE_INTERVAL_MS);
    }

    // Fetch baseline; wire WS listener after snapshot is in place.
    fetch(_fetchUrl(config))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        state.cells = _parseCells(data);
        _renderPage(state);
        _subscribeWS(state);
      })
      .catch(function () {
        _subscribeWS(state);
      });

    _mounted.set(container, state);
  }

  /**
   * Unmount the stats bar from container — removes DOM, timer, WS listener.
   */
  function unmount(container) {
    var state = _mounted.get(container);
    if (!state) return;
    if (state.timer) { clearInterval(state.timer); }
    if (window._teapartyWS && state.wsListener) {
      window._teapartyWS.removeEventListener('message', state.wsListener);
    }
    container.innerHTML = '';
    _mounted.delete(container);
  }

  return { mount: mount, unmount: unmount };

}());
