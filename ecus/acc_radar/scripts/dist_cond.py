import warnings; warnings.filterwarnings("ignore")
from openpilot.tools.lib.logreader import LogReader
from collections import defaultdict
def ule(d,st,w):
    v=0
    for i in range(w):
        b=st+i
        if b//8>=len(d): return None
        v|=((d[b//8]>>(b%8))&1)<<i
    return v
SEGS=[0,3,4,5,7,9,10]
tab=defaultdict(lambda:[0,0,0,0])  # status -> [real, sentinel, relobj1, sentinel_but_modellead]
for s in SEGS:
    p=f"/home/om/vag-ecu-re/captures/00000051--957a33a9e7/seg{s}.rlog.zst"
    acc_status=[0]; lead=[0.0]
    for m in LogReader(p):
        w=m.which()
        if w=="modelV2":
            try: lead[0]=float(m.modelV2.leadsV3[0].prob)
            except Exception: pass
        elif w=="can":
            for c in m.can:
                if c.src==1 and c.address==0x10e and len(c.dat)>=8:
                    acc_status[0]=(c.dat[7]&0xC0)>>6
                elif c.src==2 and c.address==0x30c and len(c.dat)>=8:
                    d=bytes(c.dat); ai=ule(d,24,10); rel=ule(d,46,2); st=acc_status[0]
                    real = ai is not None and ai<1000
                    tab[st][0 if real else 1]+=1
                    if rel==1: tab[st][2]+=1
                    if (not real) and lead[0]>0.7: tab[st][3]+=1
names={0:"off/avail",1:"engaged",2:"eng+ovr",3:"fault"}
print("TSK_04 ACC status  realDist  sentinel  relObj=1  sentinel_but_modelLead")
for st in sorted(tab):
    r,sen,rel,sl=tab[st]
    print(f"  {st} {names.get(st,''):10} {r:8} {sen:8} {rel:8} {sl:8}")
