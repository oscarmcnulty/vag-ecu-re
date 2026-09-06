#!/usr/bin/env python3
# Decode the ESP8 8R0907379BG CAN routing tables into a full rx/tx message inventory.
# Names come from opendbc vw_mlb.dbc if present. Emits decode/can_inventory.csv.
#   run: python3 decode/can_routing_tables.py
import struct,re,csv,os
FW="firmware/8R0907379BG_0030.bin"; d=open(FW,'rb').read()
u16=lambda o:struct.unpack('>H',d[o:o+2])[0]; u32=lambda o:struct.unpack('>I',d[o:o+4])[0]
DBC=os.path.expanduser("~/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc")
names={}
if os.path.exists(DBC):
    for line in open(DBC,encoding='latin1'):
        m=re.match(r'\s*BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)',line)
        if m: names[int(m.group(1))]=(m.group(2),m.group(4))

# --- Table 1: msg-cfg 0xa9fc0 (RX): {canid, t, mode, routine, state_ram} stride 0x14 ---
msgcfg={}; o=0xa9fc0
for i in range(240):
    cid=u32(o); rt=u32(o+0xc); st=u32(o+0x10)
    if 0x400000<=st<0x40b000 and 0<cid<0x800: msgcfg[cid]=(rt,st)
    o+=0x14
# --- Table 2: can_id_array 0xafae0 (core powertrain/chassis cluster; incl ESP's own TX) ---
o=0xafae0; cluster=[]
while o<0xb0000:
    v=u32(o)
    if 0<v<0x800: cluster.append(v)
    else: break
    o+=4
cluster=set(cluster)
# --- Table 3: gateway forward table 0xb1da6 (6-byte {canid, target, flag}) ---
gw={}; o=0xb1da6
for i in range(80):
    cid=u16(o)
    if not (0<cid<0x800): break
    gw[cid]=u16(o+2); o+=6
# --- Table 4: HW mailbox 0xaea38 (handle<->mailbox) — RX filter hardware ---
mbx={}; o=0xaea38
for i in range(31):
    handle=u16(o+0xf); hw=u32(o); mbx.setdefault(handle,[]).append(hw&0xffff); o+=0x18

ESP_TX={0x100:'ESP_01',0x101:'ESP_02',0x103:'ESP_03',0x106:'ESP_05',0x11e:'ESP_08'}  # ESP composes/sends
allids=sorted(set(msgcfg)|cluster|set(gw))
with open("decode/can_inventory.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["canid","dbc_name","sender","dir","in_msgcfg","in_cluster","gw_target","routine","state_ram"])
    for c in allids:
        nm,snd=names.get(c,("",""))
        w.writerow([f"0x{c:03x}",nm,snd,"TX" if c in ESP_TX else "RX",
                    "Y" if c in msgcfg else "","Y" if c in cluster else "",
                    f"0x{gw[c]:x}" if c in gw else "",
                    f"0x{msgcfg[c][0]:x}" if c in msgcfg else "",
                    f"0x{msgcfg[c][1]:x}" if c in msgcfg else ""])
if __name__=="__main__":
    print(f"CAN-ids handled: {len(allids)} (msgcfg-RX {len(msgcfg)}, cluster {len(cluster)}, gateway {len(gw)})")
    print(f"DBC-named: {sum(1 for c in allids if c in names)}; RX routines: {sorted(set(hex(r) for r,_ in msgcfg.values()))}")
    print("ESP TX (composed):", ", ".join(f"{v}(0x{k:x})" for k,v in ESP_TX.items()))
    print("\nReceived longitudinal/brake messages:")
    for c in sorted(allids):
        nm=names.get(c,("",""))[0]
        if nm and any(k in nm for k in ("EPB","ACC","TSK")):
            print(f"  0x{c:03x} {nm}")
    print("NOT received (comfort-ACC): ACC_05(0x10d), ACC_02(0x30c), ACC_04(0x324)")
