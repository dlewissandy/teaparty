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
  var _breadcrumbEl = null;
  var _bladeEl = null;
  var _chatInstance = null;
  var _sections = [];
  var _pinnedNodes = [];
  var _pinnedPathSet = {};  // {abs_path: true} — rebuilt whenever _pinnedNodes changes
  var _selectedFile = null;
  var _fileContent = null;
  var _loadError = null;
  var _gitStatuses = {};
  var _repoFiles = [];    // [{path, label, is_dir, expanded, children}] — full repo tree
  var _filterPinned = false;
  var _filterChanged = false;
  var _refreshInterval = null;
  var _ws = null;
  var _wsDestroyed = false;

  // ── Mount / Unmount ────────────────────────────────────────────────────────

  function mount(config) {
    _config = config || {};
    _container = _config.contentEl || null;
    _bladeEl = _config.bladeEl || null;
    _breadcrumbEl = _config.breadcrumbEl || null;
    _sections = [];
    _pinnedNodes = [];
    _selectedFile = null;
    _fileContent = null;
    _loadError = null;
    _gitStatuses = {};
    // Default filters: job mode shows changed files, browse mode shows pinned
    _filterPinned = _config.mode !== 'job';
    _filterChanged = _config.mode === 'job';

    // Mount accordion chat blade via #400 shared implementation.
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

  // ── Repo file tree ─────────────────────────────────────────────────────

  async function _fetchRepoFiles() {
    var worktree = _config.chatLaunchRepo || '';
    if (!worktree) {
      // For browse mode, resolve from project slug
      try {
        var resp = await fetch('/api/fs/list?project=' + encodeURIComponent(_config.projectSlug || ''));
        if (resp.ok) {
          var data = await resp.json();
          worktree = data.path || '';
          _config.chatLaunchRepo = worktree;
          _repoFiles = (data.entries || [])
            .filter(function(e) { return !e.name.startsWith('.'); })
            .map(function(e) {
              return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
            });
          return;
        }
      } catch(e) {}
      _repoFiles = [];
      return;
    }
    try {
      var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(worktree));
      if (resp.ok) {
        var data = await resp.json();
        _repoFiles = (data.entries || [])
          .filter(function(e) { return !e.name.startsWith('.'); })
          .map(function(e) {
            return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
          });
      } else {
        _repoFiles = [];
      }
    } catch(e) {
      _repoFiles = [];
    }
  }

  // ── Pinned nodes ──────────────────────────────────────────────────────────

  async function fetchPins() {
    var project = _config.projectSlug || '';
    var scope = _config.pinScope || 'project';
    var name = _config.pinName || '';
    var url = '/api/pins?scope=' + encodeURIComponent(scope) +
              '&project=' + encodeURIComponent(project) +
              (name ? '&name=' + encodeURIComponent(name) : '');
    try {
      var resp = await fetch(url);
      if (!resp.ok) { _pinnedNodes = []; return; }
      var data = await resp.json();
      _pinnedNodes = data.map(function(p) {
        return {path: p.path, label: p.label, is_dir: p.is_dir, expanded: false, children: null};
      });
      _rebuildPinnedPathSet();
    } catch(e) {
      _pinnedNodes = [];
      _pinnedPathSet = {};
    }
  }

  function _rebuildPinnedPathSet() {
    _pinnedPathSet = {};
    (function collect(nodes) {
      nodes.forEach(function(n) {
        _pinnedPathSet[n.path] = true;
        if (n.children) collect(n.children);
      });
    })(_pinnedNodes);
  }

  async function _togglePin(path) {
    var project = _config.projectSlug || '';
    var scope = _config.pinScope || 'project';
    var name = _config.pinName || '';
    var isPinned = !!_pinnedPathSet[path];
    var label = path.split('/').pop() || path;
    var params = '?scope=' + encodeURIComponent(scope) +
                 '&project=' + encodeURIComponent(project) +
                 (name ? '&name=' + encodeURIComponent(name) : '');
    try {
      var patchBody = isPinned
        ? {remove: {path: path}}
        : {add: {path: path, label: label}};
      var resp = await fetch('/api/pins' + params, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(patchBody),
      });
      if (resp.ok) {
        await fetchPins();
        _render();
      } else {
        var errText = await resp.text().catch(function() { return ''; });
        console.error('[pin-toggle] PATCH /api/pins returned', resp.status, errText);
      }
    } catch(e) {
      console.error('[pin-toggle] fetch error:', e);
    }
  }

  async function toggleFolder(path) {
    // Find the node in all trees — expand/collapse must apply to whichever
    // tree is being rendered, and both if both contain the path.
    var nodes = [_findNode(_repoFiles, path), _findNode(_pinnedNodes, path)].filter(Boolean);
    if (nodes.length === 0) return;
    var isExpanded = nodes[0].expanded;
    if (isExpanded) {
      nodes.forEach(function(n) { n.expanded = false; });
      _render();
      return;
    }
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      node.expanded = true;
      if (node.children === null) {
        try {
          var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(path));
          if (resp.ok) {
            var data = await resp.json();
            node.children = (data.entries || [])
              .filter(function(e) { return !e.name.startsWith('.'); })
              .map(function(e) {
                return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
              });
          } else {
            node.children = [];
          }
        } catch(e) {
          node.children = [];
        }
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
        var raw = data.files || {};
        // Exclude files in hidden directories
        _gitStatuses = {};
        for (var k in raw) {
          if (k.split('/').some(function(seg) { return seg.startsWith('.'); })) continue;
          _gitStatuses[k] = raw[k];
        }
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
    _refreshInterval = setInterval(async function() {
      var needsRender = false;

      // Poll git status for file tree indicators
      var prevStatuses = JSON.stringify(_gitStatuses);
      await _fetchGitStatus();
      if (prevStatuses !== JSON.stringify(_gitStatuses)) {
        needsRender = true;
        if (_selectedFile && _gitStatuses[_selectedFile]) {
          _reloadCurrentFile();
        }
      }

      // In job mode, poll CfA state for the workflow bar
      if (_config.mode === 'job') {
        var prevPhase = _config.workflowState;
        await _fetchCfaState();
        if (_config.workflowState !== prevPhase) needsRender = true;
      }

      if (needsRender) _render();
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
      var isPinned = !!_pinnedPathSet[node.path];
      var pinSlot = '<span class="artifact-nav-pin' + (isPinned ? ' pinned' : '') + '" title="' + (isPinned ? 'Unpin' : 'Pin') + '" onclick="event.stopPropagation();ArtifactPage._togglePin(\'' + escapedPath + '\')">' + (isPinned ? '&#128204;' : '') + '</span>';
      if (node.is_dir) {
        var icon = node.expanded ? '&#9660;' : '&#9654;';
        html += '<div class="artifact-nav-folder" style="padding-left:calc(10px + ' + indent + ')" onclick="if(!event.target.classList.contains(\'artifact-nav-pin\'))ArtifactPage._toggleFolder(\'' + escapedPath + '\')">' +
          '<span class="artifact-nav-folder-icon">' + icon + '</span>' +
          '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
          pinSlot +
          '</div>';
        if (node.expanded && node.children && node.children.length > 0) {
          html += _renderPinnedNodes(node.children, depth + 1);
        } else if (node.expanded && node.children !== null && node.children.length === 0) {
          html += '<div class="artifact-nav-item" style="padding-left:calc(16px + ' + indent + ');font-style:italic;cursor:default">(empty)</div>';
        }
      } else {
        var isActive = _selectedFile === node.path;
        var statusHtml = _gitStatusIndicator(node.path);
        html += '<div class="artifact-nav-item ' + (isActive ? 'active' : '') + '" style="padding-left:calc(16px + ' + indent + ')" onclick="if(!event.target.classList.contains(\'artifact-nav-pin\'))ArtifactPage._loadFile(\'' + escapedPath + '\')">' +
          statusHtml +
          '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
          pinSlot +
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
        html += '<a class="artifact-job-link" href="job.html?conv=' + encodeURIComponent(convId) + '">View job &#8594;</a>';
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

  // Build breadcrumb trail based on scope context.
  // Browse mode: [Home, <scope chain>, Artifacts]
  // Job mode:    [Home, <project>, Job]
  function _buildCrumbs(project, displayName) {
    var scope = _config.pinScope || 'project';
    var name = _config.pinName || '';
    var crumbs = [{ label: 'Home', href: 'index.html' }];

    if (_config.mode === 'job') {
      if (project) crumbs.push({ label: displayName, href: 'index.html?project=' + encodeURIComponent(project) });
      crumbs.push({ label: 'Job' });
      return crumbs;
    }

    // Browse mode — chain matches config.html's scopeCrumbs() hierarchy,
    // with href links so they work outside the config SPA.
    var projLabel = displayName + ' Team';
    var projHref = project ? 'config.html?project=' + encodeURIComponent(project) : null;

    switch (scope) {
      case 'system':
        crumbs.push({ label: 'Management Team', href: 'config.html' });
        break;
      case 'project':
        crumbs.push({ label: 'Management Team', href: 'config.html' });
        if (project) crumbs.push({ label: projLabel, href: projHref });
        break;
      case 'agent':
        crumbs.push({ label: 'Management Team', href: 'config.html' });
        if (project) crumbs.push({ label: projLabel, href: projHref });
        if (name) crumbs.push({ label: name, href: 'config.html?agent=' + encodeURIComponent(name) + (project ? '&project=' + encodeURIComponent(project) : '') });
        break;
      case 'workgroup':
        crumbs.push({ label: 'Management Team', href: 'config.html' });
        if (project) crumbs.push({ label: projLabel, href: projHref });
        if (name) crumbs.push({ label: name, href: 'config.html?workgroup=' + encodeURIComponent(name) + (project ? '&project=' + encodeURIComponent(project) : '') });
        break;
      case 'job':
        if (project) crumbs.push({ label: displayName, href: 'index.html?project=' + encodeURIComponent(project) });
        if (name) crumbs.push({ label: name });
        break;
      default:
        if (project) crumbs.push({ label: projLabel, href: projHref });
        break;
    }

    crumbs.push({ label: 'Artifacts' });
    return crumbs;
  }

  function _render() {
    var contentEl = _container;
    if (!contentEl) return;

    var project = _config.projectSlug || '';
    var displayName = _config.customTitle || (project ? project.charAt(0).toUpperCase() + project.slice(1) : '');
    document.title = 'TeaParty \u2014 ' + displayName + (_config.mode === 'job' ? ' Job' : ' Artifacts');

    // Breadcrumb
    var bcSlot = _breadcrumbEl;
    if (bcSlot && typeof breadcrumbBar === 'function') {
      bcSlot.innerHTML = breadcrumbBar(_buildCrumbs(project, displayName));
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
      // Workflow bar — same renderWorkflow/phaseIndex from workflow-bar.js
      // that the home page uses. Wrapped in flex:1 span so it fills available
      // space in the job-strip row, matching the home page pattern.
      if (typeof renderWorkflow === 'function') {
        var pIdx = typeof phaseIndex === 'function' ? phaseIndex(_config.workflowPhase, _config.workflowState) : 0;
        topStripHtml += '<span style="flex:1">' + renderWorkflow(pIdx, true, !!_config.needsInput) + '</span>';
      }
      topStripHtml += '</div>';
    }

    // ── Header ──────────────────────────────────────────────────────────────
    var showCopy = _selectedFile !== null && _fileContent !== null && _fileContent !== '';
    var copyBtn = showCopy
      ? '<button id="copy-btn" class="artifact-header-btn" onclick="ArtifactPage._copyFileContent()" title="Copy file content">Copy</button>'
      : '';
    var changedCount = Object.keys(_gitStatuses).length;
    var pinnedCount = _pinnedNodes.length;
    var filterHtml =
      '<button class="artifact-header-btn' + (_filterPinned ? ' active' : '') + '" onclick="ArtifactPage._toggleFilter(\'pinned\')">Pinned' + (pinnedCount ? ' (' + pinnedCount + ')' : '') + '</button>' +
      '<button class="artifact-header-btn' + (_filterChanged ? ' active' : '') + '" onclick="ArtifactPage._toggleFilter(\'changed\')">Changed' + (changedCount ? ' (' + changedCount + ')' : '') + '</button>';
    var headerHtml = '<div class="artifact-header">' +
      '<span class="artifact-header-title">' + escHtml(displayName) + (_config.mode === 'job' ? ' Job' : ' Artifacts') + '</span>' +
      '<div style="display:flex;gap:6px">' + filterHtml + copyBtn +
      '<button class="artifact-header-btn" onclick="ArtifactPage._refresh()" title="Reload">\u21ba Refresh</button>' +
      '</div>' +
      '</div>';

    // ── Nav with [Pinned][Changed] conjunctive filters ────────────────────
    //
    // The base view is the repo file tree (_repoFiles). Filters narrow it:
    //   - Pinned: only show files/dirs in the pinned set
    //   - Changed: only show files with git-status changes
    //   - Both: show files that are pinned AND changed
    //   - Neither: show all non-hidden files in the repo

    var navHtml = '<div class="artifact-nav">';

    var pinnedPathSet = _pinnedPathSet;

    function _isFileChanged(filepath) {
      if (_gitStatuses[filepath]) return true;
      // git status uses relative paths; try matching the tail
      var worktree = _config.chatLaunchRepo || '';
      if (worktree) {
        var rel = filepath.startsWith(worktree) ? filepath.slice(worktree.length + 1) : filepath;
        if (_gitStatuses[rel]) return true;
      }
      return false;
    }

    function _isDirChanged(dirpath) {
      var prefix = dirpath.endsWith('/') ? dirpath : dirpath + '/';
      var worktree = _config.chatLaunchRepo || '';
      for (var key in _gitStatuses) {
        var abs = (worktree && !key.startsWith('/')) ? worktree + '/' + key : key;
        if (abs.startsWith(prefix)) return true;
      }
      return false;
    }

    function _renderFileTree(nodes, depth) {
      var html = '';
      var indent = (depth * 12) + 'px';
      nodes.forEach(function(node) {
        var escapedPath = node.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        if (node.is_dir) {
          var dirPrefix = node.path.endsWith('/') ? node.path : node.path + '/';
          var dirChanged = _isDirChanged(node.path);
          // Skip dirs with no matching descendants under active filters
          if (_filterChanged && !dirChanged) {
            if (!_filterPinned) return;
          }
          if (_filterPinned) {
            // Show dir if it or any descendant path is pinned
            var hasPinnedDescendant = !!pinnedPathSet[node.path];
            if (!hasPinnedDescendant) {
              for (var pp in pinnedPathSet) {
                if (pp.startsWith(dirPrefix)) { hasPinnedDescendant = true; break; }
              }
            }
            if (!hasPinnedDescendant) return;
            // If both filters active, also need changed descendants
            if (_filterChanged && !_isDirChanged(node.path)) return;
          }
          var icon = node.expanded ? '&#9660;' : '&#9654;';
          var dirIsPinned = !!pinnedPathSet[node.path];
          var dirPinSlot = '<span class="artifact-nav-pin' + (dirIsPinned ? ' pinned' : '') + '" title="' + (dirIsPinned ? 'Unpin' : 'Pin') + '" onclick="event.stopPropagation();ArtifactPage._togglePin(\'' + escapedPath + '\')">' + (dirIsPinned ? '&#128204;' : '') + '</span>';
          html += '<div class="artifact-nav-folder" style="padding-left:calc(10px + ' + indent + ')" onclick="if(!event.target.classList.contains(\'artifact-nav-pin\'))ArtifactPage._toggleFolder(\'' + escapedPath + '\')">' +
            '<span class="artifact-nav-folder-icon">' + icon + '</span>' +
            '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
            dirPinSlot +
            '</div>';
          if (node.expanded && node.children && node.children.length > 0) {
            html += _renderFileTree(node.children, depth + 1);
          }
        } else {
          if (_filterPinned && !pinnedPathSet[node.path]) return;
          if (_filterChanged && !_isFileChanged(node.path)) return;
          var isActive = _selectedFile === node.path;
          var statusHtml = _gitStatusIndicator(node.path);
          var fileIsPinned = !!pinnedPathSet[node.path];
          var filePinSlot = '<span class="artifact-nav-pin' + (fileIsPinned ? ' pinned' : '') + '" title="' + (fileIsPinned ? 'Unpin' : 'Pin') + '" onclick="event.stopPropagation();ArtifactPage._togglePin(\'' + escapedPath + '\')">' + (fileIsPinned ? '&#128204;' : '') + '</span>';
          html += '<div class="artifact-nav-item ' + (isActive ? 'active' : '') + '" style="padding-left:calc(16px + ' + indent + ')" onclick="if(!event.target.classList.contains(\'artifact-nav-pin\'))ArtifactPage._loadFile(\'' + escapedPath + '\')">' +
            statusHtml +
            '<span class="artifact-nav-item-label">' + escHtml(node.label) + '</span>' +
            filePinSlot +
            '</div>';
        }
      });
      return html;
    }

    // Render the file tree
    if (_repoFiles.length > 0) {
      navHtml += _renderFileTree(_repoFiles, 0);
    } else if (_pinnedNodes.length > 0) {
      navHtml += '<div class="artifact-nav-section">Pinned</div>';
      navHtml += _renderPinnedNodes(_pinnedNodes, 0);
    } else {
      navHtml += '<div class="artifact-nav-item" style="font-style:italic;cursor:default">(no files)</div>';
    }

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

    // Update chat blade context — keep the project lead conversation
    if (_chatInstance && _chatInstance.configure) {
      _chatInstance.configure({
        convId: _config.chatConversationId || '',
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

  async function _toggleFilter(which) {
    if (which === 'pinned') _filterPinned = !_filterPinned;
    if (which === 'changed') _filterChanged = !_filterChanged;
    // Auto-expand directories needed to reveal matching files
    await _autoExpandForFilters();
    _render();
  }

  async function _autoExpandForFilters() {
    if (!_filterPinned && !_filterChanged) return;
    var worktree = _config.chatLaunchRepo || '';
    // Collect absolute paths of files that pass the active filter
    var targets = [];
    if (_filterChanged) {
      for (var rel in _gitStatuses) {
        var abs = (worktree && !rel.startsWith('/')) ? worktree + '/' + rel : rel;
        targets.push(abs);
      }
    }
    if (_filterPinned) {
      // Include pinned file paths (not dirs — dirs are expanded to show contents)
      (function walk(nodes) {
        nodes.forEach(function(n) {
          if (!n.is_dir) targets.push(n.path);
          if (n.children) walk(n.children);
        });
      })(_pinnedNodes);
    }
    // For each target, expand every ancestor directory in _repoFiles
    for (var i = 0; i < targets.length; i++) {
      await _expandAncestors(targets[i], _repoFiles);
    }
    // For pinned-only view (no repo tree), expand pinned dirs that contain other pinned items
    if (_filterPinned && _repoFiles.length === 0) {
      for (var j = 0; j < _pinnedNodes.length; j++) {
        var node = _pinnedNodes[j];
        if (!node.is_dir) continue;
        var dirPrefix = node.path.endsWith('/') ? node.path : node.path + '/';
        var hasChild = _pinnedNodes.some(function(n) { return n.path.startsWith(dirPrefix); });
        if (!hasChild) continue;
        node.expanded = true;
        if (node.children === null) {
          try {
            var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(node.path));
            if (resp.ok) {
              var data = await resp.json();
              node.children = (data.entries || [])
                .filter(function(e) { return !e.name.startsWith('.'); })
                .map(function(e) {
                  return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
                });
            } else {
              node.children = [];
            }
          } catch(e) {
            node.children = [];
          }
        }
      }
    }
  }

  async function _expandAncestors(filepath, nodes) {
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (!node.is_dir) continue;
      var dirPrefix = node.path.endsWith('/') ? node.path : node.path + '/';
      if (!filepath.startsWith(dirPrefix)) continue;
      // This directory is an ancestor — expand it
      node.expanded = true;
      if (node.children === null) {
        try {
          var resp = await fetch('/api/fs/list?path=' + encodeURIComponent(node.path));
          if (resp.ok) {
            var data = await resp.json();
            node.children = (data.entries || [])
              .filter(function(e) { return !e.name.startsWith('.'); })
              .map(function(e) {
                return {path: e.path, label: e.name, is_dir: e.is_dir, expanded: false, children: null};
              });
          } else {
            node.children = [];
          }
        } catch(e) {
          node.children = [];
        }
      }
      // Recurse into children
      await _expandAncestors(filepath, node.children);
      return;
    }
  }

  async function _refresh() {
    var project = _config.projectSlug || '';
    if (_config.requestedFile) {
      if (_selectedFile) loadFile(_selectedFile);
      return;
    }
    _loadError = null;
    try {
      var [artResp, _gitResp] = await Promise.all([
        fetch('/api/artifacts/' + encodeURIComponent(project)),
        _fetchGitStatus(),
      ]);
      await fetchPins();
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

  // ── CfA state (job mode) ────────────────────────────────────────────────

  function _deriveSessionId() {
    var convId = _config.chatConversationId || '';
    if (convId.startsWith('job:')) {
      var parts = convId.split(':');
      return parts.length >= 3 ? parts[2] : '';
    }
    return '';
  }

  async function _fetchCfaState() {
    var sessionId = _deriveSessionId();
    if (!sessionId) return;
    try {
      var resp = await fetch('/api/cfa/' + encodeURIComponent(sessionId));
      if (resp.ok) {
        var data = await resp.json();
        _config.workflowPhase = data.phase || _config.workflowPhase || '';
        _config.workflowState = data.state || _config.workflowState || '';
        _config.needsInput = data.needs_input || false;
        if (data.task) _config.originalRequest = _config.originalRequest || data.task;
      }
    } catch(e) {}
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  async function _init() {
    var project = _config.projectSlug || '';
    var requestedFile = _config.requestedFile || null;

    // In job mode, fetch live CfA state so the workflow bar is current.
    if (_config.mode === 'job') {
      await _fetchCfaState();
    }

    // Fetch repo file listing and git status in parallel
    await Promise.all([_fetchRepoFiles(), _fetchGitStatus()]);

    if (requestedFile) {
      var filename = requestedFile.split('/').pop();
      _sections = [{heading: 'File', items: [{name: filename, path: requestedFile}]}];
      await fetchPins();
      await loadFile(requestedFile);
      _startLiveRefresh();
      return;
    }

    var requestedDir = _config.requestedDir || null;
    if (requestedDir) {
      await fetchPins();
      try {
        var artResp = await fetch('/api/artifacts/' + encodeURIComponent(project));
        if (artResp.ok) {
          var artData = await artResp.json();
          _sections = Object.entries(artData).map(function(entry) {
            return {heading: entry[0], items: parseMdLinks(entry[1]), body: entry[1]};
          });
        }
      } catch(e) {}
      await toggleFolder(requestedDir);
      _startLiveRefresh();
      return;
    }

    try {
      var [artResp] = await Promise.all([
        fetch('/api/artifacts/' + encodeURIComponent(project)),
      ]);
      await fetchPins();
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

    // Auto-expand tree for default filters before first render
    await _autoExpandForFilters();
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
    _togglePin: _togglePin,
    _refresh: _refresh,
    _copyFileContent: _copyFileContent,
    _toggleFilter: _toggleFilter,
  };

})(window);
