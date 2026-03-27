// ── Chat window ──────────────────────────────────

function openChatWindow(title, scope, messages, initialPrompt) {
  const w = window.open('', '_blank', 'width=560,height=650');
  if (!w) { alert('Popup blocked — would open new terminal window for: ' + title); return; }

  const streamEntries = [];
  messages.forEach(m => {
    streamEntries.push({ cls: m.sender === 'human' ? 'user' : 'text', sender: m.sender, text: m.text });
  });
  if (messages.length > 0) {
    streamEntries.splice(0, 0,
      { cls: 'system', sender: 'system', text: 'Session initialized · model: claude-opus-4 · permission: acceptEdits' },
      { cls: 'state', sender: 'state', text: 'IDLE → WORK' },
    );
    streamEntries.splice(3, 0,
      { cls: 'thinking', sender: 'thinking', text: 'Let me analyze the current state of the implementation and what the human is likely concerned about given their recent focus on test coverage and rollback strategies...' },
      { cls: 'tool', sender: 'tool_use', text: 'Read(file_path="projects/POC/orchestrator/tests/test_retrieval.py")' },
      { cls: 'tool_result', sender: 'tool_result', text: '→ 142 lines, 6 test methods, 2 failing' },
    );
    streamEntries.push(
      { cls: 'result', sender: 'result', text: 'Turn complete · 3.2K tokens · $0.04 · 8.3s' },
    );
  }
  if (initialPrompt) {
    streamEntries.push({ cls: 'user', sender: 'human', text: initialPrompt });
  }

  const clsColors = {
    text: '#a78bfa', user: '#4ecca3', thinking: '#f0c040', tool: '#e07020',
    tool_result: '#e07020', system: '#555', state: '#4ecca3', result: '#555', log: '#555'
  };
  const clsBg = {
    text: '#1a1a2e', user: '#1a1a2e', thinking: 'rgba(240,192,64,0.05)', tool: 'rgba(224,112,32,0.05)',
    tool_result: 'rgba(224,112,32,0.05)', system: 'rgba(85,85,85,0.1)', state: 'rgba(78,204,163,0.05)',
    result: 'rgba(85,85,85,0.1)', log: 'rgba(85,85,85,0.1)'
  };

  const entriesHtml = streamEntries.map(e =>
    `<div class="entry ${e.cls}" data-cls="${e.cls}" style="margin-bottom:8px;${['text','user'].includes(e.cls)?'':'display:none'}">
      <div style="font-size:8px;font-weight:600;color:${clsColors[e.cls]};text-transform:uppercase;letter-spacing:0.5px">${e.sender}</div>
      <div style="font-size:11px;line-height:1.4;color:#888;background:${clsBg[e.cls]};padding:6px 8px;border-radius:4px;${e.cls==='thinking'?'font-style:italic;':''}">${e.text.replace(/\n/g,'<br>')}</div>
    </div>`
  ).join('');

  w.document.write(`<!DOCTYPE html><html><head><title>${title}</title>
    <style>
      body { font-family:'SF Mono','Fira Code',monospace; background:#16213e; color:#eee; padding:0; margin:0; display:flex; flex-direction:column; height:100vh; }
      .header { padding:6px 10px; background:#0f3460; border-bottom:1px solid #2a2a4a; flex-shrink:0; }
      .header-title { font-size:11px; font-weight:600; }
      .header-scope { font-size:9px; color:#888; }
      .filters { padding:5px 10px; background:#0f3460; border-bottom:1px solid #2a2a4a; display:flex; flex-wrap:wrap; gap:4px; flex-shrink:0; }
      .filter-btn {
        font-family:inherit; font-size:9px; padding:2px 7px; border-radius:3px; cursor:pointer;
        border:1px solid #2a2a4a; background:transparent; color:#555; transition:all 0.15s;
      }
      .filter-btn.on { border-color:currentColor; }
      .filter-btn[data-f="text"].on { color:#a78bfa; background:rgba(167,139,250,0.1); }
      .filter-btn[data-f="user"].on { color:#4ecca3; background:rgba(78,204,163,0.1); }
      .filter-btn[data-f="thinking"].on { color:#f0c040; background:rgba(240,192,64,0.1); }
      .filter-btn[data-f="tool"].on { color:#e07020; background:rgba(224,112,32,0.1); }
      .filter-btn[data-f="tool_result"].on { color:#e07020; background:rgba(224,112,32,0.1); }
      .filter-btn[data-f="system"].on { color:#888; background:rgba(136,136,136,0.1); }
      .filter-btn[data-f="state"].on { color:#4ecca3; background:rgba(78,204,163,0.1); }
      .filter-btn[data-f="result"].on { color:#888; background:rgba(136,136,136,0.1); }
      .filter-btn[data-f="log"].on { color:#888; background:rgba(136,136,136,0.1); }
      .messages { flex:1; overflow-y:auto; padding:10px; }
      .input-area { padding:6px 10px; border-top:1px solid #2a2a4a; display:flex; gap:5px; flex-shrink:0; }
      input { flex:1; background:#1a1a2e; border:1px solid #2a2a4a; border-radius:3px; padding:5px 8px; color:#eee; font-family:inherit; font-size:11px; outline:none; }
      input:focus { border-color:#4ecca3; }
      .send-btn { background:#4ecca3; color:#1a1a2e; border:none; padding:5px 10px; border-radius:3px; cursor:pointer; font-family:inherit; font-weight:600; font-size:11px; }
    </style></head><body>
    <div class="header">
      <div class="header-title">${title}</div>
      <div class="header-scope">${scope}</div>
    </div>
    <div class="filters">
      <button class="filter-btn on" data-f="text" onclick="toggle(this)">agent</button>
      <button class="filter-btn on" data-f="user" onclick="toggle(this)">human</button>
      <button class="filter-btn" data-f="thinking" onclick="toggle(this)">thinking</button>
      <button class="filter-btn" data-f="tool" onclick="toggle(this)">tools</button>
      <button class="filter-btn" data-f="tool_result" onclick="toggle(this)">results</button>
      <button class="filter-btn" data-f="system" onclick="toggle(this)">system</button>
      <button class="filter-btn" data-f="state" onclick="toggle(this)">state</button>
      <button class="filter-btn" data-f="result" onclick="toggle(this)">cost</button>
      <button class="filter-btn" data-f="log" onclick="toggle(this)">log</button>
    </div>
    <div class="messages" id="msgs">${entriesHtml}</div>
    <div class="input-area">
      <input id="inp" placeholder="Type a message..." onkeydown="if(event.key==='Enter'){send()}">
      <button class="send-btn" onclick="send()">Send</button>
    </div>
    <script>
      function toggle(btn) {
        btn.classList.toggle('on');
        var cls = btn.getAttribute('data-f');
        var show = btn.classList.contains('on');
        document.querySelectorAll('.entry.'+cls).forEach(function(el) {
          el.style.display = show ? '' : 'none';
        });
      }
      function send() {
        var inp = document.getElementById('inp');
        if (!inp.value.trim()) return;
        var msgs = document.getElementById('msgs');
        msgs.innerHTML += '<div class="entry user" data-cls="user" style="margin-bottom:8px"><div style="font-size:8px;font-weight:600;color:#4ecca3;text-transform:uppercase;letter-spacing:0.5px">human</div><div style="font-size:11px;line-height:1.4;color:#888;background:#1a1a2e;padding:6px 8px;border-radius:4px">'+inp.value+'</div></div>';
        inp.value = '';
        msgs.scrollTop = msgs.scrollHeight;
      }
      document.getElementById('msgs').scrollTop = document.getElementById('msgs').scrollHeight;
    <\/script></body></html>`);
}

function openChat(type, id, title, scope) {
  const history = (chatHistories[type] && chatHistories[type][id]) || [];
  openChatWindow(title, scope, history);
}

function newChatSession() {
  openChatWindow('New Session', 'Management Team', []);
}

function openNewChat(initialPrompt) {
  openChatWindow('Office Manager', 'Management Team', [], initialPrompt);
}

function openJobChat(jobId) {
  const j = data[jobId];
  const history = (chatHistories['job'] && chatHistories['job'][jobId]) || [];
  openChatWindow(j.name, `${j.projectName} · ${j.workgroupName} · ${j.phase}`, history);
}

function openTaskChat(taskId) {
  const t = data[taskId];
  const history = (chatHistories['task'] && chatHistories['task'][taskId]) || [];
  openChatWindow(t.name, `${t.projectName} · ${t.workgroupName} · ${t.assignee}`, history);
}
