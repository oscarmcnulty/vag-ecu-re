# MED17.1.1 engine ECU — CAN signal / handler map (8R0907115N_0006)

Companion to `acc_flow.md` (the ACC_01→TSK longitudinal trace). This file documents the **CAN
infrastructure** the trace sits on. Built from the decompiled corpus
(`analysis/decompiles_r/<vaddr>.c`) + raw firmware reads. Load base
`0x80000000`; `0xa00xxxxx` = uncached mirror; file offset = `addr & 0x1FFFFFFF`; RAM = `0xd00xxxxx`.

> **Architecture headline — this is NOT Simos8.5.** MED17.1.1 runs a **generic table-driven Vector
> CANbedded IL** (interaction layer) + AUTOSAR-Com, and the **CAN controller is an external companion
> chip reached over the Infineon MLI (Micro Link Interface) serial link** (`MLI0_TP0BAR/TRSTATR/TCBAR/
> RDATAR`, drivers `FUN_8009319e`/`FUN_80093318`). Consequence: there is **no "13 dedicated hardware
> mailbox handlers" table** like Simos8.5. Every message flows through generic descriptor arrays keyed
> by CAN-id and by internal slot; only a handful of **TX signal producers** (the TSK app functions) are
> bespoke. The RX signal decode and the TX byte assembly are **data-driven from flash descriptor
> tables**, so the byte↔signal wire layout is a *table decode*, not a readable per-message packer.

## Three tables that define the message layer

### 1. Per-MO CAN-ID table @ `0x80027fd4` (121 × u32) — CONFIRMED
`id_table[i]` = CAN ID assigned to internal message-object `i`. Located mechanically (dense run of
`<0x800` values); not referenced by literal address in any decompiled function (read by the driver init
via base+index), so the MO↔ID binding is authoritative from the table but has no code xref.

| MO# | CAN ID | msg | dir | MO# | CAN ID | msg | dir |
|---|---|---|---|---|---|---|---|
| 52 | 0x106 | ESP_05 | RX | 67 | 0x10e | **TSK_04** | **TX** |
| 58 | 0x10d | ACC_05 | RX | 68 | 0x10c | **TSK_02** | **TX** |
| 59 | 0x109 | **ACC_01** | **RX** | 69 | 0x10a | **TSK_01** | **TX** |
| 76 | 0x10b | LS_01 | RX | | | | |

Other 0x10x/0x11x occupants: MO47=0x104, MO53=0x101, MO64=0x114, MO65=0x107, MO66=0x111, MO81=0x102,
MO92=0x103, MO93=0x100, MO95=0x115, MO107=0x105, MO43=0x11d. (Remainder are 0x0xx/0x3xx/0x5xx/0x6xx
body/chassis IDs.) **Direction is not a per-MO bit** in a sibling array — it is encoded in the runtime
per-id descriptor flags (via `*(a9+0x36c)`/`*(a9+0x370)`) and by TX-slot membership (`DAT_800296aa`=20
TX slots; the RX timeout monitor covers id window `[0x434,0x5b0)`). RX/TX above is from the dbc,
corroborated by handler behaviour (TSK_* drive the TX set-signal path; ACC_*/LS_*/ESP_* only get gated
by the validity accessor).

### 2. Master message-handle array @ `0x80028bc0` (278 × u16) — CONFIRMED
A plain **descending u16 list of every CAN id**, `0x116` at idx0 down to `0x0001` at idx277 (ends
`0x80028dea`). The **address of a message's id-slot is its canonical "handle"** — the token passed around
the IL. Dereferencing a handle yields the 16-bit id, which indexes the RAM status arrays.

> **Closed form: `handle(id) = 0x80028bc0 + (0x116 − id)·2`.**

| msg | id | handle | | msg | id | handle |
|---|---|---|---|---|---|---|
| ESP_05 | 0x106 | `0x80028be0` | | TSK_02 | 0x10c | `0x80028bd4` |
| ACC_01 | 0x109 | `0x80028bda` | | ACC_05 | 0x10d | `0x80028bd2` |
| TSK_01 | 0x10a | `0x80028bd8` | | TSK_04 | 0x10e | `0x80028bd0` |
| LS_01 | 0x10b | `0x80028bd6` | | | | |

Idiom everywhere: `FUN_800981cc((int)DAT_80028bXX)` = "read the id at this handle, return its validity".
Handles are also passed to `FUN_80093910(id,state)` (participation/enable) and to the TX dispatch.

