// ── Render: Workgroup ──────────────────────────────────

function renderWorkgroup(id) {
  const d = data[id];
  document.getElementById('dashboard').innerHTML = `
    <div class="dashboard-title">${d.name} Workgroup</div>
    <div class="dashboard-description">${d.description}</div>
    <div class="dashboard-subtitle">${d.projectName} · ${d.lead} · ${d.agents.length} agents · ${d.activeTasks.length} active tasks</div>

    <div class="stats-bar">
      <div class="stat"><div class="stat-value stat-green">${d.stats.jobsCompleted}</div><div class="stat-label">Jobs Done</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.tasksCompleted}</div><div class="stat-label">Tasks Done</div></div>
      <div class="stat"><div class="stat-value">${d.stats.activeJobs}</div><div class="stat-label">Active</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.oneShots}</div><div class="stat-label">One-shots</div></div>
      <div class="stat"><div class="stat-value stat-yellow">${d.stats.backtracks}</div><div class="stat-label">Backtracks</div></div>
      <div class="stat"><div class="stat-value stat-red">${d.stats.withdrawals}</div><div class="stat-label">Withdrawals</div></div>
      <div class="stat"><div class="stat-value stat-purple">${d.stats.escalations}</div><div class="stat-label">Escalations</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.proxyAccuracy}%</div><div class="stat-label">Proxy Acc.</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.tokensUsed}</div><div class="stat-label">Tokens</div></div>
    </div>

    <div class="sections">

      <div class="section">
        <div class="section-header">Escalations</div>
        <div class="section-scroll">
        ${d.escalations.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No pending escalations</div>' : ''}
        ${d.escalations.map(e => `
          <div class="item" onclick="openJobChat('${e.jobId}')">
            <div class="escalation-pulse"></div>
            <div class="item-body">
              <div class="item-title">${e.job} · ${e.phase}</div>
              <div class="item-meta">${e.summary}</div>
            </div>
            <span style="color:var(--text-dim);font-size:9px">${e.time}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Sessions
          <button class="action-btn" onclick="openNewChat('I would like to start a new session for the ${d.name} workgroup')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.sessions.map(s => `
          <div class="item" onclick="openChat('office-manager','${s.id}','${s.title}','${d.name} Workgroup · ${d.projectName}')">
            <div class="heartbeat heartbeat-${s.heartbeat}" title="${s.heartbeat}: ${s.lastActivity}"></div>
            <div class="item-body">
              <div class="item-title">${s.title}</div>
              <div class="item-meta">${s.date} · ${s.messages} msgs · ${s.lastActivity}</div>
            </div>
          </div>
        `).join('')}
        ${d.sessions.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No sessions</div>' : ''}
        </div>
      </div>

      <div class="section">
        <div class="section-header">Active Tasks</div>
        <div class="section-scroll">
        ${d.activeTasks.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No active tasks</div>' : ''}
        ${d.activeTasks.map(t => `
          <div class="item" onclick="${data[t.id] ? "navigate('task','"+t.id+"')" : "navigate('job','"+t.jobId+"')"}">
            <div class="heartbeat heartbeat-${t.heartbeat}" title="${t.heartbeat}"></div>
            <div class="item-body">
              <div class="item-title">${t.name}</div>
              <div class="item-meta">${t.job} · ${t.assignee}</div>
            </div>
            <span class="item-badge badge-${t.status==='done'?'done':t.status==='active'?'active':'idle'}">${t.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Agents
          <button class="action-btn" onclick="openNewChat('I would like to add a new agent to the ${d.name} workgroup')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.agents.map(a => `
          <div class="item" onclick="showWgAgent('${id}','${a.id}')">
            <div class="item-icon icon-member">${a.role === 'Team Lead' ? '&#9733;' : '&#9672;'}</div>
            <div class="item-body">
              <div class="item-title">${a.name}</div>
              <div class="item-meta">${a.role} · ${a.model}</div>
            </div>
            <span class="item-badge badge-${a.status}">${a.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Skills
          <button class="action-btn" onclick="openNewChat('I would like to create a new skill for the ${d.name} workgroup')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.skills.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No workgroup-scoped skills</div>' : ''}
        ${d.skills.map(s => `
          <div class="item" onclick="showSkill('${s.name}','${s.path}')">
            <div class="item-icon icon-skill">&#9881;</div>
            <div class="item-body">
              <div class="item-title">${s.name}</div>
              <div class="item-meta">${s.files.length} files</div>
            </div>
          </div>
        `).join('')}
        </div>
      </div>

    </div>
  `;
}
