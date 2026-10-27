# Step 4 — hardening and sign-off log

All runs: GitHub Actions, `TinyTapeout/tt-gds-action@ttsky26d`, LibreLane 3.0.14, sky130A PDK
`8afc8346`, 50 MHz (`CLOCK_PERIOD` 20 ns), 9 STA corners. "ss" = `nom_ss_100C_1v60` unless noted.
Metrics come from `runs/wokwi/final/metrics.json` in each run's `GDS_logs` artifact.

## The iteration history, and what each run taught

| # | design | tiles | util | setup WNS (ss) | ss slew viol. | result / lesson |
|---|---|---|---|---|---|---|
| 1 | 4×10, 24-bit acc | 2x2 | — | — | — | synthesis stopped: **34 Yosys check errors**. A shared `integer` loop variable across `always` blocks is a multiple-driver error. Local synthesis now runs `check -assert`. |
| 2 | 4×10, 16-bit | 2x2 | 73.3 % | −3.06 ns | 1,931 | routed DRC/LVS clean. Worst path: BIST mux → LFSR legalise → **5-stage trit decoder** → weight reg (−3.06); adder tree → saturating acc (−1.22). |
| 3 | 4×10, 16-bit, pipelined | 2x2 | 74.1 % | −3.42 ns | 2,194 | reg→reg paths now pass; remaining 8 violations are **`rst_n` input → flop** (4 ns input delay + 430-flop fanout tree). |
| 4 | 4×10, 16-bit, + reset synchroniser | 2x2 | 72.5 % | −0.09 ns | 2,192 | nearly closed; GL test passes. Utilisation too high to be comfortable. |
| — | 4×10, 24-bit + shift (unpipelined) | 2x2 | — | — | — | still routing after 67 min (vs 16 min for 16-bit): congestion near full. |
| 5 | **4×5, 24-bit + shift** | 2x2 | **58.3 %** | **+3.44 ns** | 1,325 | meets utilisation and timing. Slew: 108 of 143 nets driven by **`clkdlybuf4s25_1`** (a clock *delay* cell) used as a fanout buffer; 11 CTS leaves with 13–14 sinks. |
| 6 | 4×10, 24-bit + shift | 3x2 | 54.5 % | −0.02 ns | 2,482 | fallback candidate, before the slew fixes. |
| 7 | 4×5 + delay cells excluded, CTS clusters ≤ 10, slew margins 30/20 % | 2x2 | 56.6 % | +4.11 ns | 1,303 | fanout violations 0. The resizer now picks `buf_1` (weakest buffer) for 10-load nets; violations at **tt** too (258) → repair is not meeting 0.75 ns anywhere. Post-GRT repair was **off** (`RUN_POST_GRT_DESIGN_REPAIR=false`). |
| 8 | 4×10 3x2 + same fixes | 3x2 | 53.3 % | +0.12 ns (−0.13 worst-wire corner) | 2,272 | the 4×10's 10-term adder trees are tighter on timing even with more room. |
| 9 | 4×5 + post-GRT repair (V1) | 2x2 | 57.0 % | +4.20 ns | 516 | repair on near-real parasitics helps a lot. |
| 10 | 4×5 + V1 + no `buf_1`/`clkbuf_1` (V2) | 2x2 | 57.8 % | +1.88 ns | 164 | 20 nets left, all within 0.08 ns; resizer now uses `dlygate4sd3_1` (hold delay gate) as a fanout buffer. |
| 11 | V2 + repair slew margins 40/40 (V3a) | 2x2 | 58.3 % | +2.87 ns | 13 (41 at max-wire ss) | 0 at every non-ss corner. |
| 12 | V3a + no `dlygate`/`dlymetal` cells (V3b) | 2x2 | 56.8 % | +6.00 ns | 1 net, −0.003 ns (19 pins / 4 nets at max-wire ss) | hold fixed with ordinary buffers (208); timing improved. Last net: `clkbuf_2` fanout buffer for weight bit `w[8][0]` (10 loads). |
| 13 | V3b + repair slew margins 60/60 (V4) | 2x2 | — | — | — | **crashed**: `RepairDesignPostGPL` peaked at 14 GiB RSS, above what the GitHub runner can hold. |
| 14 | V4 + `MAX_FANOUT_CONSTRAINT` 8 (V4b) | 2x2 | — | — | — | same crash. |
| 15 | V3b, post-GRT margin 55 only (V5a) | 2x2 | 58.2 % | +5.98 ns | 17 | worse; hold slack fell to +0.04 ns. |
| 16 | V3b + fanout 8 (V5b) | 2x2 | 57.7 % | +5.82 ns | 12 | no better than V3b: the runs are now in placement noise. |
| 17 | V3b + no `clkbuf_2` + fanout 8 (V6) | 2x2 | 57.7 % | +5.81 ns | **3 pins, 1 net, −0.086 ns** (same at all 3 ss wire corners; 0 elsewhere) | the net is row 1's saturation detect (`acc[47]`, `dot_q[1][10]`) → `sat_flags[1]`. An `a21boi_2` drives a long wire that received an antenna diode; the diode's capacitance causes the excess. |
| 18 | 4×10 3x2 with the V6 flow settings | 3x2 | 53.9 % | +0.45 ns | 225 (436 at max-wire ss), plus 3 fanout and 2 max-cap | like-for-like, the fallback is worse on every criterion. |
| 19 | V6 + antenna repair by jumpers only (V7) | 2x2 | 57.7 % | +5.85 ns | **2 pins, 1 net, −0.005 ns** (11 pins at max-wire ss) | **signed off** (see below). |
| 20 | V6 + overflow test rewritten as `sum[24]^sum[23]` (V8) | 2x2 | 57.9 % | +6.02 ns | 36 | logic-equivalent RTL change; different nets now violate. Confirms placement noise. |
| 21 | V7 + repair margins over-constrained to 50/55 % (owner's one final attempt) | 2x2 | 58.4 % | +5.81 ns | 9 (16 at max-wire ss) | not clean. By the owner's rule: sign off V7. |
| 22 | V7 configuration re-run on the release branch (run 40570454913) | 2x2 | 57.7 % | +5.85 ns | 2 (11 at max-wire ss) | **identical to V7**: 0 of 312 metrics differ, byte-identical netlist. The flow is deterministic, so this run is the sign-off artifact. |

**Owner's decision rule (2026-10-28):** one over-constrained attempt (run 21); if it is not clean, sign off V7,
provided the residual nets are not clock or reset nets, with the residual documented. Run 21 was not clean,
so V7 is signed off. No further iteration.

**A theory I got wrong.** After runs 7–11 I guessed that the repair was aiming at the library's 1.5 ns ss limit
rather than TT's 0.75 ns. The SDC used for placement (`13-openroad-floorplan/*.sdc`) contains
`set_max_transition 0.7500 [current_design]`, so the repair does know the real limit. The leftovers are the
gap between the parasitics repair estimates (placement / global route) and the detailed-route parasitics
that sign-off STA measures. No repair pass runs after detailed routing. That is also why the last few
violations move between runs: they depend on exact routes.

## Why my Step 2 area estimate was wrong (and the correction)

Step 2 sized the options with Yosys (via YoWASP) mapping onto `sky130_fd_sc_hd__*_1` cells. LibreLane maps to
**`_2` drive strengths** (`dfxtp_2`, `xnor2_2`, …), then the resizer adds fanout/hold/timing buffers:

| | local Yosys | LibreLane synth | final std-cell area |
|---|---|---|---|
| 4×10, 16-bit | 34,548 µm² | 46,950 µm² (×1.36) | 53,170 µm² (×1.54) |
| 4×5, 24-bit + shift | 27,307 µm² | — | 42,283 µm² (×1.55) |

The rule now used is **local Yosys × 1.55 ≈ final std-cell area**. It predicted 42.3k for 4×5 before the run;
the run measured 42.3k.

## Sign-off: V7 (`tt_um_msohair_tmac`, 4×5, 24-bit + `sat16(acc >>> shift)`, 2x2 tiles, 50 MHz)

| check | result |
|---|---|
| die / core | 75,602.5 / 72,564.6 µm² (2x2: 334.88 × 225.76 µm) |
| std-cell area / utilisation | 41,866 µm² / **57.7 %** |
| setup WNS, all 9 corners | **+5.69 ns** worst (max_ss_100C_1v60); nom ss +5.85; tt +13.1; ff +14.1 |
| hold WNS, all 9 corners | **+0.107 ns** worst (min_ff_n40C_1v95); 0 violations |
| max-cap / max-fanout violations | 0 / 0 |
| max-slew violations | nom ss: 2 pins (1 net); max-wire ss: 11 pins (2 nets); all other 7 corners: 0 |
| routing DRC / Magic DRC / LVS / antenna | 0 / 0 / 0 errors / 0 |
| TT precheck | pass |
| gate-level simulation | CI `gl_test` pass; local, on this exact netlist: **9/9 incl. 24-bit internal saturation** (`TMAC_GL_SLOW=1`, 10 min) |
| power (estimate, tt) | 4.37 mW |

### The residual slew, documented

| net | corner | slew | limit | over | driver → loads | type |
|---|---|---|---|---|---|---|
| `_2037_` | nom_ss_100C_1v60 | 0.7548 ns | 0.75 ns | **+4.8 ps (0.6 %)** | `a21boi_2 _4979_` → `o21a_2 _4980_.A2` → hold buffer → `sat_flags[1]` D | data: row 1 saturation detect (from `acc[47]`, `dot_q[1][10]`) |
| `_2037_` | max_ss_100C_1v60 | 0.7975 ns | 0.75 ns | +47.5 ps | same | same |
| `u_core.a[2][0]` | max_ss_100C_1v60 | 0.7652 ns | 0.75 ns | +15.2 ps | `dfxtp_2 _5690_` → 8 XOR/OR mask gates in the dot-product trees | data: activation register a[2], bit 0 |

Neither is a clock or reset net. The clock tree has 0 slew and 0 fanout violations at every corner, and the
reset synchroniser's tree is clean.

**Why it is functionally negligible.** Max-transition is a *characterisation* limit. Beyond it, the
library's delay tables are extrapolated rather than measured, and slow edges cost a little extra
short-circuit power. It is not a functional failure in itself. The timing effect of a slow edge already
appears in the STA delay of the downstream gate, and every path through both nets has positive slack:

- `_2037_` lands on `sat_flags[1]` and `u_core.a[2][0]` feeds the adder trees. The worst setup path in the
  whole design still has **+5.69 ns** of slack at the max-wire ss corner (+5.85 at nom ss). A 48 ps slower
  edge, even with a pessimistic 2–3× delay sensitivity, costs well under 0.2 ns, so roughly 30× margin remains.
- Hold is unaffected. A slower edge can only *add* delay, and hold slack is positive (+0.107 ns) at ff,
  where these nets are within limits anyway.
- The silicon test plan (notes/05, stage S8) sweeps the clock: if either net mattered, the datapath BIST
  would fail first at the highest frequency, and the sweep reports the real Fmax.

## Warnings: what each one is, and why it is acceptable

From V7's `warning.log` (1,049 lines, de-duplicated) and the Verilator lint log. None is suppressed.

| warning | count | what it is | why it is acceptable |
|---|---|---|---|
| Max slew violations in nom_ss / max_ss | 1 | the residual above | documented above |
| `EST-0026` Missing route to pin … | 1,000 (message cap reached) | all from step 41, post-global-route design repair: after `repair_design` changes the netlist (here: resized 1 cell, inserted 1 buffer), the incremental re-route drops and re-routes the affected nets, and the parasitic estimator queries them in between | transient. The final global route lists all 3,928 nets as routed, detailed routing has 0 DRC, and LVS confirms the layout's connectivity matches the netlist. |
| `PNR_SDC_FILE` / `SIGNOFF_SDC_FILE` not defined | 1 + 1 | TT uses LibreLane's generic SDC: `clk` at 20 ns, 4 ns IO delays, `set_max_transition 0.75` | intended by the TT template. The real IO timing goes through the TT mux (~20 ns round trip), which no project SDC can see, hence f_SCK ≤ f_clk/16. |
| `STA-1140` library … already exists | 24 | the same corner .lib is loaded more than once | cosmetic |
| `DRT-0349` LEF58_ENCLOSURE … not supported | 10 | a router limitation on some sky130 via rules | Magic DRC, the sign-off checker, reports 0 |
| `RSZ` found N floating nets | 1 | the unused inputs (`ui_in[7:4]`, `uio_in`, `ena`) | intentional; collected in `_unused` |
| Bterm VPWR/VGND declared as POWER/GROUND | 2 | informational, from the DEF template | expected |
| output / input pins without antenna information | 2 | the top cell's own pins have no antenna data until it is placed in the TT wrapper | expected for a macro; TT's top-level flow handles it |
| `klayout__drc_error__count` not reported | 1 | KLayout DRC is disabled by the TT config (`RUN_KLAYOUT_DRC: 0`) | Magic DRC runs and is clean; the shuttle runs full DRC at tapeout |
| long-wire threshold not set | 1 | an optional checker is skipped | no threshold applies to TT tiles |
| `VSRC_LOC_FILES` not given | 1 | IR-drop analysis has no supply-pad locations | only meaningful for a full chip; TT provides the power grid |
| 21 Verilator lint warnings | 21 | see the next table | each one checked |

### Lint warnings (Verilator), one by one

| file | warning | verdict |
|---|---|---|
| tmac_core.v | 4 × WIDTHEXPAND in the dot product and accumulate (`term`, `nneg`, `dot_q` into wider sums, `wc==2'b11` into the count) | intended: signed/unsigned operands sign- or zero-extend to the sum width, which the tests confirm bit-exact (incl. −128 and saturation) |
| tmac_core.v | WIDTHEXPAND in `clear_q ? dot_q : acc + dot_q` | intended sign extension (signed operands) |
| tmac_core.v | BLKSEQ: blocking `sum =` inside the clocked block | intended: `sum` is a per-row temporary, used only within the same iteration; no flop is inferred for it (synthesis `check` clean) |
| tmac_core.v | UNUSEDPARAM `NBYTES` | harmless leftover; candidate cleanup |
| trit_decoder.v | 3 × WIDTHTRUNC on the remainders `r3`, `r2`, `r1` | intended: after subtracting 81·d4 (27·d3, 9·d2), the remainder provably fits the narrower width (exhaustive 256-byte test) |
| tmac_bist.v | WIDTHEXPAND `w_addr` compare; WIDTHEXPAND/TRUNC in the 24→16-bit fold | intended: the fold XORs bits 23:16 onto 15:0 (model does the same) |
| spi_slave.v | UNUSEDSIGNAL `rx_shift[7]` | true by design: bit 7 is shifted out as the byte completes |
| tt_um_msohair_tmac.v | UNUSEDSIGNAL `spi_start` | the slave uses `start` internally; the top-level copy is unused. Harmless |
| tt_um_msohair_tmac.v | WIDTHEXPAND `sat_flags` (4 bits) into an 8-bit byte; `idx`/`w_ptr` compares against 32-bit loop constants; `rshift` against 32-bit constants | intended zero/sign extension |