### 3. TX signal-handle table @ `0x800295e0` (u16, `0x11`…`0x01`) — CONFIRMED
Small descending list of **TX signal handles**. The TSK producers deposit values by these handles:
- **TSK_02** (`FUN_80140922`): handles 8/9/10 (`DAT_800295f2/f0/ee`) + status 1/2 (`DAT_80029600/fe`).
- **TSK_04** (`FUN_801455ae`): handles 5/6/7 (`DAT_800295f8/f6/f4`).

## The validity accessor `FUN_800981cc` @ `0x800981cc` — CONFIRMED
```c
byte FUN_800981cc(uint id){
  id &= 0xffff;
  if (id < 0x17 /*DAT_80027f88=23*/) return (DAT_d000b083[id] >> 6) & 1;  // bit 0x40, low-id set
  return (DAT_d000b117[id] >> 5) & 1;                                     // bit 0x20, full range
}
```
- **Returns the timeout / not-present flag: `0` = message present & fresh (use real data); `1` = timed-out
  / absent (use failsafe).** Proven by caller `FUN_80087a70`: real signal data is read only when the
  accessor is `0`, else a default/`0` is sent. (This is the opposite polarity to a naive "is-valid" read —
  noted because it inverts every gate.)
- Status arrays are byte-indexed by CAN id: `DAT_d000b083[id]` (bit `0x40`, ids<23) and
  `DAT_d000b117[id]` (bit `0x20`, ids≥23; e.g. ACC_01 0x109 → `b117[0x109]`). Low nibble = a 4-bit
  confirmation down-counter; bit `0x80` = "changed".
- **Bits set/cleared by the RX reception monitor:** `FUN_800bc5d6` (event-driven — on reception clears the
  timeout bit + bumps the counter; on a missed cycle decrements, and at 0 sets timeout `|=0xa0`) and
  `FUN_8009787e` (periodic sweep, the timeout monitor proper, called from `FUN_80093910`). Both walk a
  per-bus slot→id map (`DAT_d0006d84`) + threshold table (`DAT_d0006d88`).

## Generic RX path — PARTIAL (MLI-based, table-driven)
- **`FUN_80099600`** = the generic per-MO receive dispatch loop: round-robin MO cursor `DAT_d000b68a`
  (bound `DAT_800296aa`), per-MO control words `(&DAT_d0009330)[MO]` (pending bit `&0x4000`), per-MO
  buffer index `(&DAT_d0013e64)[MO]` → data at `*(a9+0x370) + idx` (**`a9+0x370` = CAN controller
  message-RAM base**). Message RAM is organised **C_CAN-style as parallel per-byte arrays indexed by MO**
  (readers hit `msgram+0x456/0x46f/0x565/0x5c9` = "field-X"[MO]) — which is why **no contiguous 8-byte
  ACC_01 record appears in the C**.
- Generic per-MO state machines (shared, not message-specific): `FUN_8009c532` (state table `DAT_800455a0`),
  `FUN_800be038`, `FUN_8009a3ae`, `FUN_8009acd2` (transition table `DAT_8003debc`, index `DAT_8004556f`).
  These do timeout / rolling-alive / valid-bit tracking that feeds the presence bitfields above.
- **RX signal decode is table-driven** (descriptor `DAT_d0006e40`, bit-offset table `DAT_800441f8`) — there
  is **no hand-coded bit-unpacker** per message. The decoded ACC request is consumed through the struct at
  `*(a9+0x3ec)` (see `acc_flow.md`).
- **GAP:** exact MLI RX ISR entry + precise per-slot frame stride not pinned; IL frame-stage base
  `~0xd001429c` is code-confirmed (slot→id `DAT_d0013e64`, slot state `DAT_d0013e8c`).

## Generic TX path — CONFIRMED
Dispatch is by the **top nibble of the handle** (`handle>>12`) through the 16-entry pointer table
**`PTR_FUN_8003e0d8`**:
- **`FUN_8009d0ca(handle, value, 0, ctx)` @ `0x8009d0ca`** = the **generic set-signal / request-transmit
  dispatcher** (the CANbedded `Il_SetTxSignal` equivalent) that the app producers call. For a *signal
  handle* (class 0) it routes to **`FUN_800bffba` = Com_SendSignal / bit-packer**, which writes the value
  into the packed frame buffer using signal descriptor `DAT_d0006e48[handle]` (bit offset/length) + flash
  table `DAT_800441f8`. For a *message handle* (class 8, `0x84xx`) it requests the MO transmit.
  (The `PTR_FUN_8003e0d8` dispatch + the `0x800bffba` bit-packer are the Com signal path; some calls
  set a status/quality signal to `0`/`0xf`.)
