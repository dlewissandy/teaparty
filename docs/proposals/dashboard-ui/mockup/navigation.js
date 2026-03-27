// ── Navigation ──────────────────────────────────

function navigate(view, id) {
  const pageMap = {
    management: 'management.html',
    project: 'project.html',
    workgroup: 'workgroup.html',
    job: 'job.html',
    task: 'task.html',
  };
  const url = pageMap[view];
  if (!url) return;
  if (id) {
    window.location.href = url + '?id=' + encodeURIComponent(id);
  } else {
    window.location.href = url;
  }
}

function getPageId() {
  const params = new URLSearchParams(window.location.search);
  return params.get('id');
}

// ── Breadcrumb ──────────────────────────────────

function renderBreadcrumb(view, id) {
  const bc = document.getElementById('breadcrumb');
  let html = '<a href="management.html">TeaParty</a>';
  if (view === 'project') {
    html += ` <span>/</span> <a href="project.html?id=${id}">${data[id].name}</a>`;
  } else if (view === 'workgroup') {
    const w = data[id];
    html += ` <span>/</span> <a href="project.html?id=${w.project}">${w.projectName}</a>`;
    html += ` <span>/</span> <a href="workgroup.html?id=${id}">${w.name}</a>`;
  } else if (view === 'job') {
    const j = data[id];
    html += ` <span>/</span> <a href="project.html?id=${j.project}">${j.projectName}</a>`;
    html += ` <span>/</span> <a href="workgroup.html?id=${j.workgroup}">${j.workgroupName}</a>`;
    html += ` <span>/</span> <a href="job.html?id=${id}">${j.name}</a>`;
  } else if (view === 'task') {
    const t = data[id];
    html += ` <span>/</span> <a href="project.html?id=${t.project}">${t.projectName}</a>`;
    html += ` <span>/</span> <a href="job.html?id=${t.jobId}">${t.jobName}</a>`;
    html += ` <span>/</span> <a href="task.html?id=${id}">${t.name}</a>`;
  }
  bc.innerHTML = html;
}

// ── Shared page shell ──────────────────────────────────
// Each page calls initPage(view) on DOMContentLoaded.

function initPage(view) {
  const id = getPageId();
  renderBreadcrumb(view, id);
  if (view === 'management') renderManagement();
  else if (view === 'project') renderProject(id);
  else if (view === 'workgroup') renderWorkgroup(id);
  else if (view === 'job') renderJob(id);
  else if (view === 'task') renderTask(id);
}
