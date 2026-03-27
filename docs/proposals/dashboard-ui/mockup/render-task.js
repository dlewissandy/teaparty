// ── Render: Task ──────────────────────────────────

function renderTask(id) {
  const d = data[id];
  const doneCount = d.todoList.filter(t => t.done).length;
  const totalCount = d.todoList.length;

  document.getElementById('dashboard').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="dashboard-title">${d.name}</div>
      <div style="display:flex;gap:5px">
        <button class="job-action-btn" onclick="alert('open ${d.worktree} in Finder')">&#128193; Finder</button>
        <button class="job-action-btn" onclick="alert('code ${d.worktree}')">&#9998; VS Code</button>
      </div>
    </div>
    <div class="dashboard-description">${d.summary}</div>
    <div class="dashboard-subtitle">
      ${d.assignee} · ${d.status}
      · <a style="color:var(--green);cursor:pointer;text-decoration:none" href="workgroup.html?id=${d.workgroup}">${d.workgroupName} workgroup</a>
    </div>

    <div style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-dim);margin-bottom:3px">
        <span>Progress</span>
        <span>${doneCount}/${totalCount}</span>
      </div>
      <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden">
        <div style="height:100%;width:${Math.round(doneCount/totalCount*100)}%;background:var(--green);border-radius:2px"></div>
      </div>
    </div>

    <div class="stats-bar">
      <div class="stat"><div class="stat-value stat-dim">${d.stats.tokensUsed}</div><div class="stat-label">Tokens</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.elapsed}</div><div class="stat-label">Elapsed</div></div>
    </div>

    <div class="job-actions">
      <button class="job-action-btn" onclick="openTaskChat('${id}')">&#9993; Chat${d.escalations.length ? ' (escalation pending)' : ''}</button>
      <button class="job-action-btn" style="border-color:var(--red);color:var(--red)" onclick="alert('WITHDRAW this task')">&#9632; Withdraw</button>
    </div>

    <div class="sections">
      <div class="section">
        <div class="section-header">Escalations</div>
        <div class="section-scroll">
        ${d.escalations.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No pending escalations</div>' : ''}
        ${d.escalations.map(e => `
          <div class="item" onclick="openTaskChat('${id}')">
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
        <div class="section-header">Todo List</div>
        <div class="section-scroll">
        ${d.todoList.map(t => `
          <div class="item" style="cursor:default">
            <div class="item-icon icon-task">${t.done?'&#10003;':'&#9675;'}</div>
            <div class="item-body">
              <div class="item-title" style="${t.done?'text-decoration:line-through;opacity:0.5':''}">${t.name}</div>
            </div>
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
