# Recovered dispatch/config tables (from `uds_dispatch_recovery.md`)

Results of executing the recovery plan. Each section is tagged with the technique that
produced it (A = static flash-descriptor decode, B = init-trace, C = `SymbolicPropogator`
edge-resolution, D = emulation) and CONFIRMED (read from the bin) vs **inference**.

| Target | Technique | Status |
|---|---|---|
| 3. Writable flash window | **A** | **DONE** (§ below) |
| 1. SID → handler + level | **A/B** | **DONE** (§ below) |
| 2. `$27` seed/key | **A/B** | **DONE** (§ below) — and it isn't a seed/key |

> Method note: Targets 1 & 2 were closed **statically** without the `ResolveDispatchTables`
> Ghidra pass. Technique B's first trace (`DAT_d00005c8`←`0x8008eab0` via `801d8590`) led into
> a **GPTA/injection-timing** table, not UDS — another LLM-name mislabel (`800b3e6e`
> "handle_diagnostic_request" and `800b3f40` are GPTA, joining `800aa922`/`800a2c54` in §6c).
> The real table was found by **searching the image for a pointer to a behaviourally-confirmed
> handler** (`801229b4`, found at `0x80085f04`) — an approach that sidesteps the unreliable
> names entirely. `ResolveDispatchTables` is therefore not needed for these two, though it
> remains the general tool for the many other GPTA/Com jumptables.

---

## Target 3 — the writable flash window (Technique A, CONFIRMED from the bin)

Two flash-descriptor structures decode directly out of `8R0907551F_Original.bin`. Both are
lists of **20-byte segment records** `{flags, addr, size_mask, 0, back_ptr}` where the
programmable segment is `[addr & 0x0fffffff | 0x80000000, +size_mask+1)`. Addresses use the
TC1796 non-cached aliases (`0xa00xxxxx` PFLASH, `0xafexxxxx` DFLASH); mask them to the cached
`0x80…` image space. The nodes are walked by the step-dispatch trampoline
`task_dispatch_loop`@`0x800aa018` (`(*node[0])(node[1])`), i.e. these are flash **operation
step-lists** (erase/program/verify), with the concrete flash ops at `0x801d1926/1930/1980`.

### 3a. Master flash-geometry map `@0x80030268` (the full programmable layout)
The complete PFLASH+DFLASH sector geometry the flash driver knows about:

| segment (0x80… image) | size | region |
|---|---|---|
| `0x80020000` | `0x20000` (128K) | init / vector block |
| `0x80040000` | `0x40000` (256K) | **calibration** (`CAL_LO/HI`) |
| `0x80080000` | `0x80000` (512K) | ASW bank 0 (`0x80000–0x100000`) |
| `0x80100000` | `0x80000` (512K) | ASW bank 1 |
| `0x80180000` | `0x80000` (512K) | ASW bank 2 (…`0x200000`) |
| `0xafe00000` + `0xafe10000` | 64K each | DFLASH (EEPROM emulation) |

**This tiles `0x20000 → 0x200000` exactly — the boot sector `0x0–0x20000` (SBOOT/CBOOT) is in
NO programmable descriptor.** That is the geometric confirmation, independent of the RSA/CRC
story, that the boot sector is not writable through the normal flash driver — consistent with
it being blank in every OBD read and only reachable via the bench SBOOT/BSL path
(`obd_read_feasibility.md` §1, §3).

### 3b. The UDS-reflash op-descriptor `@0x800826c0` (what the diagnostic reflash path writes)
The programming-session executor `801d371c` hands the flash driver `801f13b8` the descriptor
root at **`0x800826c0`**, whose header is `count = 5` followed by segment records. Decoded, its
five segments are:

| segment | size | region |
|---|---|---|
| `0xa0040000` → `0x80040000` | `0x40000` (256K) | **calibration** |
| `0xafe00000` / `0xafe10000` (×2 each — erase + program passes) | 64K | DFLASH / EEPROM |

**So the OBD/UDS reflash path wired at `0x800826c0` programs calibration + EEPROM only — the
ASW code banks (`0x80080000/0x80100000/0x80180000`) are present in the master geometry map
(3a) but are NOT in this reflash descriptor's window.**

### What this establishes (refines `obd_read_feasibility.md` §3b/§6)
- The write path is **not** an arbitrary-address writer: it is scoped to a fixed descriptor
  of predetermined segments (as §6 inferred from the write-only transfer module), and that
  descriptor is **cal + EEPROM**. This is exactly the Pcmflash tuning surface — you can flash
  a modified *calibration* and adapt EEPROM, and nothing more, through this path.
- It **cannot write ASW code**, so it cannot be turned into the "install a reader stub"
  primitive that Door-2 patch-and-read needs (§2) — an independent, code-level confirmation of
  §3b, now not resting on the RSA-signature argument alone.
