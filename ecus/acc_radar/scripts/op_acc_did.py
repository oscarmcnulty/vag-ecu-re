#!/usr/bin/env python3
# op_acc_did.py -- read-only ReadDataByIdentifier (0x22) sweep of the ACC radar (0x0B),
# to discover every readable DID in the app session. READ-ONLY (only 0x22).
import sys, time
sys.path.insert(0, "/home/om/tools/VW_Flash")
from op_tp20_read2 import Raw, setup, Chan, txt

ACC = 0x0B
# (start, end_inclusive) bands to sweep
BANDS = [
    (0x0200, 0x02FF),   # VW measurement band (README flagged for raw-object discovery)
    (0xF100, 0xF1FF),   # identification
    (0x1000, 0x12FF),   # VW adaptation / measurement
    (0xF400, 0xF4FF),   # OBD standardized
    (0xF800, 0xF8FF),   # OBD standardized
    (0xFD00, 0xFFFF),   # VW / standardized high
]

def connect(raw):
    s = setup(raw, ACC)
    if not s: return None
    recv, send = s; c = Chan(raw, recv, send)
    if not c.params(): c.disconnect(); return None
    c.request(bytes([0x10, 0x89]))   # app session
    return c

def main():
    raw = Raw()
    try:
        c = connect(raw)
        if not c: print("no channel to 0x0B"); return
        total = sum(e - b + 1 for b, e in BANDS)
        print(f"sweeping {total} DIDs across {len(BANDS)} bands (app session)...\n", flush=True)

        hits = []          # (did, data)
        nrc_hist = {}
        noresp = 0
        run_noresp = 0     # consecutive no-resps -> channel likely dead
        done = 0
        for b, e in BANDS:
            for did in range(b, e + 1):
                r = c.request(bytes([0x22, did >> 8, did & 0xFF]), secs=0.12)
                done += 1
                if r is None:
                    noresp += 1; run_noresp += 1
                    if run_noresp >= 12:          # channel died -> reconnect
                        print(f"  [reconnecting @ {did:#06x} after {run_noresp} silent]", flush=True)
                        try: c.disconnect()
                        except Exception: pass
                        time.sleep(0.2)
                        nc = connect(raw)
                        if nc: c = nc; run_noresp = 0
                        else: print("  [reconnect failed, aborting]", flush=True); break
                    continue
                run_noresp = 0
                if r[0] == 0x62:
                    data = r[3:]
                    hits.append((did, data))
                    a = txt(data)
                    print(f"  DID {did:#06x}: {data.hex()}" + (f'  "{a}"' if a.strip() else ""), flush=True)
                elif r[0] == 0x7F:
                    nrc_hist[r[-1]] = nrc_hist.get(r[-1], 0) + 1
                else:
                    print(f"  DID {did:#06x}: unexpected {r.hex()}", flush=True)
            else:
                continue
            break
        try: c.disconnect()
        except Exception: pass

        print(f"\n==== {len(hits)} readable DIDs; no-resp={noresp} ====")
        print("negative-response NRC histogram:",
              {f'{k:#04x}': v for k, v in sorted(nrc_hist.items())})
        print("\nreadable DIDs:", [f'{d:#06x}' for d, _ in hits])
    finally:
        raw.close()

if __name__ == "__main__":
    main()
