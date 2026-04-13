// artifact-page.js — the single artifact page implementation for TeaParty.
//
// There is one artifact page in TeaParty. Both the artifact browser (browse mode)
// and the job screen (job mode) mount this module. Pages carry zero rendering,
// state, or event-handling code of their own.
//
// Usage:
//   ArtifactPage.mount(container, {
//     mode: 'browse' | 'job',
//     projectSlug: 'comics',
//     chatConversationId: 'lead:comics-lead:darrell',
//     chatAgentName:      'comics-lead',
//     chatLaunchRepo:     '/path/to/repo',
//     chatTitle:          'Comics Lead Chat',
//     // Job-mode-only fields (undefined in browse mode):
//     jobId:           'job-20260412-abc123',
//     originalRequest: '"Add a new strip..."',
//     workflowPhase:   'EXEC',
//     workflowState:   'TASK_IN_PROGRESS',
//     needsInput:      false,
//   });

(function(global) {

  // ── Helpers ───────────────────────────────────────────────────────────────────

  function escHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function parseMdLinks(text) {
    var items = [];
    var regex = /\[([^\]]+)\]\(([^)]+)\)/g;
    var m;
    while ((m = regex.exec(text)) !== null) {
      var href = m[2];
      if (!href.startsWith('http') && !href.startsWith('#') && !href.startsWith('mailto:')) {
        items.push({name: m[1], path: href});
      }
    }
    return items;
  }

  function rewriteInternalLinks(html) {
    return html.replace(/href="([^"]+)"/g, function(match, href) {
      if (/^(https?:\/\/|#|mailto:|javascript:)/.test(href)) return match;
      return 'href="javascript:void(0)" onclick="ArtifactPage._loadFile(\'' + href + '\')"';
    });
  }

  function rewriteCodeFileRefs(html) {
    return html.replace(/<code>([a-zA-Z0-9][a-zA-Z0-9_./-]*\.[a-zA-Z0-9]+)<\/code>/g, function(match, ref) {
      if (/\s/.test(ref)) return match;
      return '<code class="file-ref" onclick="ArtifactPage._loadFile(\'' + ref + '\')" style="cursor:pointer">' + ref + '</code>';
    });
  }

  function isJobArtifact(path) {
    return path.indexOf('.sessions/') !== -1;
  }

  function jobConvId(path) {
    var m = path.match(/\.sessions\/([^/]+)\//);
    return m ? m[1] : null;
  }

  function renderMarkdown(content) {
    var html = marked.parse(content);
    html = rewriteInternalLinks(html);
    html = rewriteCodeFileRefs(html);
    return html;
  }

  var LANG_ALIASES = {
    yml: 'yaml', sh: 'bash', zsh: 'bash', bash: 'bash',
    js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript',
    rb: 'ruby', rs: 'rust', cpp: 'cpp', h: 'c', hpp: 'cpp',
    cfg: 'ini', txt: 'plaintext',
  };

  function renderCode(content, ext) {
    var lang = LANG_ALIASES[ext] || ext;
    try {
      if (hljs.getLanguage(lang)) {
        return '<pre><code class="hljs language-' + escHtml(lang) + '">' +
          hljs.highlight(content, {language: lang, ignoreIllegals: true}).value +
          '</code></pre>';
      }
      var result = hljs.highlightAuto(content);
      return '<pre><code class="hljs">' + result.value + '</code></pre>';
    } catch(e) {}
    return '<pre><code>' + escHtml(content) + '</code></pre>';
  }

  var IMAGE_EXTS = ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp'];

  // ── Per-instance state ─────────────────────────────────────────────────────

  var _config = {};
  var _container = null;
  var _bladeEl = null;
  var _chatInstance = null;
  var _sections = [];
  var _pinnedNodes = [];
  var _selectedFile = null;
  var _fileContent = null;
  var _loadError = null;
  var _gitStatuses = {};
  var _showChangedOnly = false;
  var _refreshInterval = null;
  var _ws = null;
  var _wsDestroyed = false;

  // ── Mount / Unmount ────────────────────────────────────────────────────────

  function mount(container, config) {
    _config = config || {};
    _container = container;
    _sections = [];
    _pinnedNodes = [];
    _selectedFile = null;
    _fileContent = null;
    _loadError = null;
    _gitStatuses = {};
    _showChangedOnly = false;

    // Build page shell: breadcrumb slot, content pane, blade
    container.innerHTML =
      '<div class="blade-layout">' +
      '<div id="breadcrumb-slot" style="padding:6px 12px"></div>' +
      '<div id="artifact-content" class="app-pane active" style="flex:1;min-width:0"></div>' +
      '<div class="blade" id="artifact-blade"></div>' +
      '</div>';

    _bladeEl = document.getElementById('artifact-blade');

    // Mount accordion chat blade via #400 shared implementation.
    // Forward chatLaunchRepo and chatAgentName so the blade can route the
    // agent to the correct repo once #397 adds launchRepo support.
    if (typeof AccordionChat !== 'undefined' && _bladeEl) {
      _chatInstance = AccordionChat.mount(_bladeEl, {
        convId: _config.chatConversationId || '',
        title: _config.chatTitle || '',
        launchRepo: _config.chatLaunchRepo || '',
        agentName: _config.chatAgentName || '',
      });

      // Subscribe to accordion-section-changed events for file-tree retargeting
      // in job mode. When per-sub-agent worktrees exist at the CfA tier, this
      // handler retargets the file tree to the selected section's worktree.
      // Until then, the handler no-ops on non-root sections.
      if (_config.mode === 'job' && _chatInstance.onSectionChanged) {
        _chatInstance.onSectionChanged(function(sectionInfo) {
          _handleAccordionSectionChanged(sectionInfo);
        });
      }
    }

    _init();
  }

  function unmount() {
    if (_refreshInterval) {
      clearInterval(_refreshInterval);
      _refreshInterval = null;
    }
    if (_ws) {
      _wsDestroyed = true;
      try { _ws.close(); } catch(e) {}
      _ws = null;
    }
    if (_chatInstance && _chatInstance.destroy) {
      _chatInstance.destroy();
      _chatInstance = null;
    }
    if (_container) {
      _container.innerHTML = '';
      _container = null;
    }
  }

  // ── Pinned nodes ──────────────────────────────────────────────────────��───

  async function fetchPins() {
    var project = _config.projectSlug || '';
    try {
      var resp = await fetch('/api/artifacts/' + encodeURIComponent(project) + '/pins');
      if (!resp.ok) { _pinnedNodes = []; return; }
      var data = await resp.json();
      _pinnedNodes = data.map(function(p) {
        return {path: p.path, label: p.label, is_dir: p.is_dir, expanded: false, children: null};
      });
    } catch(e) {
      _pinnedNodes = [];
    }
  }

  async function toggleFolder(path) {
    var node = _findNode(_pinnedNodes, path);
    if (!node) return;
    if (node.expanded) {
      node.expanded = false;
      _render();
      return;
    }
    node.expanded = true;
    if (node.children === null) {
      try {
        var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(path));
        if (resp.ok) {
          var data = await resp.json();
          node.children = (data.entries || []).map(function(e) {
            return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
          });
        } else {
          node.children = [];
        }
      } catch(e) {
        node.children = [];
      }
    }
    _render();
  }

  function _findNode(nodes, path) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].path === path) return nodes[i];
      if (nodes[i].children) {
        var found = _findNode(nodes[i].children, path);
        if (found) return found;
      }
    }
    return null;
  }

  async function _expandToPath(path, nodes) {
    nodes = nodes || _pinnedNodes;
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (node.path === path) return true;
      if (node.is_dir && path.startsWith(node.path + '/')) {
        node.expanded = true;
        if (node.children === null) {
          try {
            var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(node.path));
            if (resp.ok) {
              var data = await resp.json();
              node.children = (data.entries || []).map(function(e) {
                return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
              });
            } else {
              node.children = [];
            }
          } catch(e) {
            node.children = [];
          }
        }
        await _expandToPath(path, node.children);
        return true;
      }
    }
    return false;
  }

  // ── Git status ─────────────────────────────────────────────────────────────

  async function _fetchGitStatus() {
    var worktree = _config.chatLaunchRepo || '';
    if (!worktree) { _gitStatuses = {}; return; }
    try {
      var resp = await fetch('/api/git-status?path=' + encodeURIComponent(worktree));
      if (resp.ok) {
        var data = await resp.json();
        _gitStatuses = data.files || {};
      } else {
        _gitStatuses = {};
      }
    } catch(e) {
      _gitStatuses = {};
    }
  }

  function _gitStatusIndicator(filepath) {
    // Try matching by filename and by relative path
    var status = _gitStatuses[filepath];
    if (!status) {
      // Try basename match
      var basename = filepath.split('/').pop();
      for (var key in _gitStatuses) {
        if (key.split('/').pop() === basename && key.endsWith(filepath)) {
          status = _gitStatuses[key];
          break;
        }
      }
    }
    if (!status) return '';
    if (status === 'new') return '<span class="git-status-new" title="New (untracked)">\u25cf</span>';
    if (status === 'modified') return '<span class="git-status-modified" title="Modified">\u25cf</span>';
    if (status === 'deleted') return '<span class="git-status-deleted" title="Deleted">\u2717</span>';
    return '';
  }

  // ── Live refresh ──────────────────────────────────────────────────────���────

  function _startLiveRefresh() {
    // Poll git status every 2 seconds for live refresh.
    // Future: can be replaced with WebSocket-based filesystem watch events.
    _refreshInterval = setInterval(async function() {
      var prevStatuses = JSON.stringify(_gitStatuses);
      await _fetchGitStatus();
      var newStatuses = JSON.stringify(_gitStatuses);
      if (prevStatuses !== newStatuses) {
        // File tree changed — re-render to update indicators
        _render();
        // If the currently viewed file was modified, reload it
        if (_selectedFile && _gitStatuses[_selectedFile]) {
          _reloadCurrentFile();
        }
      }
    }, 2000);
  }

  async function _reloadCurrentFile() {
    if (!_selectedFile) return;
    var ext = _selectedFile.split('.').pop().toLowerCase();
    if (IMAGE_EXTS.indexOf(ext) !== -1 || ext === 'pdf') return;
    try {
      var resp = await fetch('/api/file?path=' + encodeURIComponent(_selectedFile));
      if (resp.ok) {
        var newContent = await resp.text();
        if (newContent !== _fileContent) {
          _fileContent = newContent;
          _render();
        }
      }
    } catch(e) {}
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function _renderPinnedNodes(nodes, depth) {
    var html = '';
    var indent = (depth * 12) + 'px';
    nodes.forEach(function(node) {
      var escapedPath = node.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      if (node.is_dir) {
        var icon = node.expanded ? '&#9660;' : '&#9654;';
        html += '<div class="artifact-nav-folder" style="padding-left:calc(10px + ' + indent + ')" onclick="ArtifactPage._toggleFolder(\'' + escapedPath + '\')">' +
          '<span class="artifact-nav-folder-icon">' + icon + '</span>' +
          '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
          '</div>';
        if (node.expanded && node.children && node.children.length > 0) {
          html += _renderPinnedNodes(node.children, depth + 1);
        } else if (node.expanded && node.children !== null && node.children.length === 0) {
          html += '<div class="artifact-nav-item" style="padding-left:calc(16px + ' + indent + ');font-style:italic;cursor:default">(empty)</div>';
        }
      } else {
        var isActive = _selectedFile === node.path;
        var statusHtml = _gitStatusIndicator(node.path);
        html += '<div class="artifact-nav-item ' + (isActive ? 'active' : '') + '" style="padding-left:calc(16px + ' + indent + ')" onclick="ArtifactPage._loadFile(\'' + escapedPath + '\')">' +
          statusHtml +
          '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
          '</div>';
      }
    });
    return html;
  }

  function renderOverview() {
    var displayName = _config.customTitle || (_config.projectSlug ? _config.projectSlug.charAt(0).toUpperCase() + _config.projectSlug.slice(1) : '');
    var html = '<div class="artifact-title">' + escHtml(displayName) + '</div>';
    html += '<div class="artifact-content">';
    if (_sections.length === 0) {
      html += '<p class="artifact-empty">No documentation found for this project.</p>';
    }
    _sections.forEach(function(sec) {
      html += '<h3>' + escHtml(sec.heading) + '</h3>';
      if (sec.body) {
        html += renderMarkdown(sec.body);
      } else {
        html += '<p class="artifact-empty">(no content)</p>';
      }
    });
    html += '</div>';
    return html;
  }

  function renderFileView(path, content) {
    var filename = path.split('/').pop();
    var ext = filename.includes('.') ? filename.split('.').pop().toLowerCase() : '';
    var codeExts = ['py', 'js', 'ts', 'jsx', 'tsx', 'json', 'yaml', 'yml', 'sh', 'bash', 'zsh',
      'toml', 'cfg', 'ini', 'html', 'css', 'rb', 'rs', 'go', 'java', 'c', 'cpp', 'h',
      'sql', 'xml', 'txt'];
    var fileUrl = '/api/file?path=' + encodeURIComponent(path);

    var html = '';
    html += '<div class="artifact-title">' + escHtml(filename) + '</div>';
    html += '<div class="artifact-path"><code>' + escHtml(path) + '</code></div>';

    if (isJobArtifact(path)) {
      var convId = jobConvId(path);
      if (convId) {
        html += '<a class="artifact-job-link" href="chat.html?conv=' + encodeURIComponent(convId) + '">View job conversation &#8594;</a>';
      }
    }

    var isCode = codeExts.indexOf(ext) !== -1;
    html += '<div class="artifact-content' + (isCode ? ' code-view' : '') + '">';
    if (ext === 'md') {
      html += renderMarkdown(content);
    } else if (IMAGE_EXTS.indexOf(ext) !== -1) {
      html += '<img src="' + fileUrl + '" style="max-width:100%;height:auto;display:block">';
    } else if (ext === 'pdf') {
      html += '<iframe src="' + fileUrl + '" style="width:100%;height:80vh;border:none"></iframe>';
    } else if (isCode) {
      html += renderCode(content, ext);
    } else {
      html += '<pre><code>' + escHtml(content) + '</code></pre>';
    }
    html += '</div>';

    return html;
  }

  function _render() {
    var contentEl = document.getElementById('artifact-content');
    if (!contentEl) return;

    var project = _config.projectSlug || '';
    var displayName = _config.customTitle || (project ? project.charAt(0).toUpperCase() + project.slice(1) : '');
    document.title = 'TeaParty \u2014 ' + displayName + (_config.mode === 'job' ? ' Job' : ' Artifacts');

    // Breadcrumb
    var bcSlot = document.getElementById('breadcrumb-slot');
    if (bcSlot && typeof breadcrumbBar === 'function') {
      var crumbs = [{ label: 'Home', href: 'index.html' }];
      if (_config.mode === 'job') {
        crumbs.push({ label: displayName, href: 'index.html?project=' + encodeURIComponent(project) });
        crumbs.push({ label: 'Job' });
      } else {
        crumbs.push({ label: displayName + ' Artifacts' });
      }
      bcSlot.innerHTML = breadcrumbBar(crumbs);
    }

    // ── Job-mode top strip ──────────────────────────────────────────────────
    var topStripHtml = '';
    if (_config.mode === 'job') {
      var changedCount = Object.keys(_gitStatuses).length;
      topStripHtml += '<div class="job-strip">';
      // Original request
      if (_config.originalRequest) {
        topStripHtml += '<div class="job-strip-request">' + escHtml(_config.originalRequest) + '</div>';
      }
      // Workflow bar (from workflow-bar.js)
      if (typeof renderWorkflow === 'function') {
        var pIdx = typeof phaseIndex === 'function' ? phaseIndex(_config.workflowPhase, _config.workflowState) : 0;
        topStripHtml += renderWorkflow(pIdx, true, !!_config.needsInput);
      }
      // Changed / All toggle
      topStripHtml += '<div class="job-strip-filter">';
      topStripHtml += '<button class="artifact-header-btn' + (_showChangedOnly ? ' active' : '') + '" onclick="ArtifactPage._toggleChangedFilter()">changed (' + changedCount + ')</button>';
      topStripHtml += '<button class="artifact-header-btn' + (!_showChangedOnly ? ' active' : '') + '" onclick="ArtifactPage._toggleChangedFilter()">all files</button>';
      topStripHtml += '</div>';
      topStripHtml += '</div>';
    }

    // ── Header ──────────────────────────────────────────────────────────────
    var showCopy = _selectedFile !== null && _fileContent !== null && _fileContent !== '';
    var copyBtn = showCopy
      ? '<button id="copy-btn" class="artifact-header-btn" onclick="ArtifactPage._copyFileContent()" title="Copy file content">Copy</button>'
      : '';
    var headerHtml = '<div class="artifact-header">' +
      '<span class="artifact-header-title">' + escHtml(displayName) + (_config.mode === 'job' ? ' Job' : ' Artifacts') + '</span>' +
      '<div style="display:flex;gap:6px">' + copyBtn +
      '<button class="artifact-header-btn" onclick="ArtifactPage._refresh()" title="Reload">\u21ba Refresh</button>' +
      '</div>' +
      '</div>';

    // ── Nav ─────────────────────────────────────────────────────────────────
    var navHtml = '<div class="artifact-nav">';

    if (_pinnedNodes.length > 0) {
      navHtml += '<div class="artifact-nav-section">Pinned</div>';
      navHtml += _renderPinnedNodes(_pinnedNodes, 0);
    }

    if (_sections.length > 0) {
      if (_pinnedNodes.length > 0) {
        navHtml += '<div class="artifact-nav-divider">Documentation</div>';
      } else {
        navHtml += '<div class="artifact-nav-section">Documentation</div>';
      }
    }
    _sections.forEach(function(sec) {
      if (_pinnedNodes.length > 0) {
        navHtml += '<div class="artifact-nav-folder" style="cursor:default;color:var(--text-dim);padding-left:10px">' +
          '<span class="artifact-nav-item-label">' + escHtml(sec.heading) + '</span></div>';
      } else {
        navHtml += '<div class="artifact-nav-section">' + escHtml(sec.heading) + '</div>';
      }
      if (sec.items.length === 0) {
        navHtml += '<div class="artifact-nav-item" style="font-style:italic;cursor:default">(no items)</div>';
      }
      sec.items.forEach(function(item) {
        // Apply changed-only filter in job mode
        if (_showChangedOnly && _config.mode === 'job') {
          var basename = item.path.split('/').pop();
          var isChanged = false;
          for (var key in _gitStatuses) {
            if (key === item.path || key.endsWith('/' + basename)) { isChanged = true; break; }
          }
          if (!isChanged) return;
        }
        var isActive = _selectedFile === item.path;
        var statusHtml = _gitStatusIndicator(item.path);
        navHtml += '<div class="artifact-nav-item ' + (isActive ? 'active' : '') + '">' +
          statusHtml +
          '<span class="artifact-nav-item-label" onclick="ArtifactPage._loadFile(\'' + item.path + '\')">' + escHtml(item.name) + '</span>' +
          '<span class="artifact-nav-close" onclick="ArtifactPage._closeFile(\'' + item.path + '\')" title="Close">&times;</span>' +
          '</div>';
      });
    });
    navHtml += '</div>';

    // ── Main ────────────────────────────────────────────────────────────────
    var mainHtml = '<div class="artifact-main">';
    if (_loadError) {
      mainHtml += '<div class="artifact-loading">' + escHtml(_loadError) + '</div>';
    } else if (_selectedFile !== null && _fileContent === null) {
      mainHtml += '<div class="artifact-loading">Loading\u2026</div>';
    } else if (_selectedFile !== null && _fileContent !== null) {
      mainHtml += renderFileView(_selectedFile, _fileContent);
    } else {
      mainHtml += renderOverview();
    }
    mainHtml += '</div>';

    contentEl.innerHTML =
      topStripHtml + headerHtml + '<div class="artifact-layout">' + navHtml + mainHtml + '</div>';

    // Highlight code blocks
    contentEl.querySelectorAll('.artifact-content pre code:not(.hljs)').forEach(function(el) {
      hljs.highlightElement(el);
    });
  }

  // ── Accordion section retargeting (job mode) ───────────────────────────────

  function _handleAccordionSectionChanged(sectionInfo) {
    // In job mode, retarget the file tree to the selected section's worktree.
    // Until per-sub-agent worktrees exist at the CfA tier, this no-ops for
    // non-root sections — the file tree always shows the job worktree.
    if (!sectionInfo || !sectionInfo.worktree) return;
    var newWorktree = sectionInfo.worktree;
    if (newWorktree === _config.chatLaunchRepo) return;
    _config.chatLaunchRepo = newWorktree;
    _fetchGitStatus().then(function() { _render(); });
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  function _copyFileContent() {
    navigator.clipboard.writeText(_fileContent).then(function() {
      var btn = document.getElementById('copy-btn');
      if (!btn) return;
      btn.textContent = 'Copied';
      setTimeout(function() {
        var b = document.getElementById('copy-btn');
        if (b) b.textContent = 'Copy';
      }, 1500);
    });
  }

  async function loadFile(path) {
    if (_selectedFile && !path.startsWith('/')) {
      var dir = _selectedFile.substring(0, _selectedFile.lastIndexOf('/'));
      path = dir + '/' + path;
    }
    path = path.split('/').reduce(function(acc, seg) {
      if (seg === '..') { acc.pop(); } else if (seg !== '.') { acc.push(seg); }
      return acc;
    }, []).join('/');
    _selectedFile = path;
    _fileContent = null;
    _loadError = null;

    // Update chat blade context
    if (_chatInstance && _chatInstance.configure) {
      _chatInstance.configure({
        convId: 'config:artifact:' + (_config.projectSlug || 'org') + ':' + path,
        title: _config.chatTitle || '',
      });
    }

    var inPinned = await _expandToPath(path);
    var inNav = inPinned || _sections.some(function(s) {
      return s.items.some(function(i) { return i.path === path; });
    });
    if (!inNav) {
      var name = path.split('/').pop();
      if (_sections.length === 0) {
        _sections = [{heading: 'File', items: [{name: name, path: path}]}];
      } else {
        _sections[0].items.push({name: name, path: path});
      }
    }

    var ext = path.split('.').pop().toLowerCase();
    if (IMAGE_EXTS.indexOf(ext) !== -1 || ext === 'pdf') {
      _fileContent = '';
      _render();
      return;
    }

    _render();

    try {
      var resp = await fetch('/api/file?path=' + encodeURIComponent(path));
      if (!resp.ok) {
        _loadError = resp.status === 404 ? 'File not found: ' + path : 'Error loading file (' + resp.status + ')';
      } else {
        _fileContent = await resp.text();
      }
    } catch(e) {
      _loadError = 'Could not load file: ' + e.message;
    }
    _render();
  }

  function _closeFile(path) {
    _sections = _sections.map(function(s) {
      return {heading: s.heading, items: s.items.filter(function(i) { return i.path !== path; }), body: s.body};
    }).filter(function(s) { return s.items.length > 0; });
    if (_selectedFile === path) {
      _selectedFile = null;
      _fileContent = null;
      _loadError = null;
      var first = _sections.length > 0 && _sections[0].items.length > 0 ? _sections[0].items[0] : null;
      if (first) { loadFile(first.path); return; }
    }
    _render();
  }

  function _toggleChangedFilter() {
    _showChangedOnly = !_showChangedOnly;
    _render();
  }

  async function _refresh() {
    var project = _config.projectSlug || '';
    if (_config.requestedFile) {
      if (_selectedFile) loadFile(_selectedFile);
      return;
    }
    _loadError = null;
    try {
      var [artResp, pinsResp, _gitResp] = await Promise.all([
        fetch('/api/artifacts/' + encodeURIComponent(project)),
        fetch('/api/artifacts/' + encodeURIComponent(project) + '/pins'),
        _fetchGitStatus(),
      ]);
      if (pinsResp.ok) {
        var pinsData = await pinsResp.json();
        _pinnedNodes = pinsData.map(function(p) {
          return {path: p.path, label: p.label, is_dir: p.is_dir, expanded: false, children: null};
        });
      }
      if (!artResp.ok) {
        _loadError = artResp.status === 404
          ? 'No documentation found for project: ' + project
          : 'Error loading project (' + artResp.status + ')';
        _render();
        return;
      }
      var data = await artResp.json();
      _sections = Object.entries(data).map(function(entry) {
        return {heading: entry[0], items: parseMdLinks(entry[1]), body: entry[1]};
      });
    } catch(e) {
      _loadError = 'Could not connect to bridge: ' + e.message;
      _render();
      return;
    }
    if (_selectedFile) { _fileContent = null; loadFile(_selectedFile); } else { _render(); }
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  async function _init() {
    var project = _config.projectSlug || '';
    var requestedFile = _config.requestedFile || null;

    // Fetch git status first
    await _fetchGitStatus();

    if (requestedFile) {
      var filename = requestedFile.split('/').pop();
      _sections = [{heading: 'File', items: [{name: filename, path: requestedFile}]}];
      await fetchPins();
      await loadFile(requestedFile);
      _startLiveRefresh();
      return;
    }

    try {
      var [artResp, pinsResp] = await Promise.all([
        fetch('/api/artifacts/' + encodeURIComponent(project)),
        fetch('/api/artifacts/' + encodeURIComponent(project) + '/pins'),
      ]);
      if (pinsResp.ok) {
        var pinsData = await pinsResp.json();
        _pinnedNodes = pinsData.map(function(p) {
          return {path: p.path, label: p.label, is_dir: p.is_dir, expanded: false, children: null};
        });
      }
      if (!artResp.ok) {
        _loadError = artResp.status === 404
          ? 'No documentation found for project: ' + project
          : 'Error loading project (' + artResp.status + ')';
        _render();
        _startLiveRefresh();
        return;
      }
      var data = await artResp.json();
      _sections = Object.entries(data).map(function(entry) {
        return {heading: entry[0], items: parseMdLinks(entry[1]), body: entry[1]};
      });
    } catch(e) {
      _loadError = 'Could not connect to bridge: ' + e.message;
      _render();
      _startLiveRefresh();
      return;
    }

    _render();
    _startLiveRefresh();
  }

  // ── Public module API ─────────────────────────────────────────────────────

  global.ArtifactPage = {
    mount: mount,
    unmount: unmount,
    // Internal methods exposed for onclick handlers in innerHTML strings.
    _loadFile: loadFile,
    _closeFile: _closeFile,
    _toggleFolder: toggleFolder,
    _refresh: _refresh,
    _copyFileContent: _copyFileContent,
    _toggleChangedFilter: _toggleChangedFilter,
  };

})(window);
