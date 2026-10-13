# CAN Mailbox Inventory -- ESP8 ABS (8R0907379BG)

TI TMS470R1B1M, dual HECC (High-End CAN Controller), cross-referenced with
`vw_mlb.dbc` from opendbc.

## HECC Architecture

The TMS470R1B1M has two independent HECC modules, each with 32 mailboxes of 16 bytes:

| Module | Control Regs | Mailbox RAM | Firmware Label | Bus Function |
|--------|-------------|-------------|----------------|--------------|
| HECC1 (Module A) | 0xFFF7E800 | 0xFFF7E400-0xFFF7E5FF | `hecc_module_a`, ctrl-sel 1 | Chassis/sensor CAN (pins 37H/24L on T38a, OBD 3/11) |
| HECC2 (Module B) | 0xFFF7EA00 | 0xFFF7E600-0xFFF7E7FF | `hecc_module_b`, ctrl-sel 2 | Vehicle/diag CAN (pins 26/14 on T38a, OBD 6/14) |

Controller selection in `rx_mailbox_resolver` (0x501d4): param_2=1 selects HECC1, param_2=2
selects HECC2. The `can_rx_isr` (0x8f708) dispatches based on which controller raised the
interrupt.

### Module A -- Chassis/Sensor CAN

- 500 kbps, private bus internal to the vehicle's ESP/ABS/sensor cluster
- Boots dormant; heartbeat 0x060 begins only when bus traffic is detected
- Software acceptance filter at 0xafae0 covers 225 IDs (range 0x001-0x258)
- Carries wheel speed sensor data, yaw rate, lateral accel, steering angle, brake pressure
  -- all internal sensor traffic not visible on the vehicle CAN
- CanNm path uses IpduM container 0x36E (NM sub-PDU header 0x0600)

### Module B -- Vehicle/Diag CAN

- Standard vehicle CAN bus (500 kbps), connected to the gateway
- Always operational when powered; carries the ESP's 5 application TX messages
- Hardware mailbox table at 0xaea38 (62 records, stride 0x18) -- the definitive per-mailbox
  controller assignment
- Hosts TP2.0+KWP2000 diagnostics (setup on 0xC0/0x200, channel 0x4A3/0x300, resp 0x203)
- ISO-TP mailboxes 0x7E0 present but the module uses KWP2000 not UDS

### Module B TX Messages (bench-confirmed operational set)

| CAN ID | DBC Name | DLC | Notes |
|--------|----------|-----|-------|
| 0x100 | ESP_01 | 8 | Vehicle speed (ESP_v_Signal), ESP/ABS/ASR state |
| 0x101 | ESP_02 | 8 | Yaw rate, lat/long accel (relayed from sensor CAN) |
| 0x103 | ESP_03 | 8 | 4 individual wheel speeds VL/VR/HL/HR |
| 0x106 | ESP_05 | 8 | Brake pressure (ESP_Bremsdruck), ECD state |
| 0x11E | ESP_08 | 8 | Additional ESP status |
| 0x08A | -- | 8 | Internal status (no DBC match) |
| 0x08B | -- | 8 | Internal status (no DBC match) |
| 0x308 | ESP_04 | 8 | Extended ESP data |
| 0x392 | ESP_07_FR | 8 | Funktionsrahmen ESP data |
| 0x632 | -- | 8 | Internal (no DBC match) |
| 0x64A | -- | 8 | Internal (no DBC match) |
| 0x6C3 | -- | 7 | NM frame |

### Module A TX Messages

| CAN ID | Notes |
|--------|-------|
| 0x060 | Heartbeat (traffic-triggered wake indicator) |
| 0x08A | Also appears on Module A (slot 31) |

---

## Hardware Mailbox Table (0xAEA38) -- Definitive HECC Assignment

62 records decoded from firmware. Each record maps a hardware mailbox slot to one or more
CAN IDs with mask-based acceptance. Mailbox address encodes the slot: `base + slot*0x10`.

### HECC1 (Module A) Mailboxes

