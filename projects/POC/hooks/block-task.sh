#!/usr/bin/env bash
# PreToolUse hook: block Task/TaskOutput/TaskStop tools.
# These tools spawn isolated subprocesses that lack team context and hang indefinitely.
# Agents must use SendMessage to communicate with teammates instead.
jq -n '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: "Task tool is disabled. Use SendMessage to communicate with teammates, or Bash to run dispatch_cli.py for subteam dispatches."
  }
}'