- **inference:** ASW reprogramming, where supported at all, must use a different (programming-
  session, signature-gated) descriptor built over the 3a geometry map; locating that descriptor
  and its auth is future work, but it does not widen the *read* surface either way.

### Reproduce
Pure Python over the image (no Ghidra) — scan for `{addr∈flash-alias, size_mask=2^n−1}` 20-byte
records, or dump `0x80030258…` and `0x800825c0…0x800826c0`. Regenerable from
`firmware/8R0907551F_Original.bin`.

---

## Target 1 — the UDS SID → handler + access table (CONFIRMED from the bin)

**Table base `0x80085e58`**, 23 records of **12 bytes** `{key, handler, aux}` where
`key = 0x00·attr·00·SID` (attr = session/security class), `handler` = service handler (or
`0` = declared-but-no-handler), `aux` = pointer to a subfunction sub-table. Located by
searching the image for a pointer to the behaviourally-confirmed handler `801229b4`
(at `0x80085f04`), then reading the record grid outward.

| SID | service | attr | handler | note |
|---|---|---|---|---|
| `0x10` | DiagnosticSessionControl | `0x31` | `8011ef88` | |
| `0x11` | ECUReset | `0x30` | `80122580` | |
| **`0x23`** | **ReadMemoryByAddress** | `0x30` | **`00000000`** | **declared, NULL handler → not implemented** |
| `0x27` | SecurityAccess | `0x30` | `00000000` | → subfn sub-table `0x80085e38` (Target 2) |
| `0x28` | CommunicationControl | `0x31` | `80123a28` | |
| `0x01`–`0x0a` | (subfunction slots) | `0x30/70` | `80123a28` | secondary key space, shared handler |
| `0x22` | ReadDataByIdentifier | `0x70` | `801229b4` | fixed-DID reads (the identify-for-VR surface) |
| `0x2e` | WriteDataByIdentifier | `0x30` | `00000000` | → DID sub-table `0x80085e4c` |
| `0x85` | ControlDTCSetting | `0x31` | `00000000` | → sub-table `0x80085e40` |
| `0x31` | RoutineControl | `0x30` | `00000000` | routine sub-dispatch |
| **`0x34`** | **RequestDownload** | `0x30` | **`00000000`** | write path via programming-session machinery |
| **`0x36`** | **TransferData** | `0x30` | **`00000000`** | ″ (into fixed RAM buffer → CRC-16 blocks) |
| `0x37` | RequestTransferExit | `0x30` | `8011efcc` | |
| `0x19` | ReadDTCInformation | `0x70` | `801227ec` | |
| `0x2f` | InputOutputControlByID | `0x30` | `00000000` | |
| `0x3e` | TesterPresent | `0x71` | *(boundary)* | session-timing block follows the table |

**Decisive, table-level read-surface verdict** (upgrades §6b from "no handler body found"):
- **`0x23` ReadMemoryByAddress is declared with a NULL handler** — recognised, but returns a
  negative response; there is no memory-read implementation.
- **`0x35` RequestUpload and `0x3d` WriteMemoryByAddress are NOT in the table at all** — the
  read/upload and arbitrary-write services simply do not exist on this ECU.
- `0x34`/`0x36` have NULL handlers *here* but are implemented via the programming-session
  reflash/transfer machinery (§3b: write-only, fixed staging buffer, cal+EEPROM window).
- So the entire CAN service surface returns **no arbitrary flash**: reads are `0x22` fixed
  DIDs only (identify-for-VR), writes are the scoped signed reflash. Confirms §6 end to end.

## Target 2 — `$27` SecurityAccess: it is *condition-gated*, not a seed/key (CONFIRMED)

`$27` has no primary handler; it dispatches through the aux sub-table at **`0x80085e38`** into
six subfunction handlers: `8012272c, 80122758, 80123074, 80123660, 80123828, 801238c8`.
Reading their bodies:

- **There is no cryptographic seed/key here** — no seed generated from an RNG/timer and no
  `key == f(seed)` comparison. Instead the levels are a **state machine gated by vehicle state
  and calibration bytes**:
  - `80122758` grants unlock (`DAT_d000ad76 = 1`, status bit `|= 0x40`) only when a set of
    conditions hold — road speed `DAT_d00082a2 == 0`, engine/ACC state, and **calibration
    enable bytes `DAT_80043f7d` / `DAT_80043e40` / `DAT_80043e88` (all in the `0x40000–0x80000`
    cal region → the security behaviour is *calibratable*)**; otherwise NRC `0x22`
    conditionsNotCorrect.
  - `80123074` / `80123660` are a routine-style state machine keyed by IDs `0x203/0x210/0x311/
    0x315/0x317/0x32e`, using NRC `0x13` (invalidKey) / `0x21` / `0x22`, setting state flags
    `DAT_d000ad5a/ad5c` and the current-routine register `_DAT_c000215e`.
  - `80123828` is a stub (always NRC `0x31`); `801238c8` (shared with the `0x2e` aux) is another
    conditions check.
  - The unlock flag `DAT_d000ad76` is consumed at `80106ed8`.
