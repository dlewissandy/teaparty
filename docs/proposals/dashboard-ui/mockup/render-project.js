// ── Render: Project ──────────────────────────────────

function renderProject(id) {
  const d = data[id];
  document.getElementById('dashboard').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="dashboard-title">${d.name}</div>
      <div style="display:flex;gap:5px">
        <button class="job-action-btn" onclick="alert('open ${d.path} in Finder')">&#128193; Finder</button>
        <button class="job-action-btn" onclick="alert('code ${d.path}')">&#9998; VS Code</button>
      </div>
    </div>
    <div class="dashboard-description">${d.description}</div>
    <div class="dashboard-subtitle">${d.agents.length} agents · ${d.workgroups.length} workgroups · ${d.jobs.length} jobs</div>
    ${d.decider ? `<div class="dashboard-subtitle" style="margin-top:2px">Decider: <span style="color:var(--text-dim);cursor:pointer" onclick="openNewChat('I want to talk with ${d.decider}')">${d.decider}</span></div>` : ''}

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
              <div class="item-title">${e.workgroup} · ${e.phase}</div>
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
          <button class="action-btn" onclick="openNewChat('I would like to start a new session for the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.sessions.map(s => `
          <div class="item" onclick="openChat('office-manager','${s.id}','${s.title}','${d.name}')">
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
        <div class="section-header">
          Jobs
          <button class="action-btn" onclick="openNewChat('I would like to create a new job in the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.jobs.map(j => `
          <div class="item" onclick="navigate('job','${j.id}')">
            <div class="item-icon icon-job">&#9654;</div>
            <div class="item-body">
              <div class="item-title">${j.name}</div>
              <div class="item-meta">${j.workgroup} · ${j.phase}</div>
              <div class="workflow-bar">
                ${j.phases.map((p,i) => `<div class="workflow-step ${i<j.phaseIdx?'complete':i===j.phaseIdx?'active':''}"></div>`).join('')}
              </div>
            </div>
            <span class="item-badge badge-${j.status}">${j.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Workgroups
          <button class="action-btn" onclick="openNewChat('I would like to create a new workgroup in the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.workgroups.map(w => `
          <div class="item" onclick="navigate('workgroup','${w.id}')">
            <div class="item-icon icon-workgroup">&#9670;</div>
            <div class="item-body">
              <div class="item-title">${w.name}${w.shared ? ' <span style="font-size:8px;background:rgba(78,204,163,0.15);color:var(--green);border-radius:3px;padding:1px 5px;vertical-align:middle">shared</span>' : ''}</div>
              <div class="item-meta" style="color:var(--text-dim);font-size:9px;margin-bottom:2px">${w.description}</div>
              <div class="item-meta">${w.lead} · ${w.agents} agents</div>
            </div>
            <span class="item-badge badge-${w.status}">${w.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Agents <span style="font-size:9px;color:var(--text-dim);font-weight:400">(direct team members)</span>
          <button class="action-btn" onclick="openNewChat('I would like to add a new agent to the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.agents.map(a => `
          <div class="item" onclick="showProjectAgent('${id}','${a.id}')">
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
          <button class="action-btn" onclick="openNewChat('I would like to create a new skill for the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.skills.length === 0 ? '<div style="padding:12px 10px;color:var(--text-dim);font-size:10px;text-align:center">No project-scoped skills</div>' : ''}
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
          <button class="action-btn" onclick="openNewChat('I would like to create a new cron job for the ${d.name} project')">+ New</button>
        </div>
        <div class="section-scroll">
        ${d.crons.map(c => `
          <div class="item" onclick="showCron('${c.id}','${c.name}','${c.schedule}','${c.description}','${c.lastRun}','${c.status}')">
            <div class="item-icon icon-cron">&#9200;</div>
            <div class="item-body">
              <div class="item-title">${c.name}</div>
              <div class="item-meta">${c.schedule}</div>
            </div>
            <span class="item-badge badge-${c.status}">${c.status}</span>
          </div>
        `).join('')}
        </div>
      </div>

      <div class="section">
        <div class="section-header">
          Hooks
          <button class="action-btn" onclick="openNewChat('I would like to create a new hook for the ${d.name} project')">+ New</button>
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
