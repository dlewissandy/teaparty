#!/usr/bin/env bash
# Proxy — forwards to the POC project's run.sh
exec "$(dirname "${BASH_SOURCE[0]}")/projects/POC/run.sh" "$@"
