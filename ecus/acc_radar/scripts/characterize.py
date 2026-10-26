import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/om/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np
from collections import Counter, defaultdict

SEG = sys.argv[1]
TARG = [0x311, 0x3e2, 0x63a, 0x63c, 0x63d, 0x21f, 0x600, 0x5a0, 0x514]
PHYS = {0, 1, 2}  # panda1 physical buses (128/130 = panda2 forwards)

rows = defaultdict(list)   # (addr,bus) -> [(t,bytes)]
cs = []  # (t, vEgo, aEgo, steer, brake, gas)
for m in LogReader(SEG):
    w = m.which()
    if w == "carState":
        try:
            C = m.carState
            cs.append((m.logMonoTime*1e-9, float(C.vEgo), float(C.aEgo),
                       float(C.steeringAngleDeg), 1.0 if C.brakePressed else 0.0,
                       float(getattr(C, "gas", 0.0))))
        except Exception as e:
            if not cs and len(rows)==0: print("carState err:", repr(e))
    elif w == "can":
        t = m.logMonoTime*1e-9
        for c in m.can:
            if c.address in TARG:
                rows[(c.address, c.src)].append((t, bytes(c.dat)))

cs = np.array(cs) if cs else np.zeros((0,6))
HAVE_CS = cs.shape[0] > 10
cst = cs[:,0] if HAVE_CS else np.array([0.0])
print(f"carState frames: {cs.shape[0]} (correlation {'ON' if HAVE_CS else 'OFF'})")
def nearest(t):
    k = np.searchsorted(cst, t); return min(max(k,0), len(cst)-1)

def ule(d, st, w):
    v = 0
    for i in range(w):
        b = st+i
        if b//8 >= len(d): return None
        v |= ((d[b//8]>>(b%8))&1)<<i
    return v

print(f"seg duration ~{cst[-1]-cst[0]:.0f}s\n")
for a in TARG:
    # native physical bus = the PHYS bus with most frames
    buses = {b: len(rows[(a,b)]) for (aa,b) in rows if aa==a}
    phys = {b:c for b,c in buses.items() if b in PHYS}
    if not phys:
        print(f"{a:#06x}: not on a physical bus (buses={buses})"); continue
    nb = max(phys, key=phys.get)
    r = rows[(a,nb)]
    dur = r[-1][0]-r[0][0] if len(r)>1 else 1
    rate = len(r)/max(dur,1e-3)
    L = min(len(x[1]) for x in r)
    arr = np.array([list(x[1][:L]) for x in r])
    dyn = [i for i in range(L) if len(set(arr[:,i].tolist()))>1]
    print(f"{a:#06x}: nativeBus={nb} buses={buses}  rate~{rate:.0f}Hz  len={L}B  dynBytes={dyn}")
    # correlate best 8/16-bit field with vehicle state
    T = np.array([x[0] for x in r]); best=None
    if not HAVE_CS:
        print(f"    (no carState; dyn byte ranges: " + ", ".join(f"b{i}:{arr[:,i].min()}-{arr[:,i].max()}" for i in dyn) + ")")
        continue
    for st in range(0, L*8-7):
        for wdt in (8,16):
            if st+wdt>L*8: continue
            v = np.array([ule(d,st,wdt) for _,d in r], float)
            if np.nanstd(v)<1e-6 or len(set(v.tolist()))<4: continue
            ks = [nearest(t) for t in T]
            for ci,cn in [(1,"vEgo"),(2,"aEgo"),(3,"steer"),(4,"brake"),(5,"gas")]:
                cv = cs[ks,ci]
                if cv.std()<1e-6: continue
                rr = np.corrcoef(v,cv)[0,1]
                if best is None or abs(rr)>abs(best[0]): best=(rr,cn,st,wdt,v.min(),v.max())
    if best:
        print(f"    best corr: {best[1]} r={best[0]:+.2f} (bit{best[2]}+{best[3]}, range {best[4]:.0f}..{best[5]:.0f})")
