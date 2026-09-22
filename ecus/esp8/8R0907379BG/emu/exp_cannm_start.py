#!/usr/bin/env python3
"""Emulate cannm_state_machine (0x6eba8) with the master gate seeded, to confirm
HANDOFF step-2: does 0x047b==1 make CanNm advance (and toward what)?

We seed 0x408f0c(0x047b) byte0=1, nm_mode(0x4090d8)&0xf0=0x80, nm_state(0x409478)=6,
then step the state machine repeatedly, logging cannm_state(0x4090e2), netmode
(0x409230), tx_gate2(0x409438), comm_enable(0x40944c) and any CAN-controller MMIO."""
import os, sys
HERE = "/home/om/vag-ecu-re/ecus/esp8/8R0907379BG/emu"
sys.path.insert(0, HERE)
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE

RAM_BASES = os.path.join(HERE, "..", "analysis", "ram_bases.csv")
CANNM = 0x6eba8

WATCH = {
    0x4090e2: "cannm_state",
    0x409230: "netmode",
    0x409438: "tx_gate2",
    0x40944c: "comm_enable",
    0x408f20: "nm_active20",
    0x408f21: "nm_active21",
    0x408f0c: "sig_047b",
    0x4090d8: "nm_mode",
    0x409478: "nm_state",
}

def load_bases(e):
    for line in open(RAM_BASES):
        line = line.strip()
        if not line or line[0] in "#r":
            continue
        a, v = line.split(",")[:2]
        try:
            e.wr(int(a, 16), int(v, 16), 4)
        except Exception:
            pass

def snap(e):
    return {name: e.rd(a, 1) for a, name in WATCH.items()}

def run(nm_mode=0x80, nm_state=6, steps=8, verbose=True):
    e = Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2
    load_bases(e)
    # seed the wake preconditions
    e.wr(0x408f0c, 0x01, 1)     # 0x047b byte0 = 1  (master gate)
    e.wr(0x408f0d, 0xff, 1)     # counter-limit bytes high so state doesn't insta-reset
    e.wr(0x408f0e, 0xff, 1)
    e.wr(0x4090d8, nm_mode, 1)  # nm_mode & 0xf0 == 0x80 (Network Mode)
    e.wr(0x409478, nm_state, 1) # nm_state == 6
    # capture CAN-controller MMIO (0xfff7e400..0xfff7ec00 = mailboxes/ctrl)
    can_mmio = []
    def on_wr(uc, ac, a, sz, v, u):
        if 0xfff7e000 <= a <= 0xfff7f000:
            can_mmio.append((a, v))
    e.uc.hook_add(UC_HOOK_MEM_WRITE, on_wr)

    print(f"=== nm_mode=0x{nm_mode:02x} nm_state={nm_state} ===")
    print("start:", snap(e))
    for i in range(steps):
        res = e.call(CANNM, thumb=True, maxinsn=300000)
        s = snap(e)
        print(f" step{i}: ret={res[0]} state=0x{s['cannm_state']:02x} netmode=0x{s['netmode']:02x} "
              f"tx_gate2={s['tx_gate2']} comm_en={s['comm_enable']} "
              f"nm20={s['nm_active20']} nm21={s['nm_active21']}")
    if can_mmio:
        print(" CAN MMIO writes:", [(hex(a), hex(v)) for a, v in can_mmio[:20]])
    else:
        print(" CAN MMIO writes: none")
    return e

if __name__ == "__main__":
    # baseline: gate CLOSED (0x047b==0) should be a no-op
    e = Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011]); load_bases(e)
    e.wr(0x408f0c, 0, 1)
    before = snap(e); e.call(CANNM, thumb=True); after = snap(e)
    print("GATE CLOSED (0x047b=0): changed =", {k: (before[k], after[k]) for k in WATCH.values() if False})
    print("  cannm_state before/after:", before['cannm_state'], after['cannm_state'])
    print()
    run(nm_mode=0x80, nm_state=6)
    print()
    run(nm_mode=0x80, nm_state=0)
    print()
    run(nm_mode=0x20, nm_state=6)
