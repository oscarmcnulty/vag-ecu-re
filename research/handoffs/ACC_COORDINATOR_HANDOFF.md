# Handoff: make the ACC longitudinal coordinator EXECUTE in emulation, then read its accel/decel/jerk limit logic

You are continuing a reverse-engineering effort on a **Continental Simos 8.5** engine ECU
(Audi Q5 3.0 TFSI, `8R0907551F`; Infineon **TC1796**, TriCore 1.3, little-endian, load base
`0x80000000`). Image: `ecus/simos85/firmware/8R0907551F_Original.bin` (2 MB OBD read; gitignored
symlink, present locally). Env: `source `.env.sh` (sets `GHIDRA_HOME`=Ghidra 12.1.2,
`JAVA_HOME`=JDK 21). Ghidra project `ecus/simos85/ghidra_proj/Simos85`, program
`8R0907551F_Original.bin`. Decompiles: `ecus/simos85/analysis/decompiles_r/<addr>.c` (3375 fns).

## The one goal
Openpilot longitudinal on this car needs the ECU's **input limit logic** on the ACC command:
positive-accel limit, deceleration limit, minimum-speed gate, and jerk (accel-rate) limit. Some are
known from calibration + on-car (see below); the rest live in a **longitudinal "coordinator"** that
is invisible to static analysis. **Your job: get that coordinator to actually RUN inside the working
TriCore emulator, then read what it does with the commanded accel — the clamp curve, the jerk/rate
limit, and the path to the TSK brake output.**

## What is already known (do NOT re-derive)
- **Decel limit = fixed −3.0 m/s²** (on-car confirmed: engine clamps outgoing `TSK_Verzoeg_Anf`
  (TSK_02/0x10C) at −3.000 and latches `TSK_04`(0x10E) `TSK_Status_GRA_ACC_02=3`). Cal source =
  curve at **0x8004dd90** (s16 axis) / **0x8004dda0** functional values
  `[-7.5,-3.25,-3.0,-2.0,-1.565,-1.25]` / **0x8004ddb0** identical L2 monitor copy. (Details:
  `ecus/simos85/maps/decel_limit_flow.md`.)
- **Min cruise speed = 384** (raw), cal `0x8007a26a` (= ACC cal struct `0x8007a204` + 0x66), used by
  `801e9b86` line ~298 (`speed DAT_d000d644 < cal[+0x66]`).
- **Jerk:** the CAN jerk signals `ACC_neg/pos_Sollbeschl_Grad` are NOT read by any analyzed code
  (UPDATE 18, exhaustive) — the jerk fault is an INTERNAL accel-rate limit, which is in the
  coordinator, not a CAN-signal read.
- **The ACC accel consumer chain (static):** accel mirror **`d000d606`** is read ONLY by
  **`801e9b86`** (`cruise_torque_pi_controller`, the ACC supervisor). 801e9b86 → `DAT_d000e2e8` →
  `801df7ac` (writes `DAT_d0007b8a`, the ACC torque limit) → **the non-analyzed coordinator** reads
  `d0007b8a` via a computed pointer (0 static readers) and produces the engine-torque + TSK output.
- **Why the coordinator is "non-analyzed":** it is function-pointer/interrupt scheduled and uses
  computed/cal-relative pointers for EVERYTHING (accel input, the `0x8004dd90` cal via a
  map-descriptor, the TSK output shadow, the `TSK_04=3` status). Confirmed dead ends:
  `FindRefsTo`/xref, call-graph edges, absolute-pointer scan into 0x8004dd90 (0 hits at any
  alias 0x80/0xa0), and — this session — a **runtime RAM scan after boot found neither
  `0x801e9b86`'s dispatch table nor a resolved pointer to `0x8004dd90`**, because the ACC subsystem
  never activates in the current emulation and cal access is register-transient.

## The working emulator (your main tool): `core/ghidra/EmulBoot.java`
Runs via Ghidra headless:
```
"$GHIDRA_HOME/support/analyzeHeadless" ecus/simos85/ghidra_proj Simos85 \
  -process 8R0907551F_Original.bin -noanalysis \
  -scriptPath core/ghidra -postScript EmulBoot.java <args...>
