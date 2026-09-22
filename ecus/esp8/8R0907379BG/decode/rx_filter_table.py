#!/usr/bin/env python3
"""Decode the ESP8 (8R0907379BG) CAN HW mailbox / RX-filter config table at 0xaea38.

Decodes the FlexCAN mailbox/RX-filter config. Record layout (stride 0x18),
VALIDATED against known ground truth (0x117=ACC_10, 0x104=EPB_01, 0x110, the ESP TX
ids 0x100/0x101/0x103/0x106/0x11e, the diag pair 0x6b4/0x6b8):

  +0x00  u32  mailbox register   (0xfff7eXX0)
  +0x04  u32  RxIndication handler (Thumb ptr, 0 = pure-data/no-callback or TX)
  +0x08  u32  controller base    (0xfff7e800 or 0xfff7ea00 = the 2 CAN controllers)
  +0x0c  u32  dlc/flags word
  +0x10  u32  arbitration word = (CAN_id << 18);  id = (w>>18) & 0x7ff
  +0x14  u32  index/aux

Emits decode/rx_filter_map.txt. Run: python decode/rx_filter_table.py
"""
import struct, os
FW = os.path.join(os.path.dirname(__file__), "..", "firmware", "8R0907379BG_0030.bin")
d = open(FW, "rb").read()
u32 = lambda o: struct.unpack('>I', d[o:o+4])[0]

NM_RANGE = {0x400, 0x404, 0x40c, 0x418, 0x440, 0x441, 0x478}
KNOWN = {0x117: "ACC_10", 0x104: "EPB_01", 0x110: "radar/pre-fill(dormant)",
         0x100: "ESP_01(TX)", 0x101: "ESP_02(TX)", 0x103: "ESP_03(TX)",
         0x106: "ESP_05(TX)", 0x11e: "ESP_08(TX)", 0x11d: "LH_EPS_02",
         0x6b4: "diag req", 0x6b8: "diag resp", 0x060: "heartbeat(TX)"}

def decode(base=0xaea38, maxrec=80):
    rows = []
    for i in range(maxrec):
        o = base + i*0x18
        mbx = u32(o)
        if not (0xfff7e000 <= mbx <= 0xfff7f000):
            break
        hnd = u32(o+4); ctl = u32(o+8); dc = u32(o+0xc); arb = u32(o+0x10)
        idv = (arb >> 18) & 0x7ff
        rows.append(dict(off=o, mbox=mbx & 0xffff, hnd=hnd, ctl=ctl & 0xffff,
                         dlc=dc, id=idv))
    return rows

def main():
    rows = decode()
    out = [f"# ESP8 8R0907379BG HW RX-filter/mailbox table @0xaea38 ({len(rows)} records, stride 0x18)",
           f"# {'off':>8} {'mbox':>6} {'ctl':>6} {'handler':>9} {'id':>6}  name/note"]
    for r in rows:
        nm = KNOWN.get(r['id'], "")
        if r['id'] in NM_RANGE and not nm:
            nm = "NM-range"
        elif r['id'] in NM_RANGE:
            nm += " [NM-range]"
        out.append(f"  {r['off']:#08x} {r['mbox']:#06x} {r['ctl']:#06x} {r['hnd']:#09x} "
                   f"{r['id']:#06x}  {nm}")
    txt = "\n".join(out) + "\n"
    path = os.path.join(os.path.dirname(__file__), "rx_filter_map.txt")
    open(path, "w").write(txt)
    print(txt)
    nm = [r for r in rows if r['id'] in NM_RANGE]
    print("NM-range mailboxes present:",
          ", ".join(f"{r['id']:#05x}@hw{r['mbox']:#06x}(hnd {r['hnd']:#x})" for r in nm))
    print("0x40c present as a hardware mailbox id:",
          any(r['id'] == 0x40c for r in rows), "(=> '0x40c container' is not a raw RX id)")

if __name__ == "__main__":
    main()
