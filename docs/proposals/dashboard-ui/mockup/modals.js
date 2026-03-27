// ── Modals ──────────────────────────────

function showModal(title, bodyHtml) {
  document.getElementById('modal-title-text').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal(e) {
  if (e && e.target && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.remove('open');
}

function showAgent(id) {
  const a = data.management.agents.find(x => x.id === id);
  showAgentDetail(a);
}

function showAgentDetail(a) {
  const toolList = a.tools.map(t => `  ${t}`).join('\n');
  const denyList = a.disallowedTools.length ? a.disallowedTools.map(t => `  ${t}`).join('\n') : '  (none)';
  const mcpLines = a.mcpServers.length
    ? a.mcpServers.map(s => `  ${s}`).join('\n') + '\n\nMCP Tools:\n' + a.mcpTools.map(t => `  mcp__${a.mcpServers[0]}__${t}`).join('\n')
    : '  (none)';
  const hookLines = a.hooks.length
    ? a.hooks.map(h => `  ${h.event} [${h.type}]\n    ${h.detail}`).join('\n')
    : '  (none)';

  showModal(a.name, `
    <pre style="white-space:pre-wrap;font-size:10px;line-height:1.6;color:var(--text);background:var(--bg);padding:12px;border-radius:4px;margin:0">Agent:  ${a.name}
Role:   ${a.role}
File:   ${a.agentFile}
Status: ${a.status}

<span style="color:var(--green)">── Model ──────────────────────────</span>
Model:           ${a.model}
Max turns:       ${a.maxTurns}
Permission mode: ${a.permissionMode}

<span style="color:var(--green)">── Tools ─────────────────────────</span>
Allowed:
${toolList}

Disallowed:
${denyList}

<span style="color:var(--green)">── MCP Servers ────────────────────</span>
${mcpLines}

<span style="color:var(--green)">── Hooks ─────────────────────────</span>
${hookLines}

<span style="color:var(--green)">── System Prompt ──────────────────</span>
${a.prompt}</pre>
    <div class="modal-actions">
      <div style="flex:1;font-size:9px;color:var(--text-dim)">Read-only. To modify this agent, use the office manager chat.</div>
      <button class="modal-btn" onclick="closeModal()">Close</button>
    </div>
  `);
}

function showProjectAgent(projectId, agentId) {
  const a = data[projectId].agents.find(x => x.id === agentId);
  showAgentDetail(a);
}

function showWgAgent(wgId, agentId) {
  const a = data[wgId].agents.find(x => x.id === agentId);
  showAgentDetail(a);
}

function showSkill(name, path) {
  showModal(name, `
    <div style="color:var(--text);margin-bottom:12px;font-size:11px">${path}</div>
    <div class="modal-actions">
      <button class="modal-btn" onclick="alert('open ${path} in Finder');closeModal()">&#128193; Finder</button>
      <button class="modal-btn modal-btn-primary" onclick="alert('code ${path}');closeModal()">&#9998; VS Code</button>
      <button class="modal-btn" onclick="closeModal()">Cancel</button>
    </div>
  `);
}

function showCron(id, name, schedule, desc, lastRun, status) {
  showModal(name, `
    <table class="config-table">
      <tr><td>Schedule</td><td><code>${schedule}</code></td></tr>
      <tr><td>Description</td><td>${desc}</td></tr>
      <tr><td>Last run</td><td>${lastRun}</td></tr>
      <tr><td>Status</td><td><span class="item-badge badge-${status}">${status}</span></td></tr>
    </table>
    <div class="modal-actions">
      <button class="modal-btn modal-btn-primary" onclick="alert('Run now: ${name}')">&#9654; Run Now</button>
      <button class="modal-btn modal-btn-warn" onclick="alert('${status==='active'?'Pause':'Resume'}: ${name}')">${status==='active'?'&#9208; Pause':'&#9654; Resume'}</button>
    </div>
  `);
}

function showHook(h) {
  const handlersHtml = h.handlers.map(handler => {
    let details = '';
    if (handler.type === 'command') details = `<pre>${handler.command}</pre>`;
    else if (handler.type === 'agent') details = `<pre>prompt: ${handler.prompt}\nmodel: ${handler.model||'default'}</pre>`;
    else if (handler.type === 'http') details = `<pre>url: ${handler.url}</pre>`;
    else if (handler.type === 'prompt') details = `<pre>prompt: ${handler.prompt}</pre>`;
    return `<div style="margin-top:6px"><span class="hook-handler-type">${handler.type}</span>${details}</div>`;
  }).join('');
  showModal(`Hook: ${h.event}`, `
    <table class="config-table">
      <tr><td>Event</td><td><code>${h.event}</code></td></tr>
      <tr><td>Matcher</td><td><code>${h.matcher || '(all)'}</code></td></tr>
    </table>
    <div class="label">Handlers</div>
    ${handlersHtml}
  `);
}