| Slot | Mbox Addr | CAN ID | Handler | DBC Name | Notes |
|------|-----------|--------|---------|----------|-------|
| 0 | 0xE400 | 0x061 | 0x00000 | -- | Sensor CAN, no handler (data-only) |
| 1 | 0xE410 | 0x065 | 0x00000 | -- | Sensor CAN |
| 2 | 0xE420 | 0x071 | 0x00000 | -- | Sensor CAN |
| 3 | 0xE430 | 0x072 | 0x00000 | -- | Sensor CAN |
| 4 | 0xE440 | 0x066 | 0x00000 | -- | Sensor CAN |
| 5 | 0xE450 | 0x661 | 0x00000 | Anhaenger_01 | Trailer message |
| 6 | 0xE460 | 0x604 | 0x00000 | -- | Sensor CAN |
| 14 | 0xE4E0 | 0x7E8 | 0x00000 | ISO_MO_01_Resp | Motor ECU ISO-TP response (passthrough) |
| 15 | 0xE4F0 | 0x7E1 | 0x00000 | ISO_Getriebe_01_Req | Gearbox ISO-TP request (passthrough) |
| 29 | 0xE5D0 | 0x6FF | 0x0EA7D | -- | Catch-all / broadcast listener |
| 30 | 0xE5E0 | 0x060 | 0x00000 | -- | Heartbeat TX mailbox |
| 31 | 0xE5F0 | 0x08A | 0x00000 | -- | Internal status |

### HECC2 (Module B) Mailboxes

| Slot | Mbox Addr | CAN IDs | Handler | DBC Name(s) | Notes |
|------|-----------|---------|---------|-------------|-------|
| 0 | 0xE600 | 0x6B7, 0x6B8, 0x6B4, 0x6D9 | 0x127ED | Kombi_02/03, VIN_01, NMH_EPB | Diag/NM mailbox (mask-match) |
| 1 | 0xE610 | 0x6C0, 0x6D0, 0x6C7, 0x110 | 0x12771 | NMH_Gateway, --, --, radar(dormant) | NM + dormant radar ID |
| 2 | 0xE620 | 0x641, 0x062 | 0x1274D | Motor_Code_01, -- | Motor code + sensor |
| 3 | 0xE630 | 0x39C | 0x00000 | Gateway_05 | Gateway status |
| 4 | 0xE640 | 0x395, 0x441 | 0x12729 | --, Getriebe_04 | NM-range IDs |
| 5 | 0xE650 | 0x040 | 0x00000 | Airbag_01 | Airbag data |
| 6 | 0xE660 | 0x10C | 0x00000 | TSK_02 | Torque request 2 |
| 7 | 0xE670 | 0x102, 0x117 | 0x12701 | Getriebe_03, ACC_10 | Gearbox + AEB/ANB frame |
| 8 | 0xE680 | 0x11D, 0x114 | 0x126DD | LH_EPS_02, Motor_10 | EPS + motor data |
| 9 | 0xE690 | 0x105, 0x104, 0x086 | 0x126BB | Motor_03, EPB_01, LWI_01 | Key RX messages |
| 10 | 0xE6A0 | 0x085, 0x09F | 0x127AD | SCU_01, LH_EPS_03 | SCU + EPS |
| 11 | 0xE6B0 | 0x4A3 | 0xA43F5 | -- | TP2.0 channel handler |
| 12 | 0xE6C0 | 0x203 | 0xA43F5 | -- | TP2.0 response (logical addr 0x03=ABS) |
| 13 | 0xE6D0 | 0x6FF | 0x00000 | -- | Broadcast / catch-all |
| 14 | 0xE6E0 | 0x7E9 | 0x00000 | ISO_Getriebe_01_Resp | Gearbox ISO-TP response |
| 15 | 0xE6F0 | 0x200, 0x019 | 0x9D4E3 | TPS_Tester, -- | TP2.0 setup + internal |
| 16 | 0xE700 | 0x6FF | 0x9D4EB | -- | Broadcast handler |
| 17 | 0xE710 | 0x082 | 0x00000 | Getriebe_01 | Gearbox status 1 |
| 18 | 0xE720 | 0x080 | 0x00000 | Motor_01 | Motor status 1 |
| 19 | 0xE730 | 0x081 | 0x00000 | Motor_02 | Motor status 2 |
| 20 | 0xE740 | 0x084 | 0x00000 | ESP_06 | ESP self-report (loopback?) |
| 21 | 0xE750 | 0x6FF, 0x6C3 | 0x126A9 | -- | NM + broadcast |
| 22 | 0xE760 | 0x394 | 0x9B369 | -- | Internal |
| 23 | 0xE770 | 0x632, 0x64A | 0x00000 | -- | Internal TX status |
| 24 | 0xE780 | 0x308 | 0x00000 | ESP_04 | Extended ESP data (TX) |
| 25 | 0xE790 | 0x392, 0x11E | 0x12697 | ESP_07_FR, ESP_08 | ESP data (TX) |
| 26 | 0xE7A0 | 0x101 | 0x0EA73 | ESP_02 | TX mailbox |
| 27 | 0xE7B0 | 0x103 | 0x0EA9B | ESP_03 | TX mailbox |
| 28 | 0xE7C0 | 0x106 | 0x0EA91 | ESP_05 | TX mailbox |
| 29 | 0xE7D0 | 0x100 | 0x0EA87 | ESP_01 | TX mailbox |
| 30 | 0xE7E0 | 0x08B | 0x0EAB1 | -- | TX mailbox, internal |
| 31 | 0xE7F0 | 0x7E0 | 0x0EA69 | ISO_MO_01_Req | ISO-TP request (passthrough?) |

