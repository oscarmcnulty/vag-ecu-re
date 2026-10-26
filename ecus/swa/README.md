# Side Assist / blind-spot module (SWA Master, J769, VCDS address 3C) — B8 Q5

Read-only identity + DTC readout over the Linux Openport (`~/tools/VW_Flash/op_swa_dtc.py`,
UDS req **0x74E** / resp **0x7B8**, gateway-routed from OBD pins 6/14). Read on-car 2026-10-15.

## Identity (UDS 0x22, default session, no security needed)
| DID | Value |
|-----|-------|
| F187 VW part no | **8T0907566B** |
| F191 HW part no | 8T0907566B, HW version **H04** |
| F189 SW version | **0060** |
| F18A supplier | Hella Lippstadt |
| F197 system name | SWA Master |
| F1AA | J769 |
| F19E / F1A2 ODX | **EV_LaneChangAssis** / 001020 |
| F1A1 dataset | 0019 |
| F18C serial | 0310171990 |
| F17C FAZIT | HLH-45F26.06.134CA22418 |
| F1DF prog status | 0x40 |
| F190 VIN | NRC 0x31 (not stored in this module) |

Search keys for the flash container: box code `8T0907566B`, SW `0060`, ODX `EV_LaneChangAssis`.
Note: Side Assist is a master+slave pair; only the master (this unit) is diag-addressable.
The slave sensor (8T0907568x family) is not visible over UDS.

## Service support (0x19)
Supported: 0x19 0x02 (by status mask), 0x19 0x06 (ext data by DTC).
NRC 0x12 (sub-function not supported): 0x19 0x01, 0x19 0x04, 0x19 0x0A.
Mask 0x08 / 0x2F return the same two DTCs; masks 0x04 / 0x01 / 0x80 return none
(nothing currently failing or pending at read time).

## Stored DTCs (both status 0x08 = confirmed, not active now)
| UDS DTC | VCDS code | Likely label (VCDS convention, unverified w/o .clb) | prio | occurrences | last km | last time (UTC) |
|---------|-----------|------------------------------------------------------|------|-------------|---------|-----------------|
| 0B3100  | 02865 / type 00 | Sensor for Lane Change Assist, driver side (G568)    | 6 | 39 | 236 601 | 2026-04-23 00:04 |
| 0B3200  | 02866 / type 00 | Sensor for Lane Change Assist, passenger side (G569) | 6 | 14 | 240 497 | 2026-06-06 11:23 |

Raw 0x19 0x06 replies:
```
59 06 0b3100 08 | 01 06 27 | 02 72 03 9c 39 00 00 69 e9 61 f3
59 06 0b3200 08 | 01 06 0e | 02 6b 03 ab 71 00 00 6a 24 03 1c
```
Record 01 = [priority][occurrence counter]; record 02 = [?][3-byte km][00 00][4-byte Unix epoch]
(same layout as the Simos8.5 ext record, except the leading byte is 0x72/0x6b here, not 0xFF —
meaning unknown). km and date order consistently (earlier date = lower km). Only records 01/02
are present (no environmental snapshot record on this module).
