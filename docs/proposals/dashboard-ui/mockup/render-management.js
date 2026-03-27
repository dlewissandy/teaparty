// ── Render: Management ──────────────────────────────────

function renderManagement() {
  const d = data.management;
  document.getElementById('dashboard').innerHTML = `
    <div class="dashboard-title">${d.name}</div>
    <div class="dashboard-description">${d.description}</div>
    <div class="dashboard-subtitle">${d.agents.length} agents · ${d.projects.length} projects · ${d.escalations.length} escalations</div>

    <div class="stats-bar">
      <div class="stat"><div class="stat-value stat-green">${d.stats.jobsCompleted}</div><div class="stat-label">Jobs Done</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.tasksCompleted}</div><div class="stat-label">Tasks Done</div></div>
      <div class="stat"><div class="stat-value">${d.stats.activeJobs}</div><div class="stat-label">Active</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.oneShots}</div><div class="stat-label">One-shots</div></div>
      <div class="stat"><div class="stat-value stat-yellow">${d.stats.backtracks}</div><div class="stat-label">Backtracks</div></div>
      <div class="stat"><div class="stat-value stat-red">${d.stats.withdrawals}</div><div class="stat-label">Withdrawals</div></div>
      <div class="stat"><div class="stat-value stat-purple">${d.stats.escalations}</div><div class="stat-label">Escalations</div></div>
      <div class="stat"><div class="stat-value">${d.stats.interventions}</div><div class="stat-label">Interventions</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.proxyAccuracy}%</div><div class="stat-label">Proxy Acc.</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.tokensUsed}</div><div class="stat-label">Tokens</div></div>
      <div class="stat"><div class="stat-value stat-green">${d.stats.skillsLearned}</div><div class="stat-label">Skills Learned</div></div>
      <div class="stat"><div class="stat-value stat-dim">${d.stats.uptime}</div><div class="stat-label">Uptime</div></div>
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
              <div class="item-title">${e.project} · ${e.phase}</div>
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
          <button class="action-btn" onclick="newChatSession()">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.sessions.map(s => `
          <div class="item" onclick="openChat('office-manager','${s.id}','${s.title}','Management Team')">
            <div class="heartbeat heartbeat-${s.heartbeat}" title="${s.heartbeat}: ${s.lastActivity}"></div>
            <div class="item-body">
              <div class="item-title">${s.title}</div>
              <div class="item-meta">${s.date} · ${s.messages} msgs · ${s.lastActivity}</div>
            </div>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Projects
          <button class="action-btn" onclick="openNewChat('I would like to create a new project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.projects.map(p => `
          <div class="item" onclick="navigate('project','${p.id}')">
            <div class="item-icon icon-project">&#9654;</div>
            <div class="item-body">
              <div class="item-title">${p.name}</div>
              <div class="item-meta" style="color:var(--text-dim);font-size:9px;margin-bottom:2px">${p.description}</div>
              <div class="item-meta">${p.lead} · ${p.jobs} jobs${p.escalations ? ' · ' + p.escalations + ' escalations' : ''}</div>
            </div>
            <span class="item-badge badge-${p.status}">${p.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Workgroups
          <button class="action-btn" onclick="openNewChat('I would like to create a new shared workgroup')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.workgroups.map(w => `
          <div class="item" onclick="navigate('workgroup','${w.id}')">
            <div class="item-icon icon-workgroup">&#9670;</div>
            <div class="item-body">
              <div class="item-title">${w.name}</div>
              <div class="item-meta" style="color:var(--text-dim);font-size:9px;margin-bottom:2px">${w.description}</div>
              <div class="item-meta">${w.lead} · ${w.agents} agents</div>
            </div>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">Humans</div>
        <div class="section-scroll">
        ${d.humans.map(h => {
          const roleColors = { decider: 'var(--accent-blue)', advisor: 'var(--green)', informed: 'var(--text-dim)' };
          const roleColor = roleColors[h.role] || 'var(--text-dim)';
          return `
          <div class="item" onclick="openNewChat('I want to talk with ${h.name}')">
            <div class="item-icon icon-member">&#9786;</div>
            <div class="item-body">
              <div class="item-title">${h.name}${h.self ? ' <span class="item-badge" style="background:var(--accent-blue);color:#fff;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px">you</span>' : ''}</div>
            </div>
            <span style="font-size:9px;padding:2px 6px;border-radius:3px;border:1px solid ${roleColor};color:${roleColor};white-space:nowrap">${h.role}</span>
          </div>
        `;}).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Agents
          <button class="action-btn" onclick="openNewChat('I would like to create a new agent')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.agents.map(a => `
          <div class="item" onclick="showAgent('${a.id}')">
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
          <button class="action-btn" onclick="openNewChat('I would like to create a new skill')">+ New</button>
        </div>
        <div class="section-scroll">
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

      <div class="section">
        <div class="section-header">
          Cron Jobs
          <button class="action-btn" onclick="openNewChat('I would like to create a new cron job')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.crons.map(c => `
          <div class="item" onclick="showCron('${c.id}','${c.name}','${c.schedule}','${c.description}','${c.lastRun}','${c.status}')">
            <div class="item-icon icon-cron">&#9200;</div>
            <div class="item-body">
              <div class="item-title">${c.name}</div>
              <div class="item-meta">${c.schedule} · last: ${c.lastRun}</div>
            </div>
            <span class="item-badge badge-${c.status}">${c.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Hooks
          <button class="action-btn" onclick="openNewChat('I would like to create a new hook')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.hooks.map(h => `
          <div class="item" onclick="showHook(${JSON.stringify(h).replace(/"/g,'&quot;')})">
            <div class="item-icon icon-hook">&#9889;</div>
            <div class="item-body">
              <div class="item-title">${h.event}${h.matcher ? ` [${h.matcher}]` : ''}</div>
              <div class="item-meta">${h.handlers.map(x=>x.type).join(', ')}</div>
            </div>
          </div>
        `).join('')}
        </div>
      </div>

    </div>
  `;
}