---

## Complete CAN ID Inventory -- Cross-Referenced with vw_mlb.dbc

335 CAN IDs from the firmware configuration tables. Direction from the ESP's perspective.
HECC module assignment: **B** = confirmed in HW mailbox table 0xAEA38; **A** = confirmed
in HW mailbox table; **A(sw)** = in module-A software acceptance filter @0xafae0 but no
individual HW mailbox record; **--** = present in firmware config but bus not individually
confirmed.

### ESP TX Messages (Module B vehicle CAN)

| CAN ID | DBC Name | DBC Sender | Dir | HECC | DLC | Notes |
|--------|----------|------------|-----|------|-----|-------|
| 0x060 | -- | -- | TX | A | 8 | Heartbeat (module A, traffic-triggered) |
| 0x08A | -- | -- | TX | A+B | 8 | Internal status, both controllers |
| 0x08B | -- | -- | TX | B | 8 | Internal status |
| 0x100 | ESP_01 | Gateway_D4C7 | TX | B | 8 | Vehicle speed (ESP_v_Signal), ESP/ABS/ASR state |
| 0x101 | ESP_02 | Gateway_D4C7 | TX | B | 8 | Yaw rate, lat/long accel (relayed from sensor CAN) |
| 0x103 | ESP_03 | Gateway_D4C7 | TX | B | 8 | 4 individual wheel speeds VL/VR/HL/HR |
| 0x106 | ESP_05 | Gateway_D4C7 | TX | B | 8 | Brake pressure (ESP_Bremsdruck), ECD state |
| 0x11E | ESP_08 | Vector__XXX | TX | B | 8 | Additional ESP status |
| 0x308 | ESP_04 | Gateway_D4C7 | TX | B | 8 | Extended ESP data |
| 0x392 | ESP_07_FR | Gateway_D4C7 | TX | B | 8 | Funktionsrahmen ESP data |
| 0x632 | -- | -- | TX | B | 8 | Internal (no DBC match) |
| 0x64A | -- | -- | TX | B | 8 | Internal (no DBC match) |
| 0x6C3 | -- | -- | TX | B | 7 | NM frame |

### ESP RX Messages -- DBC-Matched (Module B vehicle CAN)

These CAN IDs appear in both the ESP firmware config and `vw_mlb.dbc`.

