#!/usr/bin/env python3
"""Decode ESP/TSK/ACC CAN signals from openpilot rlog segments.

Usage:  OPENPILOT=/path/to/openpilot ./analyze_decel_fault.py seg6.zst seg7.zst

Needs an openpilot checkout for cereal/log.capnp (set $OPENPILOT, default ~/openpilot)
and one or more decompressible rlog.zst segments from your own drives.
"""
import capnp, zstandard, sys, os
capnp.remove_import_hook()
OPENPILOT = os.environ.get('OPENPILOT', os.path.expanduser('~/openpilot'))
evt = capnp.load(os.path.join(OPENPILOT, 'cereal', 'log.capnp'))

SEGS = sys.argv[1:]
if not SEGS:
    sys.exit(__doc__)

def bits(dat, start, length, scale=1.0, off=0.0):
    v = int.from_bytes(dat, 'little')
    raw = (v >> start) & ((1 << length) - 1)
    return raw * scale + off

# ESP_05 (262) signals
def esp05(dat):
    return dict(
        Verz_TSK_aktiv = int(bits(dat,27,1)),
        Konsistenz_TSK = int(bits(dat,29,1)),
        ECD_Fehler     = int(bits(dat,32,1)),
        ECD_n_verf     = int(bits(dat,33,1)),
        Fahrer_bremst  = int(bits(dat,26,1)),
        Status_Bremsdr = int(bits(dat,61,1)),
        Bremsdruck     = round(bits(dat,16,10,0.3,-30),1),
    )
def tsk02(dat):
    return dict(
        TSK_Verz_Anf = round(bits(dat,56,8,0.024,-3.984),3),
        TSK_Status   = int(bits(dat,16,2)),
        TSK_Radbrems = int(bits(dat,40,12,8)),
        TSK_Anhalten = int(bits(dat,12,1)),
    )
def acc01(dat):
    return dict(Sollbeschl = round(bits(dat,24,11,0.005,-7.22),3),
               Status_ACC = int(bits(dat,60,3)))

t0 = None
rows = []  # (t, dict)
last = {}
for seg in SEGS:
    raw = zstandard.ZstdDecompressor().decompress(open(seg,'rb').read(), max_output_size=500_000_000)
    for e in evt.Event.read_multiple_bytes(raw):
        t = e.logMonoTime
        w = e.which()
        if w == 'can':
            for p in e.can:
                if p.address==262: last.update({'esp_'+k:v for k,v in esp05(p.dat).items()}); last['esp_src']=p.src
                elif p.address==268: last.update({'tsk_'+k:v for k,v in tsk02(p.dat).items()}); last['tsk_src']=p.src
                elif p.address==270: last['TSK04_Status']=int(bits(p.dat,62,2)); last['tsk04_src']=p.src
                elif p.address==265: last.update({'acc_rx_'+k:v for k,v in acc01(p.dat).items()})
        elif w == 'sendcan':
            for p in e.sendcan:
                if p.address==265: last.update({'acc_tx_'+k:v for k,v in acc01(p.dat).items()})
        elif w == 'carControl':
            last['cmd_accel']=round(e.carControl.actuators.accel,3)
            last['cc_enabled']=int(e.carControl.enabled)
            last['cc_longActive']=int(e.carControl.longActive)
        elif w == 'carState':
            cs=e.carState
            last['vEgo']=round(cs.vEgo,2); last['aEgo']=round(cs.aEgo,3)
            last['cru_en']=int(cs.cruiseState.enabled); last['cru_avail']=int(cs.cruiseState.available)
        else:
            continue
        if t0 is None: t0=t
        rows.append(((t-t0)/1e9, dict(last), seg[-11:-9]))

print(f'rows={len(rows)}  duration={rows[-1][0]:.1f}s')
# find min commanded accel and ESP decel-status transitions
import math
mn=1e9; mnrow=None
trans=[]
prev={}
for tt,d,sg in rows:
    ca=d.get('cmd_accel')
    if ca is not None and ca<mn: mn=ca; mnrow=(tt,sg,ca)
    for k in ('esp_Konsistenz_TSK','esp_ECD_Fehler','esp_ECD_n_verf','esp_Verz_TSK_aktiv','cru_en'):
        if k in d and prev.get(k)!=d[k]:
            trans.append((round(tt,2),sg,k,prev.get(k),d[k], d.get('cmd_accel'), d.get('acc_tx_Sollbeschl'), d.get('vEgo')))
            prev[k]=d[k]
print(f'\nMIN commanded accel = {mn} at t={mnrow[0]:.2f}s seg{mnrow[1]}')
print('\n=== transitions (t, seg, signal, from->to, cmd_accel, acc_tx, vEgo) ===')
for r in trans:
    print(f't={r[0]:8.2f} seg{r[1]} {r[2]:20s} {str(r[3]):>5}->{str(r[4]):<5} cmd={r[5]} tx={r[6]} v={r[7]}')

# TSK04 status transitions
prevs=None
print('\n=== TSK_04.TSK_Status_GRA_ACC_02 transitions (0=noACC 1=active 2=override 3=FAULT) ===')
for tt,d,sg in rows:
    s=d.get('TSK04_Status')
    if s is not None and s!=prevs:
        print(f't={tt:8.2f} seg{sg} TSK04_Status {prevs}->{s}  cmd={d.get("cmd_accel")} tx={d.get("acc_tx_Sollbeschl")} v={d.get("vEgo")}')
        prevs=s

# Full-resolution window around the event
print('\n=== WINDOW 53.0-55.5s: t cmd tx TSK04 espVerz espKons ECDerr ECDnv TSK02verz v ===')
lastprint=-1
for tt,d,sg in rows:
    if 53.0<=tt<=55.5 and tt-lastprint>=0.04:
        lastprint=tt
        print(f't={tt:7.3f} cmd={str(d.get("cmd_accel")):>6} tx={str(d.get("acc_tx_Sollbeschl")):>6} '
              f'TSK04={d.get("TSK04_Status")} Verz={d.get("esp_Verz_TSK_aktiv")} Kons={d.get("esp_Konsistenz_TSK")} '
              f'ECDe={d.get("esp_ECD_Fehler")} ECDnv={d.get("esp_ECD_n_verf")} '
              f'TSK02v={d.get("tsk_TSK_Verz_Anf")} v={d.get("vEgo")}')
