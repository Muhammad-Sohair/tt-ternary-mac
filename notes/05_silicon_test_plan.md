# Step 5 — silicon test plan (TT SKY 26d, `tt_um_msohair_tmac`)

Chips are expected on **2027-05-12**, with shipping estimated from **2027-06-09** (tinytapeout.com/chips,
read 2026-10-27). Script: `devkit/tmac_bringup.py`. Copy it and `test/tmac_model.py` to the demo board,
then run `import tmac_bringup; tmac_bringup.run_all(tt)`. Every check is bit-exact against the same Python
model used in simulation.

## Rules of thumb before starting

- **Order matters.** Each stage depends only on the stages above it, so the first failure localises the fault.
- **Start slow:** project clock 1 MHz, SCK ≈ 25 kHz (bit-banged, ≥ 8 clocks per SCK phase). Speed is a later
  stage, never the first.
- **Record everything:** board revision, chip ID/position on the shuttle, room temperature, and the output of
  each stage. Re-run a failing stage three times before believing it.
- **Know the factory baseline:** before testing TMAC, enable `tt_um_factory_test` and confirm it works. If the
  factory test fails, the board, mux or shuttle is at fault, not this design.

## Stages

| # | drive | expected | needs |
|---|---|---|---|
| S0 | select the project, reset, read `uo_out` with CS_n high | `uo = 0x00` (no BIST, no flags, CS inactive) | mux + reset |
| S1 | `STATUS` opcode | MISO byte during opcode = **0x81**; `uo[7]` (SPI_ACTIVE) high while CS_n is low | S0, clock, SPI pins |
| S2 | pulse `ui[3]` (BIST start), wait ≥ 1 ms at 1 MHz (BIST takes 384 clocks) | `uo[2]` DONE = 1, `uo[3]` PASS = 1; `READ_SIG` = **0xA97E** | S0, clock only (S2 needs no SPI for the pass/fail pins) |
| S3 | `LOAD_W F2 79 79 79` (0xF2 = row 0 all +1, 0x79 = 121 = all zero); activations 1…5; `CMP_CLR`; `READ_RAW` | **[15, 0, 0, 0]** | S1 |
| S4 | all 256 bytes through `LOAD_W` + `READ_W` + `STATUS` | the codes match PACKING_FORMAT; ILLEGAL set exactly for bytes 243–255 | S1 |
| S5 | 200 random matvecs, random `CMP`/`CMP_CLR`, random shift 0–31 | raw 24-bit, sat16 readout, SAT flags and status all equal the model | S3, S4 |
| S6 | 53 × `CMP` with rows (+1, −1, +1, 0) × 127, shift 0 | READ_ACC clamps to 32767 / −32768 / 32767 / 0, RSAT bit set; READ_RAW exact (+33,655 / −33,655 / +33,655 / 0) | S5 |
| S7 | streamed K = 160 matvec (`LOAD_AC`, 4 weight chunks × 8 vectors of 5) | equal to the model | S5 |
| S8 | BIST at 1, 5, 10, 25, 50 MHz project clock | PASS at every frequency up to the first failure: **that is measured Fmax** | S2 |
| S9 (optional) | repeat S5 with SCK raised towards f_clk/16 | equal to the model; first failing SCK = SPI interface limit (includes the TT mux delay) | S5 |
| S10 (optional) | measure the project supply current, idle vs BIST running at 50 MHz | a number for dynamic power (the hardening report gives the estimate to compare against) | S8 |

## What each failure means

| symptom | most likely cause | next step |
|---|---|---|
| S0: random `uo` values | project not selected, or the mux/enable sequence is wrong | re-run `enable()`; check the factory test project |
| S1: MISO always 0 | no project clock (the SPI synchronisers need `clk`) or reset held | check `clock_project_PWM`, `reset_project(False)` |
| S1: MISO always 1, or 0xFF | SCK never sampled low: bit-bang too fast, or the SCK pin is stuck | raise `HALF_US`; drive SCK slowly and watch `uo[7]`/MISO |
| S1: status is 0x81 shifted by a bit (e.g. 0x02, 0xC0) | the MISO sample point is too close to the SCK edge | increase `HALF_US`; this is the f_SCK ≤ f_clk/16 rule |
| S1 OK, S2 DONE = 0 | BIST never started (the `ui[3]` edge was missed) or no clock | make the `ui[3]` pulse longer; check the clock |
| S2 DONE = 1, PASS = 0 | **datapath fault on silicon** (decoder, adder tree or accumulator) or a hold/setup failure | read `READ_SIG` and `READ_RAW`; compare with the model's BIST trace; repeat at a lower clock (S8) — if it passes at 1 MHz, it is timing, not logic |
| S2 PASS but S3 fails | the SPI write path (LOAD_W/LOAD_A pointer, command decode) is broken, not the datapath | `READ_W` after `LOAD_W` shows whether the weights landed |
| S3 OK, S4 fails on specific bytes | a decoder digit stage (compare/subtract at 162/81, 54/27, …) | the failing bytes pin down which stage |
| S4 OK, S5 fails only for some shifts | the readout shifter/saturator (shared, after the accumulator) | `READ_RAW` correct but `READ_ACC` wrong confirms it |
| S5 fails with READ_RAW off by small values | dot-product tree error (e.g. a lost +1 carry-in for negated terms) | test single-column weight patterns to isolate the column |
| S6 READ_ACC wraps instead of clamping | the saturation compare failed | compare with `READ_RAW` |
| S7 fails, S5 passes | the LOAD_AC auto-compute path | compare with explicit `LOAD_A` + `CMP` |
| S8 fails above some frequency | the setup limit of the real silicon at this voltage/temperature | compare with sign-off STA slack (notes/04); report Fmax |
| everything passes at 1 MHz, fails at 10 MHz+ only over SPI | interface limit (TT mux ≈ 20 ns round trip, pad 33 MHz out) | stay with S8 for the datapath number |

## What is NOT covered (known limits of this plan)

- 24-bit internal saturation on silicon needs about 13,200 compute commands (8,388,607 / 635). That is
  possible (a few minutes of bit-banging) but not in `run_all()`. It is covered in RTL and gate-level
  simulation (`test_internal_saturation`, run on the netlist with `TMAC_GL_SLOW=1`).
- The two nets left slightly over the max-slew limit at sign-off (notes/04): `u_core.a[2][0]` and row 1's
  saturation-detect net. Both are data nets on paths with +5.7 ns slack. If either mattered on silicon, it
  would show up as an S8 Fmax well below the STA prediction, or as an S6 failure in row 1 only.
- No power measurement equipment is assumed; S10 is optional.
- One die is only one sample. Run on more than one chip if spares arrive.
