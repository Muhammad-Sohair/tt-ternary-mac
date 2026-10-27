# Step 2 — TMAC spec: ternary weight-stationary MAC array for TT SKY 26d

## Common architecture (all options)

```
 SPI (mode 0) ──► command decoder ──► weight bytes ─► trit decoder ─► W[R][C] (2-bit codes)
   ui[0] SCK                      └─► activations a[C] (int8) ─────────────┐
   ui[1] CS_n                                                                ▼
   ui[2] MOSI          BIST (LFSR → core → MISR) ──mux──►  R rows of C ternary PEs
   uo[0] MISO ◄── status / accumulators / weights / signature      dot_r = Σ_c w[r][c]·a[c]
                                                                    acc_r = sat16(acc_r + dot_r)
```

- **PE (multiplier-free, same as the FPGA):** w=+1 adds a, w=−1 subtracts it, w=0 passes. On silicon each row
  forms its dot product as `Σ (a ⊕ neg)&nz + popcount(neg)`, because −a = ~a + 1. One adder tree per row,
  6–15 % smaller than the add/sub/pass chain (measured with Yosys).
- **Weights:** PACKING_FORMAT v1.0 from the FPGA repo, unchanged (d = w+1, 5 trits/byte LSB-first, bytes
  243–255 illegal → decode to 0 and set a sticky `ILLEGAL` flag). COLS is a multiple of 5, so a row is exactly
  COLS/5 packed bytes and the host streams bytes in the same order as `pack_trilm.py` (without its tile padding).
- **Accumulators:** signed ACC_W bits, saturating (clamp, never wrap), with a sticky per-row SAT flag. Compute is
  one cycle: `CMP` (acc += W·a) or `CMP_CLR` (acc = W·a). `LOAD_AC` streams activation vectors and computes
  after each one, which covers K > COLS matrix-vector products (reload weights per K-chunk).
- **SPI slave:** mode 0, MSB first, oversampled by `clk` behind 2-flop synchronisers. The constraint is
  f_SCK ≤ f_clk/8. Status comes back on MISO during every opcode byte.
- **BIST:** started by the opcode or a rising edge on `ui[3]`. It runs 32 rounds of LFSR weights and activations
  through the real core, then folds the accumulators into a 16-bit MISR and compares it with a signature from
  the Python model. PASS/DONE appear on dedicated output pins, so the datapath can be checked on silicon even
  if SPI does not work.
- **Debug readback:** `READ_W` returns the stored 2-bit codes, which separates "decoder/load broken" from
  "compute broken" on silicon.
- **Reset:** synchronous, from `rst_n`. Every flop is reset.

### Command set

| op | name | following bytes |
|---|---|---|
| 0x00 | STATUS | out: SAT flags, then status |
| 0x10 | LOAD_W | in: R·C/5 packed weight bytes (pointer wraps) |
| 0x20 | LOAD_A | in: C int8 activations |
| 0x21 | LOAD_AC | in: C activations, compute (accumulate) after each C; may repeat |
| 0x30 / 0x31 | CMP / CMP_CLR | none (one-cycle compute) |
| 0x40 | READ_ACC | out: R × ACC_W/8 bytes, row 0 first, MSB first |
| 0x50 | READ_W | out: codes, 4 per byte, lowest index in LSBs |
| 0x60 | BIST | none (busy until done) |
| 0x61 | READ_SIG | out: 16-bit signature, MSB first |
| 0x70 | CLEAR | none (zero accumulators and sticky flags) |

Status byte: `{1, BIST_BUSY, BIST_DONE, BIST_PASS, ILLEGAL, ANY_SAT, 0, 1}`. The fixed `1…01` bits show that
the chip is alive and selected.

### Pinout

| pin | use | pin | use |
|---|---|---|---|
| ui[0] | SCK | uo[0] | MISO |
| ui[1] | CS_n | uo[1] | (0) |
| ui[2] | MOSI | uo[2] | BIST_DONE |
| ui[3] | BIST start (rising edge) | uo[3] | BIST_PASS |
| ui[7:4] | unused | uo[4] | ILLEGAL (sticky) |
| uio[7:0] | unused (inputs) | uo[5] | ANY_SAT (sticky) |
| | | uo[6] | BIST_BUSY |
| | | uo[7] | SPI active (CS echo) |

## Measured sizing (Yosys 0.70 via YoWASP, sky130_fd_sc_hd tt corner, full design incl. SPI/BIST)

| array | PEs | synth area µm² | flops |
|---|---|---|---|
| 2×5 | 10 | 14,493 | 221 |
| 4×5 | 20 | 21,687 | 278 |
| 4×10 | 40 | 33,028 | 364 |
| 8×10 | 80 | 57,424 | 515 |

About 600 µm² per PE, plus about 8,000 µm² of fixed overhead (SPI, decoder, BIST, activation registers,
readout mux). A 1x1 tile has 16,493 µm² of core (measured on the counter). LibreLane typically adds
5–15 % in buffers, CTS and hold fixing, and TT's placement-density target is 60 %. **Rule used: synth area
≤ ~50 % of core.** Core areas for multi-tile sizes are estimated at n × 1x1 and will be confirmed on the first
harden.

## Options

| | A — safe | B — balanced | C — ambitious |
|---|---|---|---|
| array | 2 × 5 (10 PEs) | 4 × 10 (40 PEs) | 8 × 10 (80 PEs) |
| bytes per weight load | 2 | 8 | 16 |
| tiles | 1x2 (≈33 k µm² core) | 2x2 (≈66 k) | 4x2 (≈132 k) |
| est. utilisation | ≈44 % | ≈50 % | ≈44 % |
| tile cost (70 €/tile) | 140 € | 280 € | 560 € |
| + devkit / shipping | 100 € individual early-bird (limited), else 300 €; 15 € shipping | same | same |
| MACs per compute cycle | 10 | 40 | 80 |
| MACs per streamed activation byte | 2 | 4 | 8 |
| risk | lowest: low density, few rows, short adder trees | moderate: highest density of the three, 10-term trees | low technically, highest cost; more to verify |
| story | "first silicon of the PE + packing format" | "a real tile slice: 2 bytes/row, K-chunked matvec" | "closest to the FPGA array" |

Clock target: 50 MHz (TT default `CLOCK_PERIOD` 20 ns). The longest path is one row's adder tree plus the
16-bit saturating add, so sign-off STA will show the ss-corner slack. SPI then runs at ≤ 6.25 MHz. The
chip is I/O-bound by design, like any TT project: the mux and pads cap IO at ~33 MHz out / 66 MHz in.

Deadline: TT SKY 26d closes **2026-11-30** (34 days from 2026-10-27). On that day 70 of 512 tiles were free.
