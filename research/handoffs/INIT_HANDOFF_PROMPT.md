# Handoff: recover the Simos8.5 Com runtime binding so ACC_01 → TSK is fully traceable

You are continuing a reverse-engineering effort on a **Continental Simos 8.5** engine ECU
(Audi Q5 3.0 TFSI, `8R0907551F`). MCU: **Infineon TC1796, TriCore 1.3, little-endian, load base
`0x80000000`**. The image is a 2 MB OBD read: `ecus/simos85/firmware/8R0907551F_Original.bin`
(gitignored symlink; present locally). Everything below is grounded in prior work — **read
`ecus/simos85/maps/RESULTS.md` UPDATES 18–25 first**; they contain the full evidence trail and
every address referenced here.

## The mission (one sentence)

Recover the **runtime signal→RAM-address binding** that the firmware's generated AUTOSAR-style Com
stack builds at boot, so we can confirm the complete data path
**ACC_01 (CAN 0x109) input signals → RAM mirrors → longitudinal/ACC coordinator → TSK_02 (CAN 0x10C)
brake outputs** (`TSK_Verzoeg_Anf` decel + `TSK_Radbremsmom` brake torque). Without this binding we
cannot verify how `ACC_Sollbeschleunigung`, the jerk gradients (`ACC_neg/pos_Sollbeschl_Grad`), and
`ACC_Dynamik` are (or aren't) consumed and converted into the ESP brake request.

Concretely, produce **either**:
- (A) the map `{ACC_01 signal → bit position → RAM mirror address → scaling}` for message 0x109, **and**
  the symmetric map for the TSK_02 (0x10C) output signals; **or**
- (B) the located, decompiled **longitudinal coordinator** function(s) that read the ACC mirrors and
  write the TSK_02 source RAM — i.e. the actual accel→decel/torque transfer code.

## What is already established (don't re-derive)

**Static structure (UPDATE 19–20):**
- ACC_01 (0x109) RX decodes into RAM mirrors in `d000d5xx`/`d000d6xx`. Known: `d000d606` = ACC accel
  mirror. Only app consumer of these mirrors is **`801e9b86`** (the ACC supervisor/limiter, cal-
  disabled in this image), plus a few others (`801f0204`, `801e6d54`, `801eecfc`). **No application
  code reads a jerk or `ACC_Dynamik` mirror** — exhaustively confirmed (UPDATE 18).
- The RX binding is **flash-resident**: registry table `0x801f51a0` (66 entries, 16-byte records
  `{u32 signal_id, u32 type=2, u32 dest_RAM_addr, u32 0}`) maps signal ids → mirror addresses. Per-
  message Com records live at `0x8008e000–0x8008ffe8`; the two 0x109 records are at `0x8008f2ac` and
  `0x8008f35c` (TwinCAN, two nodes) with cfg pointers `0x8008ef00` / `0x8008ef24` → signal-descriptor
  lists at `0x8008ebxx`. **The 8-byte descriptor field format was NOT fully cracked** (mixed
  absolute-dest and `{0,value}` forms; `value` is neither a clean bit position nor a registry id).
- TSK output side: Com config root `0x800906fc` (6-PDU instance) is parseable — PDU table
  `0x80090654` (stride `0x1c`), handle table `0x80090710`; **handle 3 = mailbox 0xa0 = 0x10C TSK_02**,
  PDU descriptor `0x800906a8`, unique packer `0x80123f10`. RAM-state stride is `0x14`.

**Boot / runtime (UPDATE 21–25):**
- Startup `0x80030002` (entry via vector `0x80020000` → `0x80030c1a`): sets trap vectors via `mtcr`,
  fills `.bss`, sets SP=`0xc03fc100`, builds the CSA free-list at `0xd0004000`, then `call 0x80021140`
  = **`main`** (`task_dispatch_loop`).
- `main` → `process_ecu_state` **`0x80021214`** = the **cyclic scheduler**: polls STM timer flag
  `*_DAT_c03fcb04 >> 0xd & 1`, and on tick calls periodic tasks from table `PTR_DAT_8002fd34`
  (count 4): `t0=0x80028348`, **`t1=0x8002837e`** (the **Com main-function**, calls
  `update_counter_or_reset(_DAT_c03fc37c)`), `t2=0x8002842c`, `t3=0x80028cca`.
- The generic Com engine is behind `PTR_FUN_80020130/34` → `0x80025130` / `0x8002523c` (PDU state
  machines); the per-signal bit-copy runs off the **runtime context pointer `_DAT_c03fc37c`**
  (C-RAM `0xc03fc37c`).
- **The blocker:** `c03fc37c` (Com context) and `c03fcb04` (STM status pointer that gates the
  scheduler) are set by **computed-pointer stores with NO static assigner** — invisible to Ghidra
  xref. They exist only at runtime, built by an init we have not located or been able to reach.

## Tools already built (in `core/ghidra/`, run via Ghidra headless)

Environment: `source `.env.sh` (sets `GHIDRA_HOME`=Ghidra 12.1.2, `JAVA_HOME`=JDK 21).
Project: `ecus/simos85/ghidra_proj/Simos85`, program `8R0907551F_Original.bin`. Invocation pattern:
```
"$GHIDRA_HOME/support/analyzeHeadless" ecus/simos85/ghidra_proj Simos85 \
  -process 8R0907551F_Original.bin -noanalysis \
  -scriptPath core/ghidra -postScript <Script>.java [args]
```
- **`EmulPeriph.java`** — the main emulator. TriCore PCode emulation (`EmulatorHelper`) + a peripheral
  layer: live STM timer, generic busy-wait breaker (resolves the polled address from the load insn and
  pokes it), core-CSR init, **nop-patching of unimplemented CALLOTHER insns** (`isync`/`dsync`/`mtcr`
  — Ghidra can't execute them; patched to `0x00` on first hit so they never re-throw), stderr/log
  suppression, and a pre-seed of `c03fcb04` + STM-flag injection. **Runs 100M+ real instructions
  cleanly.** Validated on leaf `801d4a5e` (reproduces `d000d536 = frame[6],frame[7]`). Args:
  `<entryHex> [budget]`.
- `EmulFn.java` — surgical single-function emulation with param (`<entryHex> <paramHex> [budget]`).
- `EmulTrace.java` — call-tracing + `c03fc37c` write-watch. `EmulMain.java` / `EmulSched.java` —
  earlier boot/scheduler variants. `Disasm.java <start> <end>` — disassemble a range.
  `RegList.java` — dump register names. `EmulInit.java` — CSA-setup probe.
Long runs are slow (~PCode interpreter); run them in the background and grep the log for markers
(`c03fc37c`, `TASK`, `STOP`, `FINAL`, `ACC mirrors`).

## What has been TRIED and did NOT build `c03fc37c` (do not simply repeat)

1. Emulate from `main` (`0x80021140`) with the full peripheral layer + scheduler pre-seed + STM-flag
   injection → 100M steps, loops in `process_ecu_state`'s phase-setup region, **`c03fc37c` never set,
   tasks never fire, ACC mirrors all zero**. The phase var `_DAT_c03fe328` never reaches its "run"
   state on this path.
2. Emulate `process_ecu_state(0)` (forces the `param != 0x1200` **full init block**) → also leaves
   `c03fc37c = 0`.
3. Surgical `init_system` (`0x80028d30`) → 5M steps, nothing.
4. `main`'s first init call `8002ec42` is a **no-op** (`*0x800301dc == 0`); `80021188`=stub,
   `80028e76`=UDS check. None build the context.
5. Static search for the assigner of `c03fc37c` / `c03fcb04` → none (computed a15-relative stores;
   confirmed byte-search negative in UPDATE 12).

## Ranked approaches to try next

1. **Interrupt modeling (most likely the real answer).** The context builder is probably reached via
   an **STM compare-match interrupt**, not the polled scheduler. Extend `EmulPeriph` to model
   interrupt dispatch: when `STM_TIM0 >= STM_CMP1` (or the STM ICR flag is set), vector the PC to the
   ISR (read the trap/interrupt base from `BIV`/`BTV` = `0x80020a00` / `0xd4000000` set by startup;
   the interrupt vector table is at that base, entries spaced by the priority). Run boot; watch for a
   write to `0xc03fc37c` and report the PC. This is the single highest-value experiment.
2. **Write-watchpoint sweep.** Modify `EmulPeriph` to check `c03fc37c` **every step** (not every
   0x400) and, the instant it becomes non-zero, print the PC + the surrounding decompile. Combine with
   (1) or with driving the phase machine so the builder is actually reached. The goal is only to learn
   *which function* writes it — then decompile that function and work statically.
3. **Drive the phase machine.** `_DAT_c03fe328` is the init phase (checked `== 0x1200` = "run").
   `0x80021214` sets it (`_DAT_c03fe328 = param` when `param != 0x1200`). Enumerate the phase sequence
   the real firmware walks (it is timer/counter driven) and call `process_ecu_state` (or the BSW init)
   once per phase in ascending order so **every** init phase's code runs. One phase builds the Com
   context. Watch `c03fc37c` across phases.
4. **Enumerate all init functions via call-trace.** Use `EmulTrace`-style logging to record every
   `call` target during the reachable boot, then for each, check (statically or by surgical emulation)
   whether it reads the Com config region `0x8008e000` or the registry `0x801f51a0`. The one that does
   is Com_Init. (Prior call traces reached ~a few dozen init functions before the scheduler; widen
   coverage by getting past the phase-setup loop.)
5. **Crack the descriptor format statically (parallel track, no emulation).** Read the generic engine
   `0x80025130`/`0x8002523c` and the functions reached through the context fn-pointers to learn the
   exact layout of the 8-byte descriptors at `0x8008ebxx` and how `value` maps to `{bit position,
   registry id}`. Anchor by finding the descriptor that must map to `d000d606` (ACC accel) or to a
   TSK_02 signal whose bit position is known from the DBC (`opendbc vw_mlb.dbc`, e.g.
   `TSK_Verzoeg_Anf` bit 56, `TSK_Radbremsmom` bit 40). Getting one anchor unlocks the format.
6. **Attack the TSK output side instead (may be easier).** The 0x10C Com instance (config root
   `0x800906fc`, handle 3, packer `0x80123f10`) is more parseable. The TSK_02 packer reads source RAM
   written by the coordinator. Find the coordinator by tracing backward from the packer's source
   addresses, or emulate the packer `0x80123f10` with a built context. If you can name the RAM that
   feeds `TSK_Verzoeg_Anf`/`TSK_Radbremsmom` and find its writer, that writer **is** the coordinator —
   the thing we ultimately want.

## Success criteria

You are done when you can state, with evidence (decompile lines and/or an emulation trace that
writes the address): the RAM address each ACC_01 0x109 signal decodes to (especially the jerk bytes
5–6 and `ACC_Dynamik` bits 58–59), **and/or** the located coordinator function that reads the ACC
accel mirror and writes the TSK_02 brake-request source RAM. Log findings as a new UPDATE in
`ecus/simos85/maps/RESULTS.md` and commit any new/edited scripts under `core/ghidra/`.

## Ground rules

- Do NOT suggest or rely on live/on-car testing — this is a static + emulation effort only.
- Be honest about negative results; record what was tried so the next agent doesn't repeat it.
- Prefer reading the actual decompiles (`ecus/simos85/analysis/decompiles_r/<addr>.c`) and the bin
  over guessing. The exhaustive decompile set is regenerable via `ecus/simos85/reproduce.sh`.