| CAN ID | DBC Name | DBC Sender | Dir | HECC | DLC | GW Target | Notes |
|--------|----------|------------|-----|------|-----|-----------|-------|
| 0x040 | Airbag_01 | Airbag_D4 | RX | B | 8 | -- | Airbag status |
| 0x080 | Motor_01 | Motor_EDC17_D4 | RX | B | 8 | -- | Engine speed, torque |
| 0x081 | Motor_02 | Motor_EDC17_D4 | RX | B | 8 | -- | Engine status |
| 0x082 | Getriebe_01 | Getriebe_AL551_951_D4_C7 | RX | B | 8 | -- | Gearbox status 1 |
| 0x083 | Getriebe_02 | Getriebe_AL551_951_D4_C7 | RX | B | 8 | -- | Gearbox status 2 |
| 0x084 | ESP_06 | ESP_D4 | RX | B | 8 | -- | ESP self-report / loopback |
| 0x085 | SCU_01 | SCU_D4 | RX | B | 8 | -- | Steering column unit |
| 0x086 | LWI_01 | LWS_D4 | RX | B | 8 | -- | Steering angle sensor |
| 0x09F | LH_EPS_03 | XXX | RX | B | 8 | -- | EPS status 3 |
| 0x102 | Getriebe_03 | Getriebe_AL551_951_D4_C7 | RX | B | 8 | 0x304 | Gearbox request (GW routed) |
| 0x104 | EPB_01 | EPB_D4 | RX | B | 8 | -- | Electric parking brake |
| 0x105 | Motor_03 | Motor_EDC17_D4 | RX | B | 8 | -- | Engine data 3 |
| 0x107 | Motor_04 | Motor_EDC17_D4 | RX | B | 8 | -- | Engine data 4 |
| 0x109 | ACC_01 | Gateway_B8 | RX | B(sw) | 8 | -- | ACC control request |
| 0x10B | LS_01 | Gateway_D4C7 | RX | B(sw) | 4 | -- | Light sensor |
| 0x10C | TSK_02 | XXX | RX | B | 8 | -- | Torque structure request 2 |
| 0x10D | ACC_05 | Gateway_D4C7 | RX | B(sw) | 8 | -- | ACC extended |
| 0x111 | TSK_05 | Motor_EDC17_D4 | RX | B(sw) | 8 | -- | Torque structure 5 |
| 0x114 | Motor_10 | Motor_EDC17_D4 | RX | B | 8 | -- | Motor data 10 |
| 0x117 | ACC_10 | XXX | RX | B | 8 | -- | **AEB/ANB frame** (key for openpilot) |
| 0x11D | LH_EPS_02 | Gateway_D4C7 | RX | B | 8 | -- | EPS torque/angle |
| 0x126 | HCA_01 | Frontsensorik | RX | B(sw) | 8 | -- | Heading control assist |
| 0x1E0 | CCP_MO_CRO_01 | Gateway_D4C7 | RX | -- | 8 | -- | CCP motor command |
| 0x1E1 | CCP_MOS_CRO_01 | Gateway_D4C7 | RX | -- | 8 | -- | CCP motor slave command |
| 0x1E8 | CCP_MO_DTO_01 | Motor_EDC17_D4 | RX | -- | 8 | -- | CCP motor data |
| 0x200 | TPS_Tester | Gateway_D4C7 | RX | B | 7 | -- | TP2.0 setup broadcast |
| 0x39C | Gateway_05 | Gateway_D4C7 | RX | B | 8 | -- | Gateway config / clock |
| 0x441 | Getriebe_04 | Getriebe_AL551_951_D4_C7 | RX | B | 8 | -- | NM-range, gearbox |
| 0x641 | Motor_Code_01 | Motor_EDC17_D4 | RX | B | 8 | -- | Motor calibration ID |
| 0x661 | Anhaenger_01 | Gateway_D4C7 | RX | A | 3 | -- | Trailer status (sensor CAN) |
| 0x6B4 | VIN_01 (DBC) | Gateway_D4C7 | RX | B | 8 | -- | **Diag request ID** in this ECU |
| 0x6B7 | Kombi_02 | Gateway_D4C7 | RX | B | 8 | -- | Instrument cluster 2 |
| 0x6B8 | Kombi_03 | Gateway_D4C7 | RX | B | 8 | -- | **Diag response ID** in this ECU |
| 0x6C0 | NMH_Gateway | Gateway_D4C7 | RX | B | 7 | -- | Network management |
| 0x6D9 | NMH_EPB | EPB_D4 | RX | B | 7 | -- | EPB network management |
| 0x7E0 | ISO_MO_01_Req | Gateway_D4C7 | RX | B | 8 | -- | ISO-TP motor diag req |
| 0x7E1 | ISO_Getriebe_01_Req | Gateway_D4C7 | RX | A | 8 | -- | ISO-TP gearbox diag req |
| 0x7E8 | ISO_MO_01_Resp | Motor_EDC17_D4 | RX | A | 8 | -- | ISO-TP motor diag resp |
| 0x7E9 | ISO_Getriebe_01_Resp | Getriebe_AL551_951_D4_C7 | RX | B | 8 | -- | ISO-TP gearbox resp |

### ESP RX Messages -- NOT in vw_mlb.dbc (Internal/Proprietary)

CAN IDs present in the ESP firmware config tables but absent from `vw_mlb.dbc`. These are
primarily sensor-CAN internal messages or ESP-specific proprietary frames.

#### Sensor CAN IDs (Module A, low-range 0x001-0x0FF)

These IDs are on the private chassis/sensor CAN bus. They carry raw sensor data from the
ESP's own sensor cluster (wheel speed sensors, yaw rate, lateral accel, pressure sensors).
None appear in the vehicle-bus DBC. IDs marked `in_msgcfg=Y` have timeout/handler config
in the `can_msg_cfg_table` (0xa9fc0).

