#!/usr/bin/env bash
# Rebuild the labeled Audi B8/8R EPS rack (8R0909144F) Ghidra project + decompiles.
set -euo pipefail
export ECU_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$ECU_DIR/../../core/pipeline/reproduce.sh"
