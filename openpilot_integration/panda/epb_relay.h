// ===========================================================================
// EPB dynamic-brake relay  -- secondary (inline) panda, black panda / STM32F4
// ---------------------------------------------------------------------------
// Sits inline on the EPB module's CAN connection:
//     bus 2 = EPB side     bus 0 = gateway/ABS side     bus 1 = extended CAN (read-only)
// Reads openpilot's intent from ACC_05 (0x10D) on bus 1 and, while active, rewrites the
// EPB module's own EPB_01 (0x104) as it is forwarded bus 2 -> bus 0, injecting
// EPB_Verzoeg_Anf + Freig so the ABS performs hydraulic service braking below 15 km/h.
//
// It ALSO (prototype, 2026-10-18) rewrites ESP_05 (0x106) as it is forwarded bus 0 -> bus 2,
// setting ESP_Anforderung_EPB to command the EPB MOTOR CLAMP at standstill, so the car holds
// at a traffic-light stop instead of creeping (the ABS has no autohold on this car -- proven
// on route 0000018c: ESP_Autohold_aktiv/Standby + AWV_Halten all-zero, EPB never auto-clamped).
// Per design intent the clamp only engages AFTER a hydraulic-hold dwell (EPB_CLAMP_DWELL_FRAMES):
// hold the stop hydraulically for a few seconds first, then clamp the parking brake as the static
// backup -- matching stock Auto-Vehicle-Hold sequencing.
//
// Validated against a live capture (2026-10-17): a real lever-pull produced
// EPB_Freig_Verzoeg_Anf=1 + EPB_Verzoeg_Anf raw 42 (-5.95 m/s2) and the ABS set
// ESP_05.ESP_Verz_EPB_aktiv within ~25 ms. This replays exactly that frame shape.
//
// LIVENESS / ENGAGEMENT (ACC_05 is the heartbeat):
//   The SAFETY_VW_EPB_RELAY mode is ENGAGED (intercept relay open, bus 0<->2 forwarding
//   active, bus 1 listen-only) only while valid ACC_05 is arriving on bus 1 -- "valid"
//   means both the XOR checksum AND the message counter (byte1 low nibble) advancing +1.
//   If ACC_05 stops (openpilot not running / disconnected / frozen sender), the panda
//   DISENGAGES and behaves exactly like SILENT: the intercept relay closes, so the EPB
//   wire is a direct EPB<->ABS link again (stock behaviour), and all buses go listen-only.
//   main.c's tick handler polls epb_relay_should_engage() at 8 Hz and flips the relay.
//
// SAFETY: only EPB_01 bus2->bus0 and ESP_05 bus0->bus2 are ever modified; every other
//   frame forwards byte-for-byte. The decel command fails safe (EPB_01 passes through
//   untouched -> no autonomous braking) when:
//     - ACC_05 is stale (no counter-valid frame recently), OR
//     - ACC_Freigabe_Verzanf == 0 (openpilot not requesting EPB braking), OR
//     - measured speed >= EPB_RELAY_SPEED_CAP_KPH (hard backstop; openpilot also gates at 15).
//   The clamp command fails safe (ESP_05 passes through untouched -> stock value, normally
//   release) when NOT ( ACC_Betaetigung_EPB && standstill-dwell-met && ESP_Verzoeg_EPB_verf && live ).
//   The clamp is HARD-gated to speed < EPB_CLAMP_SPEED_MAX_KPH so the motor caliper can never
//   be commanded closed while rolling. And the whole bridge fails safe (relay closed -> stock
//   wire) whenever ACC_05 is not live.
// ===========================================================================
#pragma once

#define EPB01_ADDR  0x104U   // EPB_01  (EPB module TX, bus 2)   seed 0x05
#define ACC05_ADDR  0x10DU   // ACC_05  (openpilot TX, bus 1)    seed 0x0C
#define ESP05_ADDR  0x106U   // ESP_05  (ABS TX, bus 0)          seed 0x07
#define ESP01_ADDR  0x100U   // ESP_01  (speed: ESP_v_Signal)

#define EPB_RELAY_SPEED_CAP_KPH  20U    // hard backstop above openpilot's 15 km/h gate
#define EPB_RELAY_FRESH_FRAMES   500U   // ~100 ms of total bus traffic (~5000 f/s); TODO: switch to us-timer
#define EPB_RELAY_STALE_TICKS    4U     // 8 Hz ticks (~0.5 s) with no counter-valid ACC_05 -> disengage

// ---- EPB motor clamp via ESP_05 (prototype 2026-10-18) ------------------------------------
#define EPB_CLAMP_ENABLE        0U   // master enable for the ESP_05 clamp rewrite
#define EPB_CLAMP_SPEED_MAX_KPH 2U   // only ever command the clamp below this (never while rolling)
#define EPB_CLAMP_DWELL_FRAMES  150U // ESP_01 frames at standstill before clamping (hold hydraulically
                                     //   first). ESP_01 ~50 Hz => ~3 s. Tune once rate is confirmed.