| CAN ID | Dir | in_msgcfg | in_cluster | Routine | State RAM | Probable Function |
|--------|-----|-----------|------------|---------|-----------|-------------------|
| 0x002 | RX | Y | -- | 0x91898 | 0x4048D8 | Sensor data |
| 0x003 | RX | -- | Y | -- | -- | Sensor data |
| 0x006 | RX | -- | Y | -- | -- | Sensor data |
| 0x00B | RX | -- | Y | -- | -- | Sensor data |
| 0x00E | RX | Y | -- | 0x9036C | 0x404918 | Sensor data |
| 0x021 | RX | -- | Y | -- | -- | Sensor data |
| 0x031 | RX | Y | -- | 0x8E3EC | 0x404868 | Wheel speed group |
| 0x035 | RX | Y | -- | 0x8E3EC | 0x404870 | Wheel speed group |
| 0x036 | RX | Y | -- | 0x8E3EC | 0x40487C | Wheel speed group |
| 0x037 | RX | Y | -- | 0x8E3EC | 0x404878 | Wheel speed group |
| 0x038 | RX | Y | -- | 0x8E3EC | 0x40486C | Wheel speed group |
| 0x039 | RX | Y | -- | 0x8E3EC | 0x404880 | Wheel speed group |
| 0x03A | RX | Y | -- | 0x8E3EC | 0x404874 | Wheel speed group |
| 0x045 | RX | -- | Y | -- | -- | Sensor data |
| 0x049 | RX | -- | Y | -- | -- | Sensor data |
| 0x04D | RX | -- | Y | -- | -- | Sensor data |
| 0x04F | RX | Y | -- | 0x908D4 | 0x4048FC | Sensor data |
| 0x052 | RX | -- | Y | -- | -- | Sensor data |
| 0x053 | RX | Y | -- | 0x8E3EC | 0x404864 | Sensor/wheel data |
| 0x054 | RX | -- | Y | -- | -- | Sensor data |
| 0x061 | RX | -- | Y | -- | -- | Sensor CAN (HW mbox on Module A) |
| 0x065 | RX | -- | Y | -- | -- | Sensor CAN (HW mbox on Module A) |
| 0x066 | RX | -- | Y | -- | -- | Sensor CAN (HW mbox on Module A) |
| 0x067 | RX | -- | Y | -- | -- | Sensor data |
| 0x068 | RX | -- | Y | -- | -- | Sensor data |
| 0x069 | RX | -- | Y | -- | -- | Sensor data |
| 0x06B | RX | -- | Y | -- | -- | Sensor data |
| 0x06C | RX | -- | Y | -- | -- | Sensor data |
| 0x06D | RX | -- | Y | -- | -- | Sensor data |
| 0x06F | RX | Y | -- | 0x9036C | 0x404910 | Sensor data |
| 0x070 | RX | -- | Y | -- | -- | Sensor data |
| 0x071 | RX | -- | Y | -- | -- | Sensor CAN (HW mbox on Module A) |
| 0x072 | RX | -- | Y | -- | -- | Sensor CAN (HW mbox on Module A) |
| 0x074 | RX | -- | Y | -- | -- | Sensor data |
| 0x075 | RX | -- | Y | -- | -- | Sensor data |
| 0x076 | RX | -- | Y | -- | -- | Sensor data |
| 0x078 | RX | -- | Y | -- | -- | Sensor data |
| 0x07B | RX | -- | Y | -- | -- | Sensor data |
| 0x090 | RX | -- | Y | -- | -- | Sensor data |
| 0x092 | RX | -- | Y | -- | -- | Sensor data |
| 0x093 | RX | Y | -- | 0x91898 | 0x4048E0 | Sensor data |
| 0x094 | RX | Y | -- | 0x9036C | 0x404908 | Sensor data |
| 0x096 | RX | -- | Y | -- | -- | Sensor data |
| 0x098 | RX | Y | -- | 0x8E3EC | 0x404894 | Sensor data |
| 0x099 | RX | Y | -- | 0x8E3EC | 0x404890 | Sensor data |
| 0x09A | RX | Y | -- | 0x8E3EC | 0x404898 | Sensor data |
| 0x09B | RX | -- | Y | -- | -- | Sensor data |
| 0x09C | RX | Y | -- | 0x91898 | 0x4048E4 | Sensor data |
| 0x09E | RX | -- | Y | -- | -- | Sensor data |
| 0x0A3 | RX | -- | Y | -- | -- | Sensor data |
| 0x0A4 | RX | -- | Y | -- | -- | Sensor data |
| 0x0A5 | RX | -- | Y | -- | -- | Sensor data |
| 0x0A7 | RX | -- | Y | -- | -- | Sensor data |
| 0x0B3 | RX | -- | Y | -- | -- | Sensor data |

#### Vehicle CAN IDs not in DBC (Module B)

These IDs are in the firmware config for the vehicle CAN but have no match in `vw_mlb.dbc`.
They are likely variant-specific, proprietary, or belong to a different DBC version.