- **`FUN_8009ca3c(id, …)` @ `0x8009ca3c`** = per-id **TX-request state machine** (control nibble
  `DAT_d00142c5[id]`, pending bitmap `DAT_d0009386`) → hands to **`FUN_800be052`**.
- **`FUN_800be052(id, …)` @ `0x800be052`** = the **CANbedded TX slot engine**: looks up the internal TX
  slot, memcpys the packed signal buffer into the MO frame (src `~0xd001429c`, dst `*(a9+0x3c8)`), **stamps
  the rolling counter**, sets request flags `DAT_d0009330[slot]`.
- **Cyclic TX scheduler** = `FUN_8009c694` (round-robin over the 20 TX slots); bus (re)init = `FUN_8009b9e8`.
  The TSK producers are dispatched from an **unresolved function-pointer task table** (zero in-corpus
  callers), so the **cyclic period (≈20 ms by Simos analogy) is not statically recoverable** — GAP.

## COM signal-descriptor table — signal ↔ RAM bindings recovered  ⭐ [C]

The COM stack binds signals to RAM in **data**, not code: the unpack routines store through a pointer read
from a descriptor record, so Ghidra shows the ACC status/state globals as unwritten. The descriptors are
plain records and decode cleanly, which recovers the bindings the call graph cannot. Applied by
**step 6b** of the pipeline (`core/ghidra/DecodeComBindings.java`, constants in `ecu.conf` as
`COM_DESC_CB`/`COM_DESC_CTX`), which annotates every target so the decompiles carry the binding inline.

**Record layout (40 bytes):**

| offset | field |
|---|---|
| `+0x00` / `+0x04` / `+0x08` | pointers into a constant pool — max / SNA / default values |
| `+0x0c` | conversion callback `0x800286c6` — **invariant across the table** |
| `+0x10` | context `0xd000ad2a` — **invariant** |
| `+0x14` | mask `0x0000ffff` |
| `+0x18` | **RAM target** |
| `+0x1c` | `[start_bit, bit_len, type, 0]` |

Records are located by the invariant `+0x0c`/`+0x10` pair rather than by stride, so enumeration does not
depend on the table being contiguous. On this image: **278 records, 40-byte stride, `0x80035e28`–`0x8003a9a0`.**

**The decode is self-checking:** a correct format implies `start_bit + bit_len <= 64` (signals live in an
8-byte frame). Measured **278/278 = 100%**, with start bits 0–62 and lengths 2–20. Random bytes would not
do that, so the layout is confirmed rather than fitted.

**Confirmed binding:** `d000a590` ← `ACC_01` (0x109) **bit 60 len 3** = `ACC_Status_ACC` (record
`@0x80038ad8`, desc `0x0000033c`) — independently matching the on-car CAN log, where openpilot's commanded
status maps 1:1 through `tbl[]` to `TSK_04`. A second record `@0x80038a60` binds the same byte from bit 57
len 3 (platform variant). Also: **message handles are literally CAN IDs** (`0x80028bd0` = `0x010e` = TSK_04,
`0x80028bda` = `0x0109` = ACC_01), with internal PDUs sharing the id space above the CAN range.

**Still GAP:** the record→PDU grouping. The `+0x00/+0x04/+0x08` pointers resolve into a constant pool of
limit/default values, not a message table, so a record's owning message is not yet recoverable — which is
what blocks naming the producer of `d000a6c3` (bit 44 len 4, internal PDU).

## MLB E2E checksum + rolling counter — PARTIAL
- **Rolling counter (byte1 low nibble) — CONFIRMED:** global `DAT_d000b729` (u8, reset in `FUN_8009b9e8`)
  copied into per-slot `DAT_d00142b0[slot]` and post-incremented on each commit in `FUN_800be052`.
