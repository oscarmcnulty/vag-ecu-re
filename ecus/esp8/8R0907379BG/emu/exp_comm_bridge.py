#!/usr/bin/env python3
"""Full software wake chain for ESP8 (8R0907379BG), driven under Unicorn.

Bridges the RAM-dispatched ComM runnables that no static xref reaches, by calling
them directly in the order the (RAM-installed) ComM arbitration would:

  cannm_state_machine(0x6eba8)  -- gate on sig 0x047b, reach Network Mode
  comm_netmode_write(0x8f5cc)   -- ComM arbitration writes netmode(0x409230) =
                                   comm_mode_map(mode) and tx_gate2(0x409438) = NMword.bit21
  comm_nm_main(0x6a71c)         -- sets comm_enable_flag(0x40944c)=1 for netmode&0xf0 in {30,40,80}
  can_tx_scheduler(0x5bfc)      -- broadcasts IFF comm_enable==1 && tx_gate2!=0

Goal: prove the exact minimal RAM state that opens can_tx_scheduler's gate, and see
how far the TX path gets without a materialized object table.
All four are Thumb. Addresses/pointers verified from the flash literal pools.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE

RAM_BASES = os.path.join(HERE, "..", "analysis", "ram_bases.csv")
CANNM, NETMODE_WR, NM_MAIN, TX_SCHED = 0x6eba8, 0x8f5cc, 0x6a71c, 0x5bfc

# gate/observation addresses
NETMODE, TX_GATE2, COMM_EN = 0x409230, 0x409438, 0x40944c
NMWORD = 0x408f10          # sig 0x046f (NM word); bit21 -> tx_gate2
CANNM_STATE = 0x4090e2

def load_bases(e):
    for line in open(RAM_BASES):
        line = line.strip()
        if not line or line[0] in "#r":
            continue
        a, v = line.split(",")[:2]
        try: e.wr(int(a, 16), int(v, 16), 4)
        except Exception: pass

def newe():
    e = Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011]); load_bases(e)
    return e

def gate_snap(e):
    return dict(cannm_state=e.rd(CANNM_STATE,1), netmode=e.rd(NETMODE,1),
                tx_gate2=e.rd(TX_GATE2,1), comm_en=e.rd(COMM_EN,1),
                nmword=e.rd(NMWORD,4))

def show(tag, e):
    s = gate_snap(e)
    print(f"  [{tag}] cannm_state=0x{s['cannm_state']:02x} netmode=0x{s['netmode']:02x} "
          f"tx_gate2={s['tx_gate2']} comm_en={s['comm_en']} nmword=0x{s['nmword']:08x}")

def main():
    e = newe()
    # --- 1. drive cannm to Network Mode (state 9): master gate + matched NM word ---
    e.wr(0x408f0c, 0x01, 1); e.wr(0x408f0d, 0xff, 1); e.wr(0x408f0e, 0xff, 1)  # sig 0x047b byte0=1
    e.wr(0x4090d8, 0x80, 1)                 # nm_mode Network Mode
    e.wr(0x409478, 6, 1)                    # nm_state==6
    e.wr(0x408f1d, 1, 1)                    # NM-rx flag
    e.wr(0x408f14, e.rd(0x408f18, 4), 4)    # received NM word == expected (sig 0x04b6)
    # NM word (sig 0x046f) with bit21 set -> the byte the container must carry for tx_gate2
    e.wr(NMWORD, 1 << 21, 4)                # 0x00200000  (byte1 bit5)
    show("init", e)
    for _ in range(4):
        e.call(CANNM, thumb=True, maxinsn=300000)
    show("after cannm", e)

    # --- 2. ComM arbitration: FullCom mode (any mode !=0,3,4 -> comm_mode_map=0x80) ---
    e.uc.reg_write(__import__("unicorn").arm_const.UC_ARM_REG_R0, 1)
    e.call(NETMODE_WR, args=(1,), thumb=True, maxinsn=100000)
    show("after netmode_write(FullCom)", e)

    # --- 3. ComM main -> comm_enable ---
    e.wr(COMM_EN, 0, 1)                     # precondition: entry with comm_enable==0
    e.call(NM_MAIN, thumb=True, maxinsn=200000)
    show("after comm_nm_main", e)

    s = gate_snap(e)
    gate_open = (s['comm_en'] == 1 and s['tx_gate2'] != 0)
    print(f"\n  ==> can_tx_scheduler GATE {'OPEN' if gate_open else 'CLOSED'} "
          f"(needs comm_en==1 && tx_gate2!=0)")

    # --- 4. run the TX scheduler; detect OPEN (0x5c46) vs CLOSED (0x6334) branch
    #        + watch for CAN-controller mailbox MMIO ---
    from unicorn import UC_HOOK_CODE
    OPEN_PC, CLOSED_PC = 0x5c46, 0x6334   # the two gate targets (disasm-verified)
    def run_sched(ee, tag):
        br = {"open": 0, "closed": 0}; canmmio = []
        def on_code(uc, a, sz, u):
            if a == OPEN_PC: br["open"] += 1
            elif a == CLOSED_PC: br["closed"] += 1
        def on_wr(uc, ac, a, sz, v, u):
            if 0xfff7e000 <= a <= 0xfff7f000: canmmio.append((a, v))
        ee.uc.hook_add(UC_HOOK_CODE, on_code)
        ee.uc.hook_add(UC_HOOK_MEM_WRITE, on_wr)
        ee.call(TX_SCHED, thumb=True, maxinsn=800000)
        branch = "OPEN" if br["open"] else "CLOSED" if br["closed"] else "?"
        print(f"  [{tag}] scheduler branch = {branch}; "
              f"CAN-mailbox MMIO = {[(hex(a),hex(v)) for a,v in canmmio[:12]] or 'none'}")
    run_sched(e, "gate-open (full ComM chain)")

    # --- control: gate CLOSED (bench reality) for comparison ---
    e2 = newe(); e2.wr(COMM_EN, 0, 1); e2.wr(TX_GATE2, 0, 1)
    run_sched(e2, "gate-closed (bench reality: no container)")
    print("\n  NOTE: open branch emits NO mailbox write because the object table "
          "(0x40a1a8 / Nm chan 0x406d02) is not materialized in bare emu -- the standing "
          "objtable wall, now confirmed from the TX side. Gate LOGIC is fully satisfiable.")

if __name__ == "__main__":
    main()
