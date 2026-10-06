import sys, struct
from capstone import *
from capstone.arm import *
BIN=sys.argv[1]; targets=set(int(x,16) for x in sys.argv[2:])
d=open(BIN,'rb').read(); CODE_HI=0xa2000
def w32(o): return struct.unpack('>I', d[o:o+4])[0]
md=Cs(CS_ARCH_ARM, CS_MODE_ARM|CS_MODE_BIG_ENDIAN); md.detail=True
# per-instruction linear scan with tiny register model (literal-pool loads + mov reg,reg)
regs={}  # reg -> concrete addr (from ldr rX,[pc,#imm]) ; cleared on other defs
hits=[]
cur_fn=0
for off in range(0,CODE_HI,4):
    b=d[off:off+4]
    ins=next(md.disasm(b, off), None)
    if ins is None:
        regs={}; continue
    m=ins.mnemonic; ops=ins.op_str
    # detect function boundary heuristically: push {...lr}
    if m=="push" and "lr" in ops:
        regs={}; cur_fn=off
    # ldr rD,[pc,#imm] -> literal value
    if m=="ldr" and "[pc" in ops:
        d0=ins.operands
        if len(d0)>=2 and d0[0].type==ARM_OP_REG and d0[1].type==ARM_OP_MEM:
            rd=ins.reg_name(d0[0].reg)
            memop=d0[1].mem
            imm=memop.disp
            litoff=(off & ~3)+8+imm
            if 0<=litoff<len(d)-4:
                regs[rd]=w32(litoff)
        continue
    # ldr/str [rN{,#off}] : check target
    if m in ("ldr","ldrh","ldrsh","ldrb","str","strh","strb"):
        d0=ins.operands
        if len(d0)>=2 and d0[1].type==ARM_OP_MEM:
            base=ins.reg_name(d0[1].mem.base) if d0[1].mem.base else None
            disp=d0[1].mem.disp
            if base in regs:
                addr=regs[base]+disp
                if addr in targets:
                    kind="WRITE" if m.startswith("str") else "read"
                    hits.append((addr,kind,off,cur_fn,f"{m} {ops}"))
        # if this instr defines a reg via load, drop its symbolic addr unless pc-load (handled above)
        if m.startswith("ld"):
            d0=ins.operands
            if d0 and d0[0].type==ARM_OP_REG:
                rn=ins.reg_name(d0[0].reg)
                regs.pop(rn,None)
        continue
    # mov rD,rS propagate; any other def clears dest
    if m=="mov":
        d0=ins.operands
        if len(d0)==2 and d0[0].type==ARM_OP_REG and d0[1].type==ARM_OP_REG:
            rd=ins.reg_name(d0[0].reg); rs=ins.reg_name(d0[1].reg)
            if rs in regs: regs[rd]=regs[rs]
            else: regs.pop(rd,None)
            continue
    # generic: clear any dest reg (first operand if reg & writes)
    d0=ins.operands
    if d0 and d0[0].type==ARM_OP_REG and m not in ("cmp","cmn","tst","teq","push","pop","b","bl","bx"):
        regs.pop(ins.reg_name(d0[0].reg),None)
for addr,kind,off,fn,txt in hits:
    print(f"0x{addr:08x} {kind:5s} @0x{off:06x} (fn~0x{fn:06x}): {txt}")
