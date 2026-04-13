/**
 * StatsBar — one parameterized stats-bar component, mounted on every
 * non-excluded page with a scope config.  Issue #406.
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
 *  4. Updates cells incrementally — no backend round-trip per event.
 *  5. Clicking the strip navigates to /stats.html?scope=...&agent=...&session=...
 *
 * Note on workgroup_filter: workgroup-level telemetry filtering requires knowing
 * which agents belong to a workgroup at query time.  The telemetry store (#405)
 * records events by scope and agent_name but has no workgroup field.  When
 * workgroup_filter is present, the bar shows stats for the parent scope
 * (filtered by scope only), not for the specific workgroup.  Workgroup-level
 * drill-down is a backend enhancement outside the scope of #406.
 */

var StatsBar = (function () {
  'use strict';

  // Per-container state.  Key: container element, value: _statsBarState object.
  var _mounted = new WeakMap();

  // ── Internal state type ──────────────────────────────────────────────────
  // { config, cells, wsListener }
  // cells: { cost, turns, active, gates, backtracks, escalations, proxyPct }
  var _statsBarState = null; // eslint-disable-line no-unused-vars — referenced by test CI check

  // ── Scope matching ────────────────────────────────────────────────────────

  function _matchesScope(event, config) {
    // scope: null means org-wide (all events match)
    if (config.scope !== null && event.scope !== config.scope) return false;
    if (config.agent_filter && event.agent_name !== config.agent_filter) return false;
    if (config.session_filter && event.session_id !== config.session_filter) return false;
    return true;
  }

  // ── Cell incremental update ───────────────────────────────────────────────

  function _applyEvent(cells, event) {
    var et = event.event_type;
    var data = event.data || {};
    if (et === 'turn_complete') {
      cells.cost = round6(cells.cost + (parseFloat(data.cost_usd) || 0));
      cells.turns += 1;
    } else if (et === 'session_create') {
      cells.active += 1;
    } else if (
      et === 'session_complete' || et === 'session_closed' ||
      et === 'session_withdrawn' || et === 'session_timed_out' ||
      et === 'session_abandoned'
    ) {
      cells.active = Math.max(0, cells.active - 1);
    } else if (et === 'gate_input_requested') {
      cells.gates += 1;
    } else if (et === 'gate_input_received') {
      cells.gates = Math.max(0, cells.gates - 1);
    } else if (et === 'phase_backtrack') {
      cells.backtracks += 1;
    } else if (et === 'escalation_requested') {
      cells.escalations += 1;
    } else if (et === 'escalation_resolved') {
      var src = data.final_answer_source;
      cells.proxyResolved += 1;
      if (src === 'proxy') cells.proxyAnswered += 1;
      cells.proxyPct = cells.proxyResolved > 0
        ? Math.round(100 * cells.proxyAnswered / cells.proxyResolved)
        : null;
    }
  }

  function round6(n) {
    return Math.round(n * 1000000) / 1000000;
  }

  // ── DOM construction ──────────────────────────────────────────────────────

  function _buildDOM(container, config, cells) {
    var clickUrl = _buildClickUrl(config);

    var bar = document.createElement('div');
    bar.className = 'stats-bar';
    bar.title = 'Click to view ' + (config.label || 'stats') + ' details';
    bar.onclick = function () { window.location.href = clickUrl; };

    var lbl = document.createElement('span');
    lbl.className = 'stats-bar-label';
    lbl.textContent = config.label || 'Stats';
    bar.appendChild(lbl);

    var cellDefs = _cellDefs(cells);
    cellDefs.forEach(function (def) {
      var cell = document.createElement('div');
      cell.className = 'stats-bar-cell' + (def.optional ? ' optional' : '');
      cell.dataset.metric = def.metric;
      if (def.optional && !def.show) cell.style.display = 'none';

      var val = document.createElement('div');
      val.className = 'stats-bar-cell-value' + (def.colorClass ? ' ' + def.colorClass : '');
      val.textContent = def.value;

      var lbl2 = document.createElement('div');
      lbl2.className = 'stats-bar-cell-label';
      lbl2.textContent = def.label;

      cell.appendChild(val);
      cell.appendChild(lbl2);
      bar.appendChild(cell);
    });

    container.innerHTML = '';
    container.appendChild(bar);
  }

  function _cellDefs(cells) {
    return [
      {
        metric: 'cost', label: 'Cost', optional: false,
        value: '$' + cells.cost.toFixed(2),
        colorClass: 'stats-bar-cell-value--purple',
      },
      {
        metric: 'turns', label: 'Turns', optional: false,
        value: String(cells.turns),
        colorClass: 'stats-bar-cell-value--green',
      },
      {
        metric: 'active', label: 'Active', optional: false,
        value: String(cells.active),
        colorClass: cells.active > 0 ? 'stats-bar-cell-value--green' : '',
      },
      {
        metric: 'gates', label: 'Gates Waiting', optional: false,
        value: String(cells.gates),
        colorClass: cells.gates > 0 ? 'stats-bar-cell-value--yellow' : '',
      },
      {
        metric: 'backtracks', label: 'Backtracks', optional: true,
        show: cells.backtracks > 0,
        value: String(cells.backtracks),
        colorClass: 'stats-bar-cell-value--yellow',
      },
      {
        metric: 'escalations', label: 'Escalations', optional: true,
        show: cells.escalations > 0,
        value: String(cells.escalations),
        colorClass: 'stats-bar-cell-value--red',
      },
      {
        metric: 'proxyPct', label: 'Proxy Ans %', optional: true,
        show: cells.proxyPct !== null,
        value: cells.proxyPct !== null ? cells.proxyPct + '%' : '—',
        colorClass: '',
      },
    ];
  }

  function _updateCell(container, metric, cells) {
    var cell = container.querySelector('[data-metric="' + metric + '"]');
    if (!cell) return;
    var defs = _cellDefs(cells);
    var def = null;
    for (var i = 0; i < defs.length; i++) {
      if (defs[i].metric === metric) { def = defs[i]; break; }
    }
    if (!def) return;

    var valEl = cell.querySelector('.stats-bar-cell-value');
    if (valEl) {
      valEl.textContent = def.value;
      valEl.className = 'stats-bar-cell-value' + (def.colorClass ? ' ' + def.colorClass : '');
    }
    if (def.optional) {
      cell.style.display = def.show ? '' : 'none';
    }
  }

  // ── Click-through URL ─────────────────────────────────────────────────────

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

  // ── Baseline fetch ────────────────────────────────────────────────────────

  function _fetchUrl(config) {
    var s = (config.scope !== null && config.scope !== undefined)
      ? config.scope : 'all';
    var params = [];
    if (config.agent_filter) params.push('agent=' + encodeURIComponent(config.agent_filter));
    if (config.session_filter) params.push('session=' + encodeURIComponent(config.session_filter));
    var qs = params.length ? '?' + params.join('&') : '';
    return '/api/telemetry/stats/' + encodeURIComponent(s) + qs;
  }

  function _parseCells(data) {
    var par = data.proxy_answer_rate || {};
    var proxyResolved = (par.total || 0);
    var proxyAnswered = (par.by_proxy || 0);
    return {
      cost:           parseFloat(data.total_cost) || 0,
      turns:          parseInt(data.turn_count, 10) || 0,
      active:         (data.active_sessions || []).length !== undefined
                        ? (Array.isArray(data.active_sessions) ? data.active_sessions.length
                           : (parseInt(data.active_sessions, 10) || 0))
                        : 0,
      gates:          (data.gates_awaiting_input || []).length !== undefined
                        ? (Array.isArray(data.gates_awaiting_input)
                           ? data.gates_awaiting_input.length
                           : (parseInt(data.gates_awaiting_input, 10) || 0))
                        : 0,
      backtracks:     parseInt(data.backtrack_count, 10) || 0,
      escalations:    parseInt(data.escalation_count, 10) || 0,
      proxyResolved:  proxyResolved,
      proxyAnswered:  proxyAnswered,
      proxyPct:       proxyResolved > 0
                        ? Math.round(100 * proxyAnswered / proxyResolved)
                        : null,
    };
  }

  // ── WebSocket subscription ────────────────────────────────────────────────

  function _makeWsListener(state, container) {
    return function (msgEvent) {
      var event;
      try { event = JSON.parse(msgEvent.data); } catch (e) { return; }
      if (event.type !== 'telemetry_event') return;
      if (!_matchesScope(event, state.config)) return;

      var affected = _affectedMetrics(event.event_type);
      _applyEvent(state.cells, event);
      affected.forEach(function (m) { _updateCell(container, m, state.cells); });
    };
  }

  function _affectedMetrics(eventType) {
    if (eventType === 'turn_complete') return ['cost', 'turns'];
    if (eventType === 'session_create') return ['active'];
    if (
      eventType === 'session_complete' || eventType === 'session_closed' ||
      eventType === 'session_withdrawn' || eventType === 'session_timed_out' ||
      eventType === 'session_abandoned'
    ) return ['active'];
    if (eventType === 'gate_input_requested') return ['gates'];
    if (eventType === 'gate_input_received') return ['gates'];
    if (eventType === 'phase_backtrack') return ['backtracks'];
    if (eventType === 'escalation_requested') return ['escalations'];
    if (eventType === 'escalation_resolved') return ['proxyPct'];
    return [];
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Mount the stats bar into container.
   *
   * config: {
   *   scope: string | null,   // null = org-wide
   *   label: string,
   *   agent_filter?: string,
   *   session_filter?: string,
   * }
   */
  function mount(container, config) {
    // Unmount any existing bar in this container first.
    unmount(container);

    var state = {
      config: config,
      cells: { cost: 0, turns: 0, active: 0, gates: 0, backtracks: 0,
               escalations: 0, proxyResolved: 0, proxyAnswered: 0, proxyPct: null },
      wsListener: null,
    };

    // Render placeholder immediately.
    _buildDOM(container, config, state.cells);

    // Fetch baseline.
    fetch(_fetchUrl(config))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        state.cells = _parseCells(data);
        _buildDOM(container, config, state.cells);
        // Wire up WS listener after baseline is in place so deltas are
        // applied to a known-good snapshot.
        _subscribeWS(state, container);
      })
      .catch(function () {
        // Baseline fetch failed; still show the bar with zeros and subscribe
        // so live events start populating it.
        _subscribeWS(state, container);
      });

    _mounted.set(container, state);
  }

  function _subscribeWS(state, container) {
    var ws = window._teapartyWS;
    if (!ws) return;
    state.wsListener = _makeWsListener(state, container);
    ws.addEventListener('message', state.wsListener);
  }

  /**
   * Unmount the stats bar from container, removing DOM and WS subscription.
   */
  function unmount(container) {
    var state = _mounted.get(container);
    if (!state) return;
    var ws = window._teapartyWS;
    if (ws && state.wsListener) {
      ws.removeEventListener('message', state.wsListener);
    }
    container.innerHTML = '';
    _mounted.delete(container);
  }

  return { mount: mount, unmount: unmount };

}());
