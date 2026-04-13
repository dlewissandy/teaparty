// workflow-bar.js — shared workflow bar rendering for TeaParty.
//
// One implementation, used by every page that shows a CfA workflow bar.
// Pages import this script and call WorkflowBar.render(phaseIdx, large, needsInput).

(function(global) {

  // Standard CfA phase sequence for workflow bar rendering.
  // Bars: INTENT, PLAN, WORK, DONE. Gates (circles): INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT.
  var PHASES = ['INTENT', 'INTENT_ASSERT', 'PLAN', 'PLAN_ASSERT', 'WORK', 'WORK_ASSERT', 'DONE'];

  // Map CfA states to workflow bar positions.
  var STATE_TO_PHASE_IDX = {
    // Intent phase (bar 0)
    'IDEA': 0, 'PROPOSAL': 0, 'INTENT_QUESTION': 0, 'INTENT_ESCALATE': 0, 'INTENT_RESPONSE': 0,
    // Intent gate (circle 1)
    'INTENT_ASSERT': 1,
    // Planning phase (bar 2)
    'INTENT': 2, 'DRAFT': 2, 'PLANNING_QUESTION': 2, 'PLANNING_ESCALATE': 2, 'PLANNING_RESPONSE': 2,
    // Plan gate (circle 3)
    'PLAN_ASSERT': 3,
    // Execution phase (bar 4)
    'PLAN': 4, 'TASK': 4, 'TASK_IN_PROGRESS': 4, 'TASK_QUESTION': 4, 'TASK_ESCALATE': 4,
    'TASK_RESPONSE': 4, 'FAILED_TASK': 4, 'COMPLETED_TASK': 4, 'WORK_IN_PROGRESS': 4,
    'AWAITING_REPLIES': 4,
    // Work gate (circle 5)
    'WORK_ASSERT': 5,
    // Done (bar 6)
    'COMPLETED_WORK': 6, 'WITHDRAWN': 6,
  };

  function phaseIndex(phase, state) {
    // Prefer state-based lookup for precision.
    if (state && STATE_TO_PHASE_IDX[state] !== undefined) return STATE_TO_PHASE_IDX[state];
    // Fallback: map phase name to segment.
    var phaseMap = { 'intent': 0, 'planning': 2, 'execution': 4 };
    return phaseMap[phase] || 0;
  }

  function renderWorkflow(phaseIdx, large, needsInput) {
    // Find the gate index at or just after phaseIdx (the next ASSERT segment).
    var activeGate = -1;
    if (needsInput) {
      for (var g = phaseIdx; g < PHASES.length; g++) {
        if (PHASES[g].indexOf('ASSERT') !== -1) { activeGate = g; break; }
      }
    }
    var cls = large ? 'workflow-bar large' : 'workflow-bar';
    var html = '<div class="' + cls + '">';
    for (var i = 0; i < PHASES.length; i++) {
      var ph = PHASES[i];
      var isGate = ph.indexOf('ASSERT') !== -1;
      var isDone = phaseIdx >= PHASES.length - 1;
      var state;
      if (i === activeGate) {
        state = 'active';
      } else if (i < phaseIdx || (isDone && i === phaseIdx)) {
        state = 'complete';
      } else if (i === phaseIdx) {
        state = 'active';
      } else {
        state = '';
      }
      if (isGate) {
        html += '<div class="wf-gate ' + state + '" title="' + ph + '"></div>';
      } else {
        html += '<div class="wf-bar ' + state + '" title="' + ph + '"></div>';
      }
    }
    html += '</div>';
    return html;
  }

  global.WorkflowBar = {
    PHASES: PHASES,
    STATE_TO_PHASE_IDX: STATE_TO_PHASE_IDX,
    phaseIndex: phaseIndex,
    render: renderWorkflow,
  };

  // Backward-compatible globals for pages that reference PHASES/renderWorkflow directly.
  global.PHASES = PHASES;
  global.STATE_TO_PHASE_IDX = STATE_TO_PHASE_IDX;
  global.phaseIndex = phaseIndex;
  global.renderWorkflow = renderWorkflow;

})(window);