- **Implication:** there is no `$27` seed/key to recover or brute-force for a *read*, because
  there is no read service to unlock (Target 1). A cryptographic key for the *reprogramming*
  level, if one exists, is not in this app-level table — consistent with reflash being secured
  by the **RSA signature at the loader** (`RE_findings_checksum.md`), not an app `$27` challenge.
  (**inference** on the last point.)

## The UDS download (write) path — verification & partial-write feasibility

What `$34 RequestDownload` → `$36 TransferData` → `$37 RequestTransferExit` actually checks, and
whether a tool can write a **small sub-range** of the 256 K cal segment instead of all of it.
All hangs off the reflash descriptor `0x800826c0` (`_DAT_c03fd380`); cal is a *single* 256 K
segment (`0xa0040000`, size `0x40000`). The TC1796 PMU command sequences decode cleanly:
program-page `801f249e` (`0xAA/0x55/0xA0`), erase-sector `801f40de`/`801f2224` (`…/0x30` written
to the sector base), blank-check `801f1704` (compares against `0xff`, *not* the programmer).

**Verification = per-block CRC only; no whole-region gate.**
- Each `0x1e00` block self-validates: `word[0]==~word[0x1dfc]` (complement) **and**
  `crc16(payload,len,0xABCD)==word[0x1dfa]` (`uds_validate_xfer_block`@`801d1ebe`; the `0x80`-record
  variants `801d230e`/`801d283c` do the same). No cross-block or whole-segment integrity check.
- `$37 RequestTransferExit` (`8011efb8`) is trivial — clears a byte, transitions session state. **No
  whole-region checksum/signature over cal.**
- No static cal checksum in the image (`RE_findings_checksum.md` §4). RSA keys `0x73/0x6E/0x74` are
  boot-level (SBOOT/CBOOT), in the `0x0–0x20000` region blank in every OBD read — so whether cal is
  in the RSA scope **can't be proven statically**; empirically modified cal flashes accepted on the
  CRC alone (**inference**: cal not RSA-gated over OBD).

**Address handling — `$34` DOES accept a sub-range.** The only bound check (`801f1598:23`) is
`segment_size < offset+length-1 → NRC 0x80`, i.e. it enforces only `[offset,offset+length) ⊆
[0,segment_size)`. It does **not** require `offset==0`, `length==segment_size`, or sector alignment;
the write address is `segment_base + offset` (`801f3b5e:40`, byte-granular; the program stage buffers
to a 128/256-byte flash page). The request is still bounded to a *declared segment* (cal or EEPROM —
never the ASW banks).

**Erase — whole 256 K segment (the actual blocker).** The erase executor `801f3fb8` loops over
**every physical sector spanning the entire descriptor segment, unconditionally** — no "is this
sector written?" test — with the range taken from the static segment size (`find_map_index_801f1c74`
over `record+4`/`record+8`, not request-modifiable). So any cal erase wipes all 256 K to `0xFF`. The
physical sector size can't be read (the sector table is gitignored firmware data) but is immaterial:
the loop covers the whole segment regardless. Trigger: `$31` erase → `801d1a72:52` → `801f14e0` →
`801f3fb8`.

**Verdict — can you write small portions of cal?**
- **The transfer + validation layer would accept it** — a sub-range `$34`/`$36` of valid `0x1e00`
  blocks passes (Q2 + Q3).
- **But the normal sequence erases the whole 256 K first** (Q1), so anything you don't re-transmit is
  left erased (`0xFF`). To change arbitrary bytes you must erase (whole segment) and re-supply all
  256 K. There is **no UDS-reachable sub-segment / single-sector erase**.
- **Sole loophole:** a custom tool could **skip the `$31` erase** and send only `$34`/`$36` for a
  sub-range — program runs without a preceding erase. NOR flash only clears bits (`1→0`) on program,
  so a no-erase partial write sticks **only where the new bytes are a bitwise subset of the current
  bytes**. Fine for turning bits off (e.g. clearing a flag); useless for general map edits, which
  need `0→1` somewhere and thus an erase. Cite: `801f249e` does not self-erase; erase/program are
  separate ops.

Net for tuning: **surgical small-region cal writes are not achievable over the stock UDS surface** —
it's whole-segment erase + full 256 K rewrite (exactly what Pcmflash/WinOLS do), unless your edit
happens to be `1→0`-only.

## Net
Targets 1–3 all closed statically. The recovered tables confirm, at the dispatch-table level,
the §6 conclusion: **no `0x23`/`0x35`/`0x3d`, no CCP/XCP, `$27` gates nothing readable, and the
only write window is cal+EEPROM** → VR, not RD. The `ResolveDispatchTables` pass
(`uds_dispatch_recovery.md` Technique C) was not required here but is still the general tool for
the remaining GPTA/Com jumptables and for naming the NULL-handler routing at full fidelity.
