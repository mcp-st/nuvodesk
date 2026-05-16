#!/usr/bin/env bash
# Deploy NuvoDesk → GitHub + VMSLAVE + VPS
# Wrapper sobre ~/deploy-all.sh
set -e
exec bash "$(dirname "$0")/../../deploy-all.sh" nuvodesk "$@"
