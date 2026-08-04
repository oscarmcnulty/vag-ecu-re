# CLAUDE.md — agent orientation

Reverse-engineering toolkit for VAG (Audi/VW) TriCore ECUs (Continental Simos, Bosch
MED17/MD1). Read `README.md` for layout and `docs/methodology.md` for the workflow.

## Hard rules
- **Never commit firmware-derived work.** Decompiled C, the `ghidra_proj/`, and firmware
  images are gitignored (`ecus/*/firmware/*`, `.env.sh`). Only *metadata* (addresses,
  names, scripts) is committed, and analysis is regenerated from it. Keep it that way.
- `analysis/symbols_merged.csv` holds **only confirmed** names (`source ∈ {verified,
  re-trace, fr-trace}`); everything else is `FUN_<addr>`. The machine-proposed `llm` names
  were removed (20% were actively wrong — `analysis/symbol_name_audit.md`); they live only in
  git history, not the tree. A name earns a place here by tracing (`re-trace`) or a
  Funktionsrahmen match (`fr-trace`) — don't reintroduce unverified guesses.

## Reproduce an ECU
`source .env.sh` then `ecus/<ecu>/reproduce.sh` (parameters in `ecus/<ecu>/ecu.conf`).
Needs Ghidra 12.1.2 + JDK 21 on PATH. A clean run ends `done.` with `analysis/coverage.log`.

## Ghidra setup in a fresh container (Claude Code web / CI)
- **JDK 21** is usually already installed:
  `JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")"`.
- **Ghidra 12.1.2** — general web egress is blocked, but GitHub *release-asset* downloads
  work (the direct `/releases/download/` URL 302-redirects to an allowed CDN; the API and
  the releases *listing* page are 403-gated, so you must use the exact asset URL):
  ```bash
  curl -L -o ~/opt/ghidra.zip \
    https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.2_build/ghidra_12.1.2_PUBLIC_20260605.zip
  echo "b62e81a0390618466c019c60d8c2f796ced2509c4c1aea4a37644a77272cf99d  ~/opt/ghidra.zip" | sha256sum -c -
  unzip -q ~/opt/ghidra.zip -d ~/opt      # -> ~/opt/ghidra_12.1.2_PUBLIC
  ```
  Newer version? Web-fetch `github.com/NationalSecurityAgency/ghidra/releases/latest` for the
  version + build date (that page renders; only the API/listing are gated), then build the
  URL as `Ghidra_<ver>_build/ghidra_<ver>_PUBLIC_<YYYYMMDD>.zip` and sha256-check it.
- Then write `.env.sh` (see `.env.sh.example`) and run `reproduce.sh`. `JAVA_TOOL_OPTIONS`
  is preset with the proxy CA truststore, so Ghidra's JVM trusts the egress proxy as-is —
  don't disable TLS or unset `HTTPS_PROXY`.
