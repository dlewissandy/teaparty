# Scheduled Task Removal Safety Checklist

## Before removing

- [ ] Confirm the task name matches exactly — there may be similarly named tasks
- [ ] Check if the task is currently running or mid-execution
- [ ] Consider `enabled: false` instead if the task may be re-enabled later

## What removal does

- Removes the `scheduled:` entry from the YAML file
- Does NOT delete the skill the task referenced — the skill remains available

## After removal

Report: "Removed scheduled task {name} from {file}. The skill {skill} is still available."
