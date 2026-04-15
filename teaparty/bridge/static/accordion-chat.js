// accordion-chat.js — the single chat UX implementation for TeaParty.
//
// There is one chat UX in TeaParty. Every page that shows a chat mounts this
// module. Pages carry zero chat DOM, state, or event handlers of their own.
//
// Usage:
//   var chat = AccordionChat.mount(bladeEl, { convId, title });
//   chat.seed('message text');         // open blade and post a message
//   chat.configure({ convId, title }); // switch to a different conversation
//   chat.toggle();                     // open/close the blade
//   chat.destroy();                    // clean up WS, remove globals

(function(global) {

  // ── Session ID derivation ─────────────────────────────────────────────────
  //
  // The dispatch tree endpoint requires the agent's session_id, which is derived
  // from the conversation ID using the same logic as AgentSession._session_key():
  //
  //   safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
  //   session_key = agent_name + '-' + safe_id   (or just agent_name when qualifier is empty)
  //
  // For 'om' (no qualifier — singleton office manager):
  //   → 'office-manager'
  //
  // For lead:{leadName}:{rest}:
  //   agent_name = leadName, qualifier = '{leadName}:{rest}'
  //   → '{leadName}-{leadName}-{rest}'
  //
  function deriveSessionId(convId) {
    if (!convId) return null;
    if (convId === 'om') {
      return 'office-manager';
    }
    if (convId.startsWith('job:')) {
      // job:{project}:{session_id} — session_id is the dispatch tree root
      var jobParts = convId.split(':');
      return jobParts.length >= 3 ? jobParts[2] : null;
    }
    if (convId.startsWith('lead:')) {
      var rest = convId.slice(5);
      var colonIdx = rest.indexOf(':');
      if (colonIdx < 0) return null;
      var leadName = rest.slice(0, colonIdx);
      var leadQualifier = rest.slice(colonIdx + 1);
      // key = f'{leadName}:{leadQualifier}' → safe_key replaces :, /, space with -
      var key = leadName + ':' + leadQualifier;
      var safeKey = key.replace(/[:/\s]/g, '-');
      return leadName + '-' + safeKey;
    }
    return null;
  }

  // ── Filter bar ────────────────────────────────────────────────────────────

  var BLADE_FILTERS = ['agent', 'human', 'thinking', 'tools', 'results', 'system', 'state', 'cost', 'log'];

  // ── mount(bladeEl, config) ────────────────────────────────────────────────
  //
  // Populates bladeEl with the full accordion chat UX and returns an instance.
  // bladeEl must be the .blade element (the CSS flex shell); the module writes
  // its interior (tab, body, header, filters, accordion container).
  //
  // config: { convId, title }

  function mount(bladeEl, initialConfig) {

    // ── Per-instance state ───────────────────────────────────────────────────
    var _config = initialConfig || {};
    var _bladeOpen = localStorage.getItem('bladeOpen') === '1';
    var _accordionExpanded = null;
    var _dispatchTree = null;
    var _bladeActiveFilters = { agent: true, human: true };
    var _ws = null;
    var _wsDestroyed = false;

    // ── Build blade interior ─────────────────────────────────────────────────
    bladeEl.innerHTML =
      '<div class="blade-tab" id="blade-tab"><span id="blade-tab-chevron" ' +
      'style="writing-mode:horizontal-tb;display:inline-block;font-size:14px;line-height:1">' +
      (_bladeOpen ? '&gt;' : '&lt;') + '</span></div>' +
      '<div class="blade-body">' +
      '<div class="blade-header">' +
      '<span class="blade-title" id="blade-title" ' +
      'style="font-size:18px;color:var(--green);text-transform:none;letter-spacing:normal"></span>' +
      '</div>' +
      '<div class="blade-filters" id="blade-filters"></div>' +
      '<div id="dispatch-accordion" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>' +
      '</div>';

    if (_bladeOpen) bladeEl.classList.add('open');

    document.getElementById('blade-tab').addEventListener('click', toggle);

    _renderBladeFilters();
    _applyConfig(_config);
    _connectWS();

    // ── Config ────────────────────────────────────────────────────────────────

    function _applyConfig(cfg) {
      _config = cfg || {};
      _accordionExpanded = null;
      _dispatchTree = null;
      var titleEl = document.getElementById('blade-title');
      if (titleEl) titleEl.textContent = _config.title || '';
      if (_bladeOpen) _updateAccordion();
    }

    // ── Blade open/close ──────────────────────────────────────────────────────

    function toggle() {
      _bladeOpen = !_bladeOpen;
      localStorage.setItem('bladeOpen', _bladeOpen ? '1' : '0');
      bladeEl.classList.toggle('open', _bladeOpen);
      var chev = document.getElementById('blade-tab-chevron');
      if (chev) chev.innerHTML = _bladeOpen ? '&gt;' : '&lt;';
      if (_bladeOpen) _updateAccordion();
    }

    // ── Seed (open blade and post a message) ──────────────────────────────────

    function seed(message) {
      if (!_config.convId) return;
      if (!_bladeOpen) toggle();
      fetch('/api/conversations/' + encodeURIComponent(_config.convId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: message }),
      });
    }

    // ── Accordion ─────────────────────────────────────────────────────────────

    function _updateAccordion() {
      if (!_bladeOpen) return;
      var sessionId = deriveSessionId(_config.convId);
      if (!sessionId) return;
      fetch('/api/dispatch-tree/' + encodeURIComponent(sessionId) + '?conv=' + encodeURIComponent(_config.convId || ''))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(tree) {
          if (!tree) return;
          _dispatchTree = tree;
          if (!_accordionExpanded) _accordionExpanded = tree.session_id;
          _renderAccordion();
        })
        .catch(function() {});
    }

    function _renderAccordion() {
      var container = document.getElementById('dispatch-accordion');
      if (!container || !_dispatchTree) return;

      var currentSections = container.querySelectorAll('.accord-section');
      var currentIds = [];
      for (var i = 0; i < currentSections.length; i++) {
        currentIds.push(currentSections[i].getAttribute('data-session'));
      }

      var flat = _flattenTree(_dispatchTree);
      var newIds = flat.map(function(n) { return n.session_id; });

      if (JSON.stringify(currentIds) === JSON.stringify(newIds)) {
        flat.forEach(function(node) {
          var section = container.querySelector('[data-session="' + node.session_id + '"]');
          if (section) {
            var badge = section.querySelector('.item-badge');
            if (badge) {
              var statusCls = node.status === 'active' ? 'badge-active' : 'badge-idle';
              badge.className = 'item-badge ' + statusCls;
              badge.textContent = node.status;
            }
          }
        });
        var expandedSection = container.querySelector('.accord-section.expanded');
        var expandedId = expandedSection ? expandedSection.getAttribute('data-session') : null;
        if (expandedId === _accordionExpanded) return;
      }

      var expandedExists = flat.some(function(n) { return n.session_id === _accordionExpanded; });
      if (!expandedExists) {
        _accordionExpanded = _findParent(_dispatchTree, _accordionExpanded) || _dispatchTree.session_id;
      }

      container.innerHTML = _renderNode(_dispatchTree, 0);
      _syncFiltersToIframe();
    }

    function _renderNode(node, depth) {
      var isExpanded = (_accordionExpanded === node.session_id);
      var indent = depth * 16;
      var statusCls = node.status === 'active' ? 'badge-active' : 'badge-idle';
      var agentLabel = node.agent_name.replace(/-/g, ' ');
      agentLabel = agentLabel.charAt(0).toUpperCase() + agentLabel.slice(1);

      var html = '';
      var sectionCls = 'accord-section' + (isExpanded ? ' expanded' : '');
      html += '<div class="' + sectionCls + '" data-session="' + node.session_id + '" style="margin-left:' + indent + 'px">';
      html += '<div class="accord-header' + (isExpanded ? ' expanded' : '') + '" onclick="accordionToggle(\'' + node.session_id + '\')">';
      html += '<span class="accord-label">' + agentLabel + '</span>';
      html += '<span class="item-badge ' + statusCls + '" style="font-size:7px">' + node.status + '</span>';
      html += '</div>';

      if (isExpanded) {
        // At depth 0 the dispatch tree's root node uses dispatch:{session_id} as its
        // conversation_id, not the real convId the human posted to. Override with the
        // configured convId so the iframe shows the actual conversation.
        var iframeConvId;
        if (depth === 0 && _config.convId) {
          iframeConvId = _config.convId;
        } else {
          iframeConvId = node.conversation_id || ('session:' + node.session_id);
        }
        html += '<div class="accord-body">';
        html += '<iframe src="chat.html?conv=' + encodeURIComponent(iframeConvId) + '&minimal=1&_t=' + Date.now() + '" style="width:100%;flex:1;border:none;display:block;min-height:0"></iframe>';
        html += '</div>';
      }
      html += '</div>';

      if (node.children && node.children.length > 0) {
        for (var i = 0; i < node.children.length; i++) {
          html += _renderNode(node.children[i], depth + 1);
        }
      }
      return html;
    }

    function _handleSessionRemoval(sessionId) {
      if (!_dispatchTree) return;
      var flat = _flattenTree(_dispatchTree);
      var idx = -1;
      for (var i = 0; i < flat.length; i++) {
        if (flat[i].session_id === sessionId) { idx = i; break; }
      }
      if (idx >= 0 && _accordionExpanded === sessionId) {
        _accordionExpanded = idx > 0 ? flat[idx - 1].session_id : flat[0].session_id;
      }
      _updateAccordion();
    }

    function _removeFromTree(node, sessionId) {
      if (!node.children) return;
      node.children = node.children.filter(function(c) { return c.session_id !== sessionId; });
      for (var i = 0; i < node.children.length; i++) {
        _removeFromTree(node.children[i], sessionId);
      }
    }

    function _findParent(tree, targetId) {
      if (!tree.children) return null;
      for (var i = 0; i < tree.children.length; i++) {
        if (tree.children[i].session_id === targetId) return tree.session_id;
        var found = _findParent(tree.children[i], targetId);
        if (found) return found;
      }
      return null;
    }

    function _flattenTree(node) {
      var result = [node];
      if (node.children) {
        for (var i = 0; i < node.children.length; i++) {
          result = result.concat(_flattenTree(node.children[i]));
        }
      }
      return result;
    }

    // ── Filter bar ────────────────────────────────────────────────────────────

    function _renderBladeFilters() {
      var html = BLADE_FILTERS.map(function(f) {
        var on = _bladeActiveFilters[f] ? ' on' : '';
        return '<button class="filter-btn filter-' + f + on + '" onclick="toggleBladeFilter(\'' + f + '\')">' + f + '</button>';
      }).join('');
      var el = document.getElementById('blade-filters');
      if (el) el.innerHTML = html;
    }

    function _syncFiltersToIframe() {
      setTimeout(function() {
        var iframe = document.querySelector('.accord-section.expanded iframe');
        if (iframe && iframe.contentWindow) {
          iframe.contentWindow.postMessage({ type: 'setFilters', filters: _bladeActiveFilters }, '*');
        }
      }, 300);
    }

    // ── WebSocket (dispatch events only) ──────────────────────────────────────
    //
    // The accordion connects its own WS to handle dispatch_started /
    // dispatch_completed / session_completed. The page's WS handles page-level
    // events (state_changed, input_requested, escalation_cleared).

    function _connectWS() {
      if (_wsDestroyed) return;
      var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      _ws = new WebSocket(proto + '//' + location.host + '/ws');

      _ws.onmessage = function(e) {
        try {
          var event = JSON.parse(e.data);
          if (event.type === 'dispatch_started') {
            _updateAccordion();
          } else if (event.type === 'dispatch_completed') {
            if (_dispatchTree) {
              if (_accordionExpanded === event.child_session_id) {
                _accordionExpanded = event.parent_session_id || _dispatchTree.session_id;
              }
              _removeFromTree(_dispatchTree, event.child_session_id);
              var flatAfter = _flattenTree(_dispatchTree);
              var stillExists = flatAfter.some(function(n) {
                return n.session_id === _accordionExpanded;
              });
              if (!stillExists) {
                _accordionExpanded = _dispatchTree.session_id;
              }
              var container = document.getElementById('dispatch-accordion');
              if (container) container.innerHTML = _renderNode(_dispatchTree, 0);
              _syncFiltersToIframe();
            }
          } else if (event.type === 'session_completed') {
            _handleSessionRemoval(event.session_id);
          }
        } catch (err) {}
      };

      _ws.onclose = function() {
        if (!_wsDestroyed) setTimeout(_connectWS, 3000);
      };
    }

    // ── Global event handler shims ────────────────────────────────────────────
    //
    // onclick handlers in innerHTML strings require global scope. Expose
    // instance-bound functions as globals. One accordion per page — no collision.

    global.accordionToggle = function(sessionId) {
      _accordionExpanded = sessionId;
      _renderAccordion();
      _syncFiltersToIframe();
    };

    global.toggleBladeFilter = function(f) {
      _bladeActiveFilters[f] = !_bladeActiveFilters[f];
      _renderBladeFilters();
      _syncFiltersToIframe();
    };

    // ── Public instance API ───────────────────────────────────────────────────

    function destroy() {
      _wsDestroyed = true;
      if (_ws) { try { _ws.close(); } catch(e) {} }
      delete global.accordionToggle;
      delete global.toggleBladeFilter;
    }

    return {
      toggle: toggle,
      seed: seed,
      configure: _applyConfig,
      destroy: destroy,
    };
  }

  // ── Public module API ─────────────────────────────────────────────────────

  global.AccordionChat = { mount: mount, deriveSessionId: deriveSessionId };

})(window);
