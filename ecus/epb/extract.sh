#!/usr/bin/env bash
# Regenerate the raw flash blocks from the encrypted FRF (deterministic; blocks are gitignored).
#   FRF -> (VW_Flash recursive-XOR decrypt) -> .odx -> (core/odx/odx_extract.py) -> DB_*.bin
# Needs bri3d/VW_Flash checked out (default ~/tools/VW_Flash) for the FRF key + decryptor.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
FRF="${1:-$HERE/firmware/FL_8K0907801N_0005.frf}"
VWFLASH="${VWFLASH:-$HOME/tools/VW_Flash}"
[ -f "$FRF" ] || { echo "missing FRF: $FRF (gitignored; supply locally)"; exit 1; }
( cd "$VWFLASH" && python3 -m frf.decryptfrf --file "$FRF" --outdir "$HERE/firmware" )
ODX="$HERE/firmware/$(basename "${FRF%.frf}").odx"
python3 "$ROOT/core/odx/odx_extract.py" "$ODX" -o "$HERE/firmware"
echo "extracted:"; ls -l "$HERE"/firmware/DB_*.bin
