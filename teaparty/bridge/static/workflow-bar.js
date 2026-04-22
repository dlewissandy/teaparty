// workflow-bar.js — shared workflow bar rendering for TeaParty.
//
// One implementation, used by every page that shows a CfA workflow bar.
// Pages import this script and call WorkflowBar.render(phaseIdx, large, needsInput).

(function(global) {

  // Standard CfA phase sequence for workflow bar rendering.
  // Four bars, one per state. Dialog/approval happens inside each phase's
  // skill (no separate gate states in the five-state model).
  var PHASES = ['INTENT', 'PLAN', 'EXECUTE', 'DONE'];

  // Map CfA states to workflow bar positions.
  var STATE_TO_PHASE_IDX = {
    'INTENT':    0,
    'PLAN':      1,
    'EXECUTE':   2,
    'DONE':      3,
    'WITHDRAWN': 3,
  };

  function phaseIndex(phase, state) {
    if (state && STATE_TO_PHASE_IDX[state] !== undefined) return STATE_TO_PHASE_IDX[state];
    var phaseMap = { 'intent': 0, 'planning': 1, 'execution': 2 };
    return phaseMap[phase] || 0;
  }

  function renderWorkflow(phaseIdx, large, needsInput) {
    var cls = large ? 'workflow-bar large' : 'workflow-bar';
    var html = '<div class="' + cls + '">';
    var isDone = phaseIdx >= PHASES.length - 1;
    for (var i = 0; i < PHASES.length; i++) {
      var ph = PHASES[i];
      var state;
      if (i < phaseIdx || (isDone && i === phaseIdx)) {
        state = 'complete';
      } else if (i === phaseIdx) {
        state = 'active';
      } else {
        state = '';
      }
      html += '<div class="wf-bar ' + state + '" title="' + ph + '"></div>';
      // Drop a pulsing red gate dot immediately after the active
      // phase's bar whenever an escalation is in flight for the
      // session.  INTENT phase + escalation → dot after INTENT;
      // PLAN phase + escalation → dot after PLAN; etc.  The dot
      // sits between bars (not inside one) so it reads as "the
      // phase is paused on human input" rather than part of the
      // bar itself.
      if (needsInput && i === phaseIdx && !isDone) {
        html += '<div class="wf-gate active" title="Escalation — human input required"></div>';
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