```
Args (positional): `<entryHex> [budget] [traceLoHex] [traceHiHex] [injStep] [invokeFnHex] [fullInit] [bridgeStep] [readWatch]`
- It BOOTS the firmware from `main()` (`0x80021140`) to steady state and materializes the Com context
  `c03fc37c=0x80030be0`. It runs 10M+ real instructions cleanly.
- **`arg6=1` (fullInit):** take the FULL-init boot path `initialize_system_801dea38` → **completes CAN
  init**, sets `DAT_d00072c4=0x80083270`. (Plain boot without arg6 takes the CAN-less
  `process_ecu_state` run-mode path.)
- **`arg7=<step>` (bridgeStep):** at that step, jump into RUN-mode (`process_ecu_state` 0x80021214,
  d4=0x1200) with RAM/CAN state INTACT — so you can get "CAN initialized AND run-mode scheduler
  running" simultaneously. Typical: `... 4000000 0 0 0 1 2500000` = full-init, bridge at 2.5M.
- **`arg4=<step>` (injStep):** at that step it currently pokes the ACC mirror region
  (`d000d5c0-d000d700`) with a pattern + `d000d604`/`d000d644`, and can inject a CAN frame. Adapt this
  to poke your test accel into `d000d606` and set ACC-active state.
- **`arg5=<fnHex>` (invokeFn):** at injStep, redirect PC to that function (a11=SENT sentinel; on
  return it either chains a built-in sequence or stops). Use it to directly invoke a function
  (e.g., `801e9b86`) with state pre-poked.
- **`arg8=1` (readWatch):** logs every load whose effective address lands in the watched region
  (currently `d000d5c0-d000d700`, the ACC mirrors) with the reader PC + function — use this to find
  who reads the accel.
Built-in machinery you can rely on (all in EmulBoot.java, read it): peripheral seed (SCU/PLL/ports
high), live STM timer, region-based busy-wait breaker + force-return, `calli`/`ji` ROM-stub (null/ROM
fn-ptrs), **RAM-code execution enabled for 0xd4000000** (vector/trampoline scratchpad), null-call
recovery, fn-return stubs (`800b4f80`/`80021de0`→0x190, `80028e76`→1), terminal reset-handler
ret-stubs (`801d7838`/`8002ed62`/`801d7902`), a RAM value-scan + context-walk dump at the end, and a
`DisasmF.java` helper that FORCE-disassembles data-marked regions (`DisasmF.java <startHex> <endHex>`;
plain `Disasm.java` only prints already-defined instructions). `FindRefsTo.java <addr...>` lists xrefs.

## The task, concretely
The ACC subsystem currently does NOT run: a read-watch on `d000d5c0-d000d700` over ~9M run-mode steps
logged **zero** reads — so `801e9b86` itself isn't being dispatched (it has no static callers; it is
called through a fn-pointer table that is only built when ACC init runs, which is gated). Get it to
run. Recommended ladder (try in order; each is a real result even if the next is blocked):

1. **Directly invoke `801e9b86`** (address known, fully decompiled) via `arg5=801e9b86` in bridged
   run-mode, with the ACC mirrors + cal + plausible ACC-active state pre-poked (see its decompile
   `decompiles_r/801e9b86.c` for the exact bytes it reads: `d000d606` accel, `d000d644` speed,
   `d5e4/e8/d4`, `d5c8/ca/cc/ce`, status bools `d656/7/8/60d/5c5`, cal struct `0x8007a204` via ptr
   `DAT_80090f94`; the shape-enable byte `0x7a247` is `1`). Add a CALL-TRACE + read/write watch and
   see (a) that it runs to completion, (b) every function it calls and every RAM address it writes.
   This fully characterizes the supervisor at runtime and may expose the fn-ptr it hands off to.
2. **Follow the chain to the coordinator.** After 801e9b86 runs, invoke `801df7ac`
   (`update_status_flags`) so `d0007b8a` is written, then hunt the coordinator: put a **write-watch on
   the TSK_02/TSK_04 output shadow RAM** and on `d0007b8a`, and a **read-watch on `d0007b8a`** and on
   the decel cal `0x8004dd90-0x8004ddbe`, while running the scheduler — whatever PC reads `d0007b8a`
   or the cal curve and writes the TSK shadow IS the coordinator. (The TSK side: `canmo_10c_TSK_02`
   @`0x801d2956` → `com_process_ipdu(3)`; `canmo_10e_TSK_04` @`0x8011e9ce` assembles from
   `*(d000d404)+8`, status byte at `*(d000d404)+0xf` — the coordinator writes that status=3.)
3. **Get ACC init to build the dispatch table.** Find the ACC subsystem init (the code that stores
   `801e9b86`/`801df7ac` and the coordinator into a fn-pointer or task table) and get it to run during
   the full-init boot (it is likely one of the init phases the current run skips or force-returns).
   Then re-run the RAM value-scan (already in EmulBoot: it scans c0/d0/d4 RAM for target pointers) for
   `0x801e9b86` — once the table exists, its SIBLING entries reveal the coordinator's address.
4. **Set the ACC-active state and let the scheduler dispatch it.** Locate the ACC main-switch / active
   flags (the state the supervisor and coordinator gate on) and poke them so the periodic scheduler
   runs the ACC chain naturally; poke a test accel into `d000d606` and watch the coordinator clamp it.
5. **Model the STM compare-match interrupt** (the handoff-ranked #1 for the whole effort): the
   coordinator may be IRQ-scheduled off the STM. `mtcr` is nop-patched so hardware vectoring can't
   fire; instead find the periodic-ISR entry and drive it. (The RX side has an analogous RAM-resident
   ISR at `0x801f8382` if you need a model to imitate.)

Once the coordinator's code address is known, `DisasmF.java` it and decompile it (or add it as a
function in Ghidra) to read the actual clamp/curve/jerk logic. Then **sweep the injected accel** in
`d000d606` from, say, −1.0 down past −4.0 m/s² and confirm the output shadow clamps at −3.0 and the
`TSK_04` status flips to 3 — that both verifies you've got the right code and lets you read the
positive-accel limit and the internal jerk/accel-rate limit that are still unknown.

## Success criteria
State, with evidence (a runtime trace and/or decompile lines):
- the **code address** of the longitudinal coordinator (force-disassembled), and
- how it converts the commanded accel into the TSK decel/torque output, specifically the
  **positive-accel limit**, the **−3.0 decel clamp mechanism** (fixed vs the 0x8004dd90 curve, and its
  selector index), and the **internal jerk/accel-rate limit** — the four limits openpilot needs.

## Ground rules
- Do NOT rely on live/on-car testing for THIS task — this is an emulation + static effort. (A separate
  track will do the on-car XCP/UDS runtime dump; don't block on it.)
- Be honest about negative results; append findings as a new UPDATE in `ecus/simos85/maps/RESULTS.md`
  and commit any new/edited scripts under `core/ghidra/`.
- Prefer reading the actual decompiles and the bin over guessing. The emulator is validated and
  reusable — extend it, don't restart. Read `EmulBoot.java` fully before modifying it.
- Background long runs and grep the log for markers (`RD-ACC`, `MW`, `RETURNED`, `left @`, `RAM[`,
  the coordinator PC). Runs of 6–12M steps take a couple minutes.

## Key files
- `core/ghidra/EmulBoot.java` (emulator), `core/ghidra/DisasmF.java`, `core/ghidra/FindRefsTo.java`.
- `ecus/simos85/maps/RESULTS.md` (UPDATES 18–32 = full evidence trail), `maps/decel_limit_flow.md`.
- `ecus/simos85/analysis/decompiles_r/801e9b86.c` (the ACC supervisor), `801df7ac.c`.
- `ecus/simos85/analysis/CHECKSUM_COUNTER_VALIDATION.md` (RX chain map, if you need the input side).
