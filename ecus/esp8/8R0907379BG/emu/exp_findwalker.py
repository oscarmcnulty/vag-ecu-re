import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Emu
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
FNS=[0x21896,0x8760a,0x9d2d6,0xa1060,0x53e3c,0x9f32c,0x9c0c4,0x9ed00,0x77d42,0x33338,0x9cff6,
0xa0614,0x6b00,0x827ac,0x82732,0x6b550,0x3d13c,0xa4ec,0xa168,0x9e28,0x9be0,0xa314,0x3d260,
0x3aba0,0x9543c,0x50460,0x29b70,0x962e8,0xa1a28,0x37b54,0x33e10,0x310ec,0x3714c,0x5216c,
0x507f4,0xa0654,0x93600,0x93674,0x9b910,0x83d14,0x8c9c8,0x976e8,0x14dec,0x40268,0x9fb54,
0x90db2,0x317c,0x1750,0x6d81a,0x9f276,0x91168,0x7630c,0x8e0aa]
def load_bases(e):
    for line in open(os.path.join(os.path.dirname(__file__),"..","analysis","ram_bases.csv")):
        line=line.strip()
        if not line or line[0] in '#r': continue
        a,v=line.split(',')[:2]
        try:e.wr(int(a,16),int(v,16),4)
        except:pass
for fn in FNS:
    e=Emu()
    e.uc.mem_write(0xbb048, e.fw[0xbb045:0x134011])
    load_bases(e)
    e.wr(0x4069b4,0x40a1a8,4); e.wr(0x4069b0,0x40a1a8,4)
    hits=[]
    def on_w(uc,acc,a,sz,val,ud):
        if 0x4069a4<=a<=0x4069ac:
            hits.append((uc.reg_read(UC_ARM_REG_PC),a,val))
    e.uc.hook_add(UC_HOOK_MEM_WRITE,on_w)
    import sys as _s; print(f"testing {fn:#x}",flush=True); _s.stdout.flush()
    try: e.call(fn, maxinsn=120_000)
    except: pass
    cmds=[(pc,a,v) for pc,a,v in hits if a in (0x4069a8,) and 0xd0<=(v&0xff)<=0xfe]
    if hits:
        print(f"FUN_{fn:#07x}: staging writes={len(hits)} "+("CMD! "+str([(hex(pc),hex(a),hex(v&0xff)) for pc,a,v in cmds]) if cmds else ""))
