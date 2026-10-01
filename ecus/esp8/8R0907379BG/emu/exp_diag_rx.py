#!/usr/bin/env python3
"""Does the COM RX ISR path (can_rx_isr 0x8f708 -> FUN_000501d4 0x501d4 -> dispatch via
0xb6a50[idx*0x18]) ever dispatch the DIAG mailbox (0xfff7e600 on module B)?

Mechanism (from decompiled 0x8f708 / 0x501d4):
  - can_rx_isr dispatches handler = *(0xb6a50 + idx*0x18); if idx==0xff or that word==0 -> DROP.
  - FUN_000501d4(param_1=mailbox_slot, param_2=controller{1=A@0xfff7e400,2=B@0xfff7e600})
    walks com_sig_group_table (0xb6a44, 62 recs, stride 0x18) and returns the record index whose
    mailbox pointer (rec+8) == (ctrl_base + param_1*0x10), else 0xff.
Hypothesis: the diag mailbox (module B slot 0 = 0xfff7e600) is NOT a COM group -> idx==0xff ->
can_rx_isr drops it -> this ISR never reaches the diag/CanTp handler. (Diag must use a different
dispatch; the COM ISR is not the UDS path.)

We validate the method on a known COM mailbox, then test the diag slot.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import Emu

RAM_BASES = os.path.join(HERE, "..", "analysis", "ram_bases.csv")
F_IDX   = 0x501d4          # FUN_000501d4: (slot, ctrl) -> com_sig_group index or 0xff
DISP    = 0xb6a50          # dispatch base used by can_rx_isr (= com_sig_group_table 0xb6a44 + 0xc)
CTRL_B  = 0xfff7e600       # module B mailbox array base (diag bus)
CTRL_A  = 0xfff7e400       # module A mailbox array base

def load_bases(e):
    for line in open(RAM_BASES):
        line = line.strip()
        if not line or line[0] in "#r":
            continue
        a, v = line.split(",")[:2]
        try: e.wr(int(a, 16), int(v, 16), 4)
        except Exception: pass

def probe(e, ctrl_sel, slot, cid):
    """Write the slot's arb word (=id<<18) then call FUN_000501d4; return (idx, handler)."""
    base = CTRL_B if ctrl_sel == 2 else CTRL_A
    mbx = base + slot*0x10
    # mailbox content: arb word at +0 (id<<18), a few data words after (harmless)
    e.wr(mbx+0, (cid << 18) & 0xffffffff, 4)
    e.wr(mbx+4, 0x00000000, 4)
    e.wr(mbx+8, 0x3e000000, 4)     # a plausible TesterPresent-ish payload
    res = e.call(F_IDX, args=(slot, ctrl_sel), thumb=True, maxinsn=200000)
    if res[0] != 'OK':
        return ('ERR:'+str(res[1]), None)
    idx = res[1] & 0xff
    hdlr = e.rd(DISP + idx*0x18) if idx != 0xff else None
    return (idx, hdlr)

def main():
    e = Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])   # seg2
    load_bases(e)

    print("=== sweep module B (ctrl=2) mailbox slots 0..15: which resolve to a COM group? ===")
    for slot in range(16):
        # use the id that the config table 0xaea38 assigns, but we don't strictly need it;
        # feed a generic id so only address-match entries resolve.
        idx, hdlr = probe(e, 2, slot, 0x100)
        mbx = CTRL_B + slot*0x10
        tag = ""
        if slot == 0: tag = "  <== DIAG mailbox 0xfff7e600"
        hs = f"0x{hdlr:08x}" if isinstance(hdlr, int) else str(hdlr)
        print(f"  B slot{slot:2d} (mbx 0x{mbx:08x}): idx={idx if isinstance(idx,str) else '0x%02x'%idx}  handler={hs}{tag}")

    print("\n=== control: a KNOWN COM mailbox should resolve to a valid idx+handler ===")
    # ACC_10 (0x117) config row had mailbox reg 0xe670 -> module B slot 7
    for cid, slot in [(0x117, 7), (0x104, 9), (0x100, 0)]:
        idx, hdlr = probe(e, 2, slot, cid)
        hs = f"0x{hdlr:08x}" if isinstance(hdlr, int) else str(hdlr)
        print(f"  id 0x{cid:03x} slot{slot}: idx={idx if isinstance(idx,str) else '0x%02x'%idx} handler={hs}")

    print("\n=== raw dispatch table 0xb6a50[idx] for idx 0..10 (handler words) ===")
    for i in range(11):
        print(f"  disp[{i:2d}] @0x{DISP+i*0x18:05x} = 0x{e.rd(DISP+i*0x18):08x}")

if __name__ == "__main__":
    main()