| CAN ID | Dir | in_msgcfg | in_cluster | GW Target | Routine | Notes |
|--------|-----|-----------|------------|-----------|---------|-------|
| 0x108 | RX | -- | Y | -- | -- | Between Motor_04 and ACC_01 |
| 0x10A | RX | -- | Y | -- | -- | TSK_01 (per existing label; not in vw_mlb.dbc) |
| 0x110 | RX | -- | Y | -- | -- | Radar/pre-fill (dormant), HW mbox on Module B |
| 0x112 | RX | -- | Y | -- | -- | Unknown |
| 0x113 | RX | -- | Y | -- | -- | Unknown |
| 0x115 | RX | -- | Y | -- | -- | Unknown |
| 0x116 | RX | -- | Y | -- | -- | Unknown |
| 0x11C | RX | Y | -- | -- | 0x91898 | Unknown |
| 0x11F | RX | Y | -- | -- | 0x8E3EC | Unknown |
| 0x120 | RX | Y | -- | -- | 0x8E3EC | Unknown |
| 0x121 | RX | Y | -- | -- | 0x8E3EC | Unknown |
| 0x122 | RX | Y | -- | -- | 0x8E3EC | Unknown |
| 0x394 | RX | -- | -- | -- | -- | HW mbox on Module B, handler 0x9B369 |
| 0x395 | RX | -- | -- | -- | -- | NM-range, HW mbox on Module B |
| 0x604 | RX | -- | -- | -- | -- | HW mbox on Module A |
| 0x6C7 | RX | -- | -- | -- | -- | NM-related, HW mbox on Module B |
| 0x6D0 | RX | -- | -- | -- | -- | NM-related, HW mbox on Module B |
| 0x6FF | RX | -- | -- | -- | -- | Broadcast/catch-all, both modules |
| 0x708 | RX | -- | -- | 0x90A | -- | Unknown, has GW target |

#### Extended-range IDs with msgcfg handlers (0x0B5-0x267)

IDs in range 0x0B5-0x267 that have `in_msgcfg=Y` (handler config in can_msg_cfg_table)
and/or `in_cluster=Y` but no DBC match. Many share routine 0x8E3EC (the common COM handler).
There are approximately 200 such IDs. The full set is in `decode/can_inventory.csv`.

Selected notable entries:

| CAN ID | Dir | GW Target | Notes |
|--------|-----|-----------|-------|
| 0x0BA-0x0BD | RX | -- | Both in_msgcfg and in_cluster, sensor data block |
| 0x0C0-0x0C2 | RX | -- | Both flags, likely sensor aggregation |
| 0x0E0 | RX | -- | Both flags, sensor data |
| 0x118-0x119 | RX | -- | Adjacent to ACC_10 (0x117), msgcfg only |
| 0x125 | RX | -- | Both flags, before HCA_01 (0x126) |
| 0x127-0x128 | RX | -- | Both flags, after HCA_01 |
| 0x17F-0x185 | RX | -- | Both flags, large block |
| 0x1AC-0x1B8 | RX | -- | Both flags, large block |
| 0x1DA | RX | 0x167 | GW-routed, has state_ram |
| 0x1DD | RX | 0x167 | GW-routed, has state_ram |
| 0x1E7 | RX | 0x167 | GW-routed, has state_ram |
| 0x1F5 | RX | 0x167 | GW-routed, has state_ram |
| 0x203 | RX | 0x167 | GW-routed (also TP2.0 response) |
| 0x211 | RX | 0x167 | GW-routed |
| 0x220 | RX | 0x168 | GW-routed |
| 0x229-0x22D | RX | 0x168 | Both flags, GW-routed block |
| 0x235 | RX | 0x168 | GW-routed |
| 0x254-0x258 | RX | 0x168 | Both flags, GW-routed block |

#### Diagnostic / Transport IDs (Module B, not in can_inventory.csv)

These IDs appear in the HW mailbox table but are NOT in the application-level can_inventory.csv
because they are handled by the TP2.0/KWP diagnostic path, not the COM layer.

| CAN ID | HECC | Handler | DBC Name | Notes |
|--------|------|---------|----------|-------|
| 0x019 | B | 0x9D4E3 | -- | Internal |
| 0x062 | B | 0x1274D | -- | Sensor data (on vehicle bus) |
| 0x203 | B | 0xA43F5 | -- | TP2.0 channel (logical addr 0x03=ABS) |
| 0x4A3 | B | 0xA43F5 | -- | TP2.0 channel (our-TX/their-RX) |
| 0x6B4 | B | 0x127ED | VIN_01 (DBC) | **Diag request** in this ECU |
| 0x6B7 | B | 0x127ED | Kombi_02 (DBC) | Diag-range, mask-matched |
| 0x6B8 | B | 0x127ED | Kombi_03 (DBC) | **Diag response** in this ECU |
| 0x6D9 | B | 0x127ED | NMH_EPB (DBC) | NM, mask-matched with diag |

