#!/usr/bin/env python3
"""NM container-reception oracle for ESP8 (8R0907379BG).

Emulates the REAL flash receive path transport_rx_process (FUN_00068 9e4, Thumb) against a
synthesized reassembled 0x40c container, to determine which sub-PDU 0x600 content the ECU
accepts and what it does to the enable gates. Seeds the boot-relocated sub-id list (pointer
0xbd774) with the real flash list from 0xb5760 (0x600 len4 / 0xf1a3 len3 / 0xf1a4 len8).

Reassembled-buffer layout (base 0x4050e8): buf[0x108]=segment len (=sublen+3=7 for 0x600),
buf[0x10a:0x10c]=sub-id (06 00), buf[0x10c:0x110]=the 4 sub-PDU bytes [d0 d1 d2 d3]. The NM word
handed to nm_msg_process is [buf[0x10e],buf[0x10d],buf[0x10c],buf[0x10f]] = [d2,d1,d0,d3]; node =
d0, and bit21(tx_gate2 source) = d1 bit5.

VERIFIED RESULTS:
- Accepted container (node d0 in {0x4a,5f,98,99,9a,d4}) sets 0x408f10 and net-active flag 0x408f20.
- For node 0x5f the accepted d1 (byte1) values are {0,1,8,9,40,41,48,49} = bits {0,3,6} only; byte1
  bit5 (0x20) is REJECTED by the flash validation masks 0xbda3c/3e. Since tx_gate2 = bit21 =
  d1 bit5, and comm_netmode_write is tx_gate2's SOLE writer, a valid NM container canNOT set
  tx_gate2 in emulation. Whether the live ECU's (possibly boot-relocated) masks also forbid bit5 is
  the open question -> test on the bench.

Run:  python nm_container_oracle.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(),"emu"))
from harness import Emu
RAM_BASES=os.path.join("analysis","ram_bases.csv")
e=Emu(); e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])
for line in open(RAM_BASES):
    line=line.strip()
    if line and line[0] not in "#r":
        a,v=line.split(",")[:2]
        try: e.wr(int(a,16),int(v,16),4)
        except: pass
BUF=0x4050e8; CH=0x4079a0; STATUS=0x4079e4; LIST=0xbd774
REAL_LIST = e.fw[0xb5760:0xb5760+24]
def trial(d0,d1,d2,d3, status=0x00000c00):
    e.uc.mem_write(LIST, REAL_LIST)
    e.wr(0x408f10,0,4); e.wr(0x409438,0,1)  # clear tx_gate2
    for a in range(0x408f20,0x408f24): e.wr(a,0,1)
    e.wr(BUF+0x22f,0,1); e.wr(BUF+0x108,7,1)
    e.wr(BUF+0x10a,0x06,1); e.wr(BUF+0x10b,0x00,1)
    e.wr(BUF+0x10c,d0,1); e.wr(BUF+0x10d,d1,1); e.wr(BUF+0x10e,d2,1); e.wr(BUF+0x10f,d3,1)
    e.wr(STATUS,status,4); e.wr(CH+0x35,0,1)
    try: e.call(0x689e4, thumb=True, maxinsn=400000)
    except Exception: return None
    return (e.rd(CH+0x35,1), e.rd(0x408f10,4), e.rd(0x409438,1), e.rd(0x408f20,1), e.rd(0x40944c,1))
print("accepted NM containers: does tx_gate2(0x409438) get set?")
for d1 in (0x00,0x01,0x08,0x09,0x40,0x41,0x48,0x49):
    r=trial(0x5f,d1,0,0)
    if r: print(f"  d1=0x{d1:02x}: state={r[0]} 0x408f10=0x{r[1]:08x} tx_gate2=0x{r[2]:02x} f20={r[3]} enable={r[4]}")