- **Checksum (byte0) — mechanism known, function GAP:** no standalone XOR routine surfaced; byte0 =
  `seed ^ XOR(bytes1..7)` with per-id `seed = (id>>8)^(id&0xff)` (**ACC_01 0x109 → 0x08**; TSK_01 0x10a →
  0x0b; TSK_02 0x10c → 0x0d; TSK_04 0x10e → 0x0f). Applied inside the generic per-id E2E Com pack callback
  (a message is flagged E2E-protected via the `*(a9+0x36c/0x370)` per-id flag, test `bVar8 & 2` in
  `FUN_800be052`); the exact callback address is not pinned. Matches the verified MLB seeds in the
  `vw-mlb-checksums` note.

## Target-message handler table (MED17 idiom — the analog of Simos8.5's "13 dedicated handlers")
"App function" = the bespoke application function that touches the message (validity gate for RX, signal
producer for TX). Everything else is generic IL/Com.

| CAN ID | msg | MO# | dir | handle | app function | mechanism | conf |
|---|---|---|---|---|---|---|---|
| 0x106 | ESP_05 | 52 | RX | `0x80028be0` | `FUN_8019c6a0` (presence collector) | validity→shadow `d00028cX`; signals via generic Com | high |
| **0x109** | **ACC_01** | 59 | **RX** | `0x80028bda` | consumed in `FUN_801455ae`/`FUN_80145c88` via `*(a9+0x3ec)` | generic table decode → ACC-request struct; gated `d000a454==2` | high |
| **0x10a** | **TSK_01** | 69 | **TX** | `0x80028bd8` | `FUN_8014469a` (+ byte packer `FUN_80143a68`) | TSK_Status_AB(24b) ← `d000f828/29/2a`; generic Com serialize | med-high |
| 0x10b | LS_01 | 76 | RX | `0x80028bd6` | `FUN_8017a760` (presence collector) | validity→shadow; generic unpack | high |
| **0x10c** | **TSK_02** | 68 | **TX** | `0x80028bd4` | **`FUN_80140922`** | decel/hold/status shadows → generic Com (sig handles 8/9/10); gated `d000a454∈{1,2}` | high |
| 0x10d | ACC_05 | 58 | RX | `0x80028bd2` | read in `FUN_801455ae` | validity `FUN_800981cc(0x10d)`; gated `d000a454==2` | high |
| **0x10e** | **TSK_04** | 67 | **TX** | `0x80028bd0` | **`FUN_801455ae`** | status/gear shadows → generic Com (sig handles 5/6/7); gated `d000a454==2` | high |

> `FUN_8019c6a0` and `FUN_8017a760` are validity **collectors** (fan `FUN_800981cc` over many handles into
> `d00028cX`/`d0009fxx` presence-shadow bytes) — **not** signal decoders/packers. Don't mistake them for
> handlers; this was the first false trail (the ACC_01 handle only appears in `8019c6a0`).

## Quick-reference addresses
- per-MO id table `0x80027fd4` (121×u32) · handle array `0x80028bc0` (278×u16, `0x116`↓`0x001`)
- validity accessor `FUN_800981cc` (thr `DAT_80027f88`=23; arrays `d000b083` bit0x40 / `d000b117` bit0x20)
- RX monitors `FUN_800bc5d6` (event) / `FUN_8009787e` (sweep) · RX dispatch `FUN_80099600`
- TX set-signal `FUN_8009d0ca`→`PTR_FUN_8003e0d8`→Com_SendSignal `FUN_800bffba` · TX FSM `FUN_8009ca3c` · slot engine `FUN_800be052` · scheduler `FUN_8009c694`
- rolling counter `DAT_d000b729`→`DAT_d00142b0[slot]` · TX signal-handle table `0x800295e0`
- MLI driver `FUN_8009319e`/`FUN_80093318` (external CAN controller) · CAN msg-RAM base `*(a9+0x370)`

## The load-bearing open item: the unresolved base register `a9`
Every per-message runtime structure hangs off **`a9`** (CAN msg-RAM `*(a9+0x370)`, per-id config
`*(a9+0x36c)`, ACC-request struct `*(a9+0x3ec)`, ACC cal struct `*(a9+0x3dc)`, MO frame area `*(a9+0x3c8)`).
Ghidra's `SetBaseRegs` pinned `a0/a1/a8` (see `ecu.conf`) but **not `a9`** — it is loaded in the
un-decompiled task dispatcher and preserved across the task, so all `*(a9+…)` members stay symbolic.
Resolving `a9` (emulation — as Simos8.5's `EmulComWatch` did — or a RAM dump) is what would turn the
table-driven RX shadows and the pointer-relative cal cells into absolute addresses. This is the single
highest-value next step for both this map and `acc_flow.md`.