---

## Gateway Routing

Several CAN IDs have a `gw_target` field indicating they are gateway-routed (received on one
bus and forwarded to an internal destination or another module):

| CAN ID | GW Target | Notes |
|--------|-----------|-------|
| 0x102 | 0x304 | Getriebe_03 -> TPD_Tester_05 (DBC 0x304) |
| 0x1DA | 0x167 | Unknown, routed to internal target |
| 0x1DD | 0x167 | Routed to internal target |
| 0x1DF | 0x167 | Routed to internal target |
| 0x1E7 | 0x167 | Routed to internal target |
| 0x1F5 | 0x167 | Routed to internal target |
| 0x203 | 0x167 | TP2.0 resp, routed to internal target |
| 0x211 | 0x167 | Routed to internal target |
| 0x21F | 0x167 | Routed to internal target |
| 0x220 | 0x168 | Routed to internal target |
| 0x229 | 0x168 | Routed to internal target |
| 0x235 | 0x168 | Routed to internal target |
| 0x24B | 0x168 | Routed to internal target |
| 0x251 | 0x168 | Routed to internal target |
| 0x252 | 0x168 | Routed to internal target |
| 0x253 | 0x168 | Routed to internal target |
| 0x254 | 0x168 | Routed to internal target |
| 0x267 | 0x168 | Routed to internal target |
| 0x708 | 0x90A | Unknown destination |

---

## Openpilot-Relevant Messages

Messages on the vehicle CAN bus (Module B, HECC2) that carry data relevant for openpilot
lateral and longitudinal control on the Audi B8 Q5 / MLB platform.

### Critical for openpilot

| CAN ID | DBC Name | Content (from vw_mlb.dbc) | Dir | Notes |
|--------|----------|---------------------------|-----|-------|
| 0x100 | ESP_01 | `ESP_v_Signal` (vehicle speed, 0.01 km/h/bit), `ASR_Moment`, `ABS_Bremsung`, `ESP_Eingriff` | TX | Vehicle speed + ESP/ABS/ASR status |
| 0x101 | ESP_02 | `ESP_Gierrate` (yaw rate, 0.01 deg/s/bit, 14-bit), `ESP_Querbeschleunigung` (lat accel), `ESP_Laengsbeschl` (long accel) | TX | Inertial sensors + standstill flag |
| 0x103 | ESP_03 | `ESP_VL/VR/HL/HR_Radgeschw` (4 individual wheel speeds, 0.1 km/h/bit, 12-bit each) | TX | Individual wheel speeds |
| 0x106 | ESP_05 | `ESP_Bremsdruck` (0.3 bar/bit), `ECD_nicht_verfuegbar` (bit 33), `ESP_Fahrer_bremst`, `ESP_Verz_TSK_aktiv` | TX | Brake pressure + ECD availability |
| 0x11E | ESP_08 | `ESC_Bremsdruckgradient`, `ESP_v_ref` (0.125 km/h/bit) | TX | Ref speed + brake gradient |
| 0x086 | LWI_01 | `LWI_Lenkradwinkel` (steering angle, 0.1 deg/bit), `LWI_VZ_Lenkradwinkel` (sign), `LWI_Lenkradw_Geschw` (steering rate) | RX | **Steering angle sensor** |
| 0x11D | LH_EPS_02 | `EPS_Lenkmoment` (steering torque), `EPS_Bereitschaft` | RX | EPS torque + readiness |
| 0x126 | HCA_01 | `HCA_Lenkmoment_Soll` (desired steering torque), `HCA_Funktionsstatus` | RX | **Lateral control input** (from front sensor) |
| 0x117 | ACC_10 | `ANB_Zielbrems_Teilbrems_Verz_Anf` (AEB target decel), `ANB_*_Freigabe`, `AWV1_ECD_Anlauf` | RX | **AEB/ANB braking** (key for low-speed ACC) |
| 0x109 | ACC_01 | `ACC_Sollbeschleunigung_Gradient` | RX | ACC comfort decel request |

### Supplementary for openpilot

