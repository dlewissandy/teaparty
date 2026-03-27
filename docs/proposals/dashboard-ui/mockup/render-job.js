// ── Render: Job ──────────────────────────────────

function renderJob(id) {
  const d = data[id];
  document.getElementById('dashboard').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="dashboard-title">${d.name}</div>
      <div style="display:flex;gap:5px">
        <button class="job-action-btn" onclick="alert('open ${d.worktree} in Finder')">&#128193; Finder</button>
        <button class="job-action-btn" onclick="alert('code ${d.worktree}')">&#9998; VS Code</button>
      </div>
    </div>
    <div class="dashboard-description">${d.summary}</div>
    <div class="dashboard-subtitle">${d.projectName} · ${d.workgroupName} · Phase: ${d.phase}</div>

    <div class="workflow-bar" style="margin-bottom:12px;height:4px">
      ${d.phases.map((p,i) => `<div class="workflow-step ${i<d.phaseIdx?'complete':i===d.phaseIdx?'active':''}" title="${p}" style="border-radius:2px"></div>`).join('')}
    </div>
    <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--text-dim);margin-bottom:12px;margin-top:-8px">
      ${d.phases.map(p => `<span>${p}</span>`).join('')}
    </div>

    <div class="stats-bar">
      <div class="stat"><div class="stat-value stat-green">${d.stats.tasksCompleted}/${d.stats.tasksTotal}</div><div class="stat-label">Tasks</div></div>
      <div class="stat"><div class="stat-value stat-yellow">${d.stats.backtracks}</div><div class="stat-label">Backtracks</div></div>
      <div class="stat"><div class="stat-value stat-purple">${d.stats.escalations}</div><div class="stat-label">Escalations</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.tokensUsed}</div><div class="stat-label">Tokens</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.elapsed}</div><div class="stat-label">Elapsed</div></div>
    </div>

    <div class="job-actions">
      <button class="job-action-btn" onclick="openJobChat('${id}')">&#9993; Chat${d.escalations.length ? ' (escalation pending)' : ''}</button>
      <button class="job-action-btn" style="border-color:var(--red);color:var(--red)" onclick="alert('WITHDRAW')">&#9632; Withdraw</button>
    </div>

    <div class="sections">
      <div class="section">
        <div class="section-header">Escalations</div>
        <div class="section-scroll">
        ${d.escalations.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No pending escalations</div>' : ''}
        ${d.escalations.map(e => `
          <div class="item" onclick="openJobChat('${id}')">
            <div class="escalation-pulse"></div>
            <div class="item-body">
              <div class="item-title">${e.phase}</div>
              <div class="item-meta">${e.summary}</div>
            </div>
            <span style="color:var(--text-dim);font-size:9px">${e.time}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">Artifacts</div>
        <div class="section-scroll">
        ${d.artifacts.map(a => a.exists ? `
          <div class="item" onclick="alert('Open ${d.worktree}/${a.name} in editor')">
            <div class="item-icon" style="background:rgba(78,204,163,0.15);color:var(--green)">&#128196;</div>
            <div class="item-body">
              <div class="item-title">${a.name}</div>
            </div>
          </div>
        ` : `
          <div class="item" style="opacity:0.4;cursor:default">
            <div class="item-icon" style="background:rgba(136,136,136,0.1);color:var(--text-dim)">&#128196;</div>
            <div class="item-body">
              <div class="item-title">${a.name}</div>
              <div class="item-meta">not yet created</div>
            </div>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">Tasks</div>
        <div class="section-scroll">
        ${d.tasks.map(t => `
          <div class="item" ${data[t.id] ? `onclick="navigate('task','${t.id}')" style="cursor:pointer"` : ''}>
            <div class="heartbeat heartbeat-${t.heartbeat}" title="${t.heartbeat}"></div>
            <div class="item-body">
              <div class="item-title">${t.name}</div>
              <div class="item-meta">${t.assignee}</div>
            </div>
            <span class="item-badge badge-${t.status==='done'?'done':t.status==='active'?'active':'idle'}">${t.status}</span>
          </div>
        `).join('')}
        </div>
      </div>
    </div>

    <div style="margin-top:10px;padding:8px 10px;background:var(--surface);border:1px solid var(--border);border-radius:4px">
      <span style="font-size:9px;color:var(--text-dim);text-transform:uppercase">Worktree</span>
      <code style="font-size:10px;color:var(--green);margin-left:6px">${d.worktree}</code>
    </div>
  `;
}