#define EPB_CLAMP_CMD           2U   // ESP_Anforderung_EPB value to request the stop-go CLOSE/clamp.
                                     //   DBC VAL (vw_mlb.dbc, msg 262) + EPB fw (8K0907801N) are
                                     //   ground truth for this 2-bit field (byte7 bits62-63):
                                     //     0 = keine_Anforderung   (no request)
                                     //     1 = Anforderung_Oeffnen (OPEN / release)
                                     //     2 = Anforderung_Schliessen (CLOSE / clamp)  <-- what we want
                                     //     3 = reserviert
                                     //   CORRECTED 2026-10-19: we had =1 ("hold"), but 1 is OPEN. On
                                     //   route 000001fe the EPB never clamped (EPB_Status/Spannkraft=0,
                                     //   no fault/konsistenz flag) because we were commanding OPEN. The
                                     //   close command is 2. VERIFY ON CAR: EPB_01.EPB_Status -> 1
                                     //   (closed) + EPB_Spannkraft rises while we hold =2.
#define EPB_CLAMP_RELEASE_CMD   1U   // ESP_Anforderung_EPB = 1 = Anforderung_Oeffnen (explicit OPEN)
                                     //   to ACTIVELY command release; falls back to passthrough after.
#define EPB_RELEASE_FRAMES      75U  // ESP_05 frames to ACTIVELY command release after clamp drops
                                     //   (~1.5 s @50 Hz) before falling back to passthrough -- guarantees
                                     //   a deterministic open on launch, covering the ~1 s motor release.

typedef struct {
  bool     brake_active;   // ACC_Freigabe_Verzanf == 1
  bool     epb_clamp;      // ACC_Betaetigung_EPB  == 1 (static-clamp request, standstill hold)
  uint8_t  epb_verz_raw;   // EPB_Verzoeg_Anf raw byte, converted from ACC_Verz_anf
  uint16_t speed_kph;      // from ESP_01 ESP_v_Signal
  uint16_t standstill_frames; // consecutive ESP_01 frames with speed < EPB_CLAMP_SPEED_MAX_KPH
  bool     clamp_was_active;  // we commanded a clamp and have not finished the active-release window
  uint16_t release_frames;    // ESP_05 frames remaining in which to actively command OPEN/release
  uint32_t fresh;          // decremented per received frame; command valid only while > 0
  uint8_t  last_counter;   // last ACC_05 counter (byte1 low nibble) seen with a valid checksum
  bool     counter_init;   // last_counter has been primed by at least one checksum-valid frame
  volatile uint32_t acc05_good;  // monotonic count of counter-valid ACC_05 frames (liveness heartbeat)
} EpbRelayState;

EpbRelayState epb_relay = {0};

// ACC_05 ACC_Verz_anf (11b, 0.005, -7.22)  ->  EPB_01 EPB_Verzoeg_Anf raw (8b, 0.048, -7.968)
//   epb_raw = (acc_raw*5 + 748) / 48   [verified: acc_raw 254 -> 42 == -5.95 m/s2]
static uint8_t acc_verz_to_epb_raw(uint16_t acc_raw) {
  uint32_t v = ((uint32_t)acc_raw * 5U + 748U) / 48U;
  return (v > 255U) ? 255U : (uint8_t)v;
}

// Called for every received frame (from can_rx), before forwarding.
static void epb_relay_rx(const CANPacket_t *rx, uint8_t bus) {
  if (epb_relay.fresh > 0U) { epb_relay.fresh--; }

  if ((bus == 1U) && (rx->addr == ACC05_ADDR) && (dlc_to_len[rx->data_len_code] == 8U)) {
    uint8_t cs = 0x0CU;                               // seed = 0x01 ^ 0x0D
    for (int i = 1; i < 8; i++) { cs ^= GET_BYTE(rx, i); }
    if (cs != GET_BYTE(rx, 0)) { return; }            // bad XOR checksum -> ignore entirely

    // Counter (byte1 low nibble) must advance exactly +1 vs the previous checksum-valid frame.
    // This is the liveness heartbeat: a frozen or absent sender never increments acc05_good,
    // so the tick handler disengages the bridge. A duplicate/stuck counter is rejected here.
    uint8_t ctr = GET_BYTE(rx, 1) & 0x0FU;
    bool counter_ok = epb_relay.counter_init && (ctr == ((uint8_t)(epb_relay.last_counter + 1U) & 0x0FU));
    epb_relay.last_counter = ctr;
    epb_relay.counter_init = true;
    if (!counter_ok) { return; }                      // first frame after a gap: prime only, not yet "live"

    bool     freigabe   = (GET_BYTE(rx, 1) >> 5) & 1U;                                   // ACC_Freigabe_Verzanf  bit13
    uint16_t acc_raw    = ((uint16_t)GET_BYTE(rx, 4) | ((uint16_t)GET_BYTE(rx, 5) << 8)) & 0x7FFU; // ACC_Verz_anf 32|11
    bool     betaet_epb = (GET_BYTE(rx, 7) >> 4) & 1U;                                   // ACC_Betaetigung_EPB   bit60
    epb_relay.brake_active = freigabe;
    epb_relay.epb_verz_raw = acc_verz_to_epb_raw(acc_raw);
    epb_relay.epb_clamp    = betaet_epb;
    epb_relay.fresh        = EPB_RELAY_FRESH_FRAMES;
    epb_relay.acc05_good  += 1U;                       // heartbeat tick
  } else if ((rx->addr == ESP01_ADDR) && (dlc_to_len[rx->data_len_code] == 8U)) {
    uint16_t raw = (uint16_t)GET_BYTE(rx, 4) | ((uint16_t)GET_BYTE(rx, 5) << 8);         // ESP_v_Signal 32|16, 0.01 km/h
    epb_relay.speed_kph = raw / 100U;
    // standstill dwell counter: used to hold hydraulically for a few seconds before clamping
    if (epb_relay.speed_kph < EPB_CLAMP_SPEED_MAX_KPH) {
      if (epb_relay.standstill_frames < 0xFFFFU) { epb_relay.standstill_frames++; }
    } else {
      epb_relay.standstill_frames = 0U;
    }
  }
}