| CAN ID | DBC Name | Content | Dir | Notes |
|--------|----------|---------|-----|-------|
| 0x080 | Motor_01 | `Motor_Drehzahl` (RPM), `Motor_Soll_ist` | RX | Engine RPM |
| 0x081 | Motor_02 | `Motor_Moment_ist` (actual torque) | RX | Engine torque |
| 0x082 | Getriebe_01 | `Getriebe_Gang_akt` (current gear) | RX | Transmission gear |
| 0x102 | Getriebe_03 | `Getriebe_Anforderung` | RX | Transmission request |
| 0x104 | EPB_01 | `EPB_Status`, `EPB_Verzoeg_Anf` | RX | Parking brake status |
| 0x085 | SCU_01 | Steering column unit | RX | Column switch inputs |
| 0x09F | LH_EPS_03 | EPS additional data | RX | EPS extended status |
| 0x308 | ESP_04 | `ESP_m_Raddrehz` (wheel freq), `ABS_Lampe`, `ESP_Lampe`, `ESP_Wegimp_VA` | TX | Warning lamps + wheel impulse |
| 0x10C | TSK_02 | Torque request | RX | Engine torque coordination |

### Key openpilot observations

1. **Vehicle speed** is in ESP_01 (0x100): `ESP_v_Signal`, 16-bit, 0.01 km/h/bit.
   **Individual wheel speeds** (VL/VR/HL/HR) are in ESP_03 (0x103), 12-bit each,
   0.1 km/h/bit. ESP_08 (0x11E) carries `ESP_v_ref` at 0.125 km/h/bit.

2. **Steering angle** comes from LWI_01 (0x086, LWS_D4 = steering angle sensor):
   `LWI_Lenkradwinkel` (13-bit, 0.1 deg/bit) + sign bit. The EPS (LH_EPS_02, 0x11D)
   provides steering torque (`EPS_Lenkmoment`), not angle.

3. **Yaw rate** is in ESP_02 (0x101): `ESP_Gierrate` (14-bit, 0.01 deg/s/bit) + sign.
   **Lateral accel** is also in ESP_02: `ESP_Querbeschleunigung` (8-bit, 0.01 g/bit).
   **Longitudinal accel** is ESP_02: `ESP_Laengsbeschl` (10-bit, 0.03125 m/s2/bit).
   The raw sensor data comes from the sensor CAN (Module A); the ESP relays processed
   values on the vehicle bus.

4. **Brake pressure** is in ESP_05 (0x106): `ESP_Bremsdruck` (10-bit, 0.3 bar/bit).
   **Braking decel request** enters via ACC_10 (0x117) for AEB/ANB and ACC_01 (0x109)
   for comfort ACC. The ESP converts these into hydraulic actuation internally.

5. **ECD availability** (the 15 km/h floor question) is ESP_05 bit 33
   (`ECD_nicht_verfuegbar`). It originates in this ECU's firmware. The exact threshold
   computation is traced to `FUN_0000a904` but the specific RAM-to-bit-packer path is
   not yet fully resolved (see `docs/RE_findings.md`).

6. **HCA_01** (0x126) is the lateral control input from the front sensor (camera/radar).
   The ESP acts on `HCA_Lenkmoment_Soll` to provide lane-keep / heading control assist
   via the EPS.

7. **No CAN ID 0x10D (ACC_05)** is received by the ESP in the firmware acceptance filter
   @0xafae0. The DBC lists it as a Gateway-sourced message; the ESP does have it in its
   `in_cluster` but the earlier analysis noted "CAN 0x10D is NOT in the receive filter"
   (see `docs/com_init_objtable.md`). If openpilot sends comfort decel on 0x10D, the ESP
   may not act on it via the comfort path.

---

## Statistics

- **Total CAN IDs in can_inventory.csv:** 334
- **Matched to vw_mlb.dbc:** 39 (including TX and RX)
- **Not in vw_mlb.dbc:** 296 (mostly sensor-CAN internal + proprietary)
- **HECC1 (Module A) HW mailbox records:** 12
- **HECC2 (Module B) HW mailbox records:** 50
- **ESP TX messages (Module B):** 5 primary (ESP_01/02/03/05/08) + 8 auxiliary
- **Gateway-routed IDs:** 19

---

## Sources

- `decode/can_inventory.csv` -- 335-row CAN ID inventory (firmware config tables)
- `decode/rx_filter_map.txt` -- 62-record HW mailbox table decoded from @0xAEA38
- `decode/rx_filter_table.py` -- decoder script for the HW mailbox table
- `bench/can_raw.py` -- 225-ID acceptance filter from @0xAFAE0 (Module A)
- `bench/nm_operational.py` -- Module B operational TX ID set (bench-confirmed)
- `vw_mlb.dbc` from opendbc -- DBC message definitions for VAG MLB platform
- `analysis/decompiles_r/0008f708.c` -- `can_rx_isr` (dual-controller ISR)
- `analysis/decompiles_r/000501d4.c` -- `rx_mailbox_resolver` (COM signal-group resolver)
- `docs/RE_findings.md` -- MCU/peripheral identification (TMS470R1B1M + HECC)
