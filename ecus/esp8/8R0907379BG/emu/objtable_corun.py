#!/usr/bin/env python3
"""Object-table (0x40a1a8) materialization via walker+dispatcher co-run — session-2 progress.

Goal: run the COM-init config interpreter in Unicorn so the runtime object table at
0x40a1a8 (handle -> descriptors -> buffers) is populated, which resolves every
signal->buffer->CAN-id binding (incl. the NM container id feeding 0x408f10) that is
otherwise object-table-routed and unresolvable statically.

WHAT THIS SESSION CRACKED (all reproduced by this script):
- Firmware is ARM BE32; the harness (harness.py) maps flash+RAM+seg2 correctly.
- DISPATCHER FUN_0008df52 is **Thumb** (function_entries: 0x8df52,T). Prior drive loops
  called it as ARM and executed garbage. It runs ONE builder op per call, gated by:
      *0x406aa0 == 0 (not done) AND *0x4092e0 == 0 (no error)
      AND *0x4069e5 == 1 AND *0x4069e7 == 0        (enable the builder switch)
      AND *0x4069e4 != 1   (==1 diverts to phase-0 setup FUN_000931e8)
      AND phase *0x406aa4 == 1
    then switch(*0x4069a8): 0xd3=registrar(814c2) 0xd4=alloc(89f90) 0xdd=phase(892a0)
    0xe0=populate(8e298) ... — VERIFIED: each command branches into its builder.
- WALKER FUN_00049f38 is ARM. Entry: if *0x406aa0!=0 return; if *0x4069e3==1 -> the
  per-state staging-clear switch (0x4a004..); else -> MAIN BODY at 0x4a060.
  Main body needs *0x4069e2 == 1 (record-ready, set by FUN_0008e4f4) and reads the
  staged 14-byte record at the cursor 0x406980:
      record[4]==0xff -> copy record[0:8] to header 0x40699c, set *0x4069e4=1
      record[4]==0xdc -> emit an alloc command into the queue struct @0x408ba8
      else (phase==1, *0x4069e5==0) -> copy record[0:0xc] to dispatch staging 0x4069a4,
                                       set *0x4069e5=1
      else (*0x4069e5==1) -> alloc + emit command tag 2 (0xfe marker) into 0x408ba8
  Tail (0x4a184+): a state machine on *0x406a04 / *0x408ba0..ba1 that calls the sizer
  com_objtable_alloc(0x8e3d0) when *0x408ba1 == 0x14, reading config via 0xbd6c4.
- HELPERS: FUN_00049e48 / FUN_00049e80 are 16-bit **byte-swap** routines — the config
  half-words are byte-swapped on read (matters when feeding/parsing records).
- CONFIG SOURCE: records are submitted one at a time via FUN_0008e4f4(len<=14, record_ptr)
  which memcpys the record to cursor 0x406980 and sets *0x4069e2=1, then calls the walker.
  The record iterator that calls it (FUN_000954ce -> ...-> FUN_0008e4f4) is RAM-wired
  (object-table dispatch, no static caller) — so records must be fed by us. Config root
  is 0xa7e14 (a variable-length TLV stream; a fixed 14-byte step does NOT align).

REMAINING (precisely scoped) to finish materialization:
1. The walker emits into a COMMAND QUEUE at 0x408ba8 (fields +0xc tag, +0xe handle,
   +0x10 marker 0xfe/0xff, +0x11 len, +0x14 ptr), while the dispatcher consumes dispatch
   staging 0x4069a4. Find the step that moves a queued command into 0x4069a4 (or drive the
   builder ops directly from the queue), so walker output reaches the dispatcher.
2. Sequence the walker's 2-phase-per-record protocol + the 0x406a04/0x408ba1 tail state so
   records advance (currently it processes ~1 record then stalls waiting for consume/ack).
3. Parse the 0xa7e14 TLV with correct record lengths (per record[4] type) + byte-swap, so
   the right records are fed in order — OR let the walker self-advance the cursor if it does.

NOTE FOR THE WAKE GOAL: materializing the table yields the ROUTING (container CAN-id ->
signal 0x046f -> 0x408f10). The CONTENT needed to pass FUN_00040950's node-id/mask
validation is a separate problem (needs the real sensor-cluster NM payload or a capture).

Run:  python objtable_corun.py         # drives the current partial pipeline + reports
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_BLOCK

HERE = os.path.dirname(os.path.abspath(__file__))
RAM_BASES = os.path.join(HERE, "..", "analysis", "ram_bases.csv")

WALKER = 0x49f38       # ARM
DISP = 0x8df52         # Thumb
CURSOR = 0x406980      # staged-record buffer (DAT_0008e54c / walker DAT_0004a4d0)
ROOT = 0xa7e14         # flash config root
OBJ_LO, OBJ_HI = 0x40a1a8, 0x40a1a8 + 0x8000

BUILDERS = {0x814c2: "d3-registrar", 0x89f90: "d4-alloc", 0x8efbc: "d5", 0x9a66a: "d6",
            0x892a0: "dd-phase", 0x6bb22: "de", 0x9e3f4: "df", 0x8e298: "e0-populate",
            0x7a072: "e1", 0x9db84: "e2", 0xa0d48: "f1", 0x931e8: "phase0-setup"}


def load_bases(e):
    n = 0
    for line in open(RAM_BASES):
        line = line.strip()
        if not line or line[0] in "#r":
            continue
        a, v = line.split(",")[:2]
        try:
            e.wr(int(a, 16), int(v, 16), 4)
            n += 1
        except Exception:
            pass
    return n


def fresh():
    e = Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2 at VMA=file+3
    load_bases(e)
    e.wr(0x4069b4, 0x40a1a8, 4)   # object-table base
    e.wr(0x4069b0, 0x40a1a8, 4)   # bump pointer
    e.wr(0x406aa4, 1, 4)          # phase = 1
    e.wr(0x406aa0, 0, 1)          # done flag clear
    e.wr(0x4092e0, 0, 1)          # error gate clear
    e.wr(0x4069e1, 0, 1)          # dispatcher flags (bit2=0 -> switch runs)
    return e


def demo_dispatcher_branches():
    """VERIFIED: with the gate flags set, each command 0xd3.. branches into its builder."""
    print("== dispatcher builder-branch check (Thumb) ==")
    for cmd in (0xd3, 0xd4, 0xdd, 0xe0, 0xdf):
        e = fresh()
        e.wr(0x4069e4, 0, 1)
        e.wr(0x4069e5, 1, 1)
        e.wr(0x4069e7, 0, 1)
        e.wr(0x4069a8, cmd, 1)
        hit = []
        e.uc.hook_add(UC_HOOK_BLOCK,
                      lambda uc, a, s, u: hit.append(BUILDERS[a]) if a in BUILDERS else None)
        r = e.call(DISP, thumb=True, maxinsn=500000)
        print(f"   cmd=0x{cmd:02x} -> {r[0]} builder={hit[:1]}")


def demo_walker_processes_record():
    """VERIFIED: walker main body copies a staged normal record into dispatch staging."""
    print("== walker processes a staged record ==")
    e = fresh()
    rec = e.fw[ROOT + 14: ROOT + 28]      # the first non-zero (type 0x09) record
    e.uc.mem_write(CURSOR, rec)
    e.wr(0x4069e2, 1, 1)
    e.wr(0x4069e3, 0, 1)
    r = e.call(WALKER, args=(0, 0, CURSOR, 0x4f0000), thumb=False, maxinsn=400000)
    stg = " ".join("%02x" % b for b in e.uc.mem_read(0x4069a4, 12))
    print(f"   walk={r[0]}  dispatch-staging 0x4069a4 = [{stg}]  "
          f"e5(staging-full)={e.rd(0x4069e5, 1) & 0xff}")


if __name__ == "__main__":
    demo_dispatcher_branches()
    demo_walker_processes_record()
    print("\nSee module docstring for the precisely-scoped remaining steps.")
