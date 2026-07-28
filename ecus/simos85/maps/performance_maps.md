# Performance-tuning maps — NAMED + ADDRESSED

Source: `maps/simos85.a2l` (canonical ASAP2 store). Names come from the Funktionsrahmen;
addresses were located in `8R0907551F_Original.bin` and confirmed there — 19/19 axis
arrays land on monotonic RPM/load breakpoints, and `ip_tqi_ref` renders as a clean
0–468 Nm torque table.

Addresses below are direct file offsets into the 2 MB bin (= vaddr − 0x80000000).
Full machine-readable catalog: `maps/a2l_catalog.csv` (name, kind, addr, dims, cell bits, x/y axis, scaling), generated from the canonical `maps/simos85.a2l`.

## Maps the Stage1/2 tunes actually modified (the deployed tuning)
| addr | dims | name | role |
|------|------|------|------|
| 0x560f4 | 12x10 u16 | `ip_tq_pow_max_at[0]` | **max torque at clutch by gear** (core power) |
| 0x561e4 | 12x10 u16 | `ip_tq_pow_max_at[1]` | max torque at clutch by gear |
| 0x56554 | 12x10 u16 | `ip_tq_pow_max_eco[0]` | max torque, efficiency mode |
| 0x56644 | 12x10 u16 | `ip_tq_pow_max_eco[1]` | max torque, efficiency mode |
| 0x56764 | 12x7 u16 | `ip_tq_pow_max_mt[0]` | max torque at clutch (MT) |
| 0x5680c | 12x7 u16 | `ip_tq_pow_max_mt[1]` | max torque at clutch (MT) |
| 0x568b4 | 1x8 u16 | `ip_tq_pow_max_mt_4wd` | max torque (MT 4WD) |
| 0x57bd4 | 16x12 u16 | `ip_tqi_ref` | **indicated torque @ reference** (torque model) |
| 0x5ee5c | 12x10 u16 | `ip_fup_sp_hom` | fuel pressure setpoint (homogeneous) |
| 0x44512 | 1x6 u8 | Max RPM vs coolant temp | rev limit vs ECT |
| 0x44518 | 1x4 u8 | Max RPM vs oil temp | rev limit vs oil temp |
| 0x43c38 | u8 km/h | `c_vs_max_aeb_act` | max speed, active engine brackets |

## Other defined maps (not tuned in Stage1/2, but available)
ignition dwell @0x73dac, fuel-mass correction `ip_mff_cor` @0x711e4/0x71c24,
fuel pressure `ip_fup_sp_dui/pu` @0x5edbc/0x5ef4c, knock correction `ip_iga_*_knk` @0x44fc9/0x44fd1,
fuel pump duty `lpfp_max_duty` @0x43256.

## Cross-link to FR (Funktionsrahmen)
The A2L CHARACTERISTIC names are lowercase FR labels: `ip_tq_pow_max*` ↔ FR `TQ_POW_MAX`/`TQI_POW_MAX`,
`ip_tqi_ref` ↔ `TQI`, `c_vs_*` ↔ FR `C_VS_*` family (incl. cruise `C_VS_MIN_CRU`). See `fr_alignment.md`.