// NOTE: liveness/engagement (epb_relay_should_engage) lives in board/main.c, since it needs
// board-level calls (relay, can_init) and must be F4-only; it reads epb_relay.acc05_good.

// Called in the forward path on the frame about to be sent to dest_bus; rewrites EPB_01
// (decel, bus2->bus0) and ESP_05 (motor clamp, bus0->bus2) in place.
static void epb_relay_fwd_rewrite(CANPacket_t *fwd, uint8_t src_bus, int dest_bus) {
  if (dlc_to_len[fwd->data_len_code] != 8U) { return; }

  // ---- ESP_05 motor-clamp rewrite: ABS side (bus 0) -> EPB side (bus 2) -------------------
  if ((EPB_CLAMP_ENABLE != 0U) && (src_bus == 0U) && (dest_bus == 2) && (fwd->addr == ESP05_ADDR)) {
    bool epb_verf   = (fwd->data[7] >> 4) & 1U;                     // ESP_Verzoeg_EPB_verf bit60 (byte7 bit4)
    bool dwell_met  = (epb_relay.standstill_frames >= EPB_CLAMP_DWELL_FRAMES);
    bool want_clamp = epb_relay.epb_clamp && (epb_relay.fresh > 0U) && dwell_met && epb_verf;

    uint8_t cmd_val;
    if (want_clamp) {
      cmd_val = EPB_CLAMP_CMD;                        // request the hold
      epb_relay.clamp_was_active = true;
      epb_relay.release_frames   = EPB_RELEASE_FRAMES;
    } else if (epb_relay.clamp_was_active && (epb_relay.release_frames > 0U)) {
      cmd_val = EPB_CLAMP_RELEASE_CMD;                // actively command OPEN for the release window
      epb_relay.release_frames--;
      if (epb_relay.release_frames == 0U) { epb_relay.clamp_was_active = false; }
    } else {
      return;                                         // idle: pass ESP_05 through untouched (stock value)
    }

    // ESP_Anforderung_EPB = bits 62-63 (byte7 top two bits). Preserve COUNTER (byte1 low nibble).
    fwd->data[7] = (uint8_t)((fwd->data[7] & ~(3U << 6)) | ((cmd_val & 3U) << 6));

    uint8_t cs = 0x07U;                                            // ESP_05 seed
    for (int i = 1; i < 8; i++) { cs ^= fwd->data[i]; }
    fwd->data[0] = cs;                                             // ESP_05 CHECKSUM (byte0)
    return;
  }

  // ---- EPB_01 decel rewrite: EPB side (bus 2) -> ABS side (bus 0) --------------------------
  if ((src_bus != 2U) || (dest_bus != 0) || (fwd->addr != EPB01_ADDR)) { return; }

  bool ok = epb_relay.brake_active && (epb_relay.fresh > 0U) &&
            (epb_relay.speed_kph < EPB_RELAY_SPEED_CAP_KPH);
  if (!ok) { return; }                                 // pass EPB_01 through untouched (fail-safe)

  fwd->data[2]  = epb_relay.epb_verz_raw;              // EPB_Verzoeg_Anf   (16|8)
  fwd->data[1] |= (uint8_t)(1U << 7);                  // EPB_Freig_Verzoeg_Anf (bit15) -- preserves COUNTER (byte1 low nibble)
  fwd->data[6]  = (uint8_t)((fwd->data[6] & ~(3U << 4)) | (2U << 4));  // EPB_Schalterposition (52|2) = 2 (mimic lever pull)

  uint8_t cs = 0x05U;                                  // EPB_01 seed
  for (int i = 1; i < 8; i++) { cs ^= fwd->data[i]; }
  fwd->data[0] = cs;                                   // EPB_01 CHECKSUM (byte0)
}
