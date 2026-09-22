#!/usr/bin/env python3
"""Drive cannm_state_machine to Network Mode by satisfying its case-4 NM-RX
comparison, to characterize exactly what container-delivered NM state moves the
module toward comm-enable. Reuses harness."""
import os, sys
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,HERE)
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
RAM_BASES=os.path.join(HERE,"..","analysis","ram_bases.csv")
CANNM=0x6eba8
def load_bases(e):
    for line in open(RAM_BASES):
        line=line.strip()
        if not line or line[0] in "#r": continue
        a,v=line.split(",")[:2]
        try: e.wr(int(a,16),int(v,16),4)
        except: pass
def newe():
    e=Emu(); e.uc.mem_write(0xbb048,e.fw[0xbb045:0x134011]); load_bases(e)
    return e
WATCH={0x4090e2:"cannm_state",0x409230:"netmode",0x409438:"tx_gate2",
       0x40944c:"comm_en",0x408f20:"nm20",0x408f21:"nm21",0x408f1e:"f1e"}
def snap(e): return {n:e.rd(a,1) for a,n in WATCH.items()}
def scenario(name, setup):
    e=newe()
    e.wr(0x408f0c,0x01,1); e.wr(0x408f0d,0xff,1); e.wr(0x408f0e,0xff,1)
    e.wr(0x4090d8,0x80,1)      # nm_mode Network Mode
    setup(e)
    log=[]
    seen=set()
    def on_wr(uc,ac,a,sz,v,u):
        if 0xfff7e000<=a<=0xfff7f000: log.append((a,v))
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_wr)
    print(f"--- {name} ---")
    for i in range(6):
        e.call(CANNM,thumb=True,maxinsn=300000)
    print("  end:",{k:hex(v) for k,v in snap(e).items()})
    print("  CAN-TX MMIO:", [(hex(a),hex(v)) for a,v in log[:8]] or "none")
# S1: nm_state==6, received NM word (0x408f14) == expected (0x408f18), rx-flag 0x408f1d=1
def s1(e):
    e.wr(0x409478,6,1)
    e.wr(0x408f1d,1,1)                 # "NM msg received this cycle"
    w=e.rd(0x408f18,4); e.wr(0x408f14,w,4)   # received == expected 0x04b6 word
scenario("nm_state=6, rx-flag set, rxword==expected", s1)
# S2: same but received word differs (mismatch path)
def s2(e):
    e.wr(0x409478,6,1); e.wr(0x408f1d,1,1); e.wr(0x408f14,0xdeadbeef,4)
scenario("nm_state=6, rx-flag set, rxword mismatched", s2)
# S3: nm_state=6, no rx flag (bench reality: gate open but no NM frame)
def s3(e):
    e.wr(0x409478,6,1); e.wr(0x408f1d,0,1)
scenario("nm_state=6, NO rx flag (bench: 047b=1 only)", s3)
