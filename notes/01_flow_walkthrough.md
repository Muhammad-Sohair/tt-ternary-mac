# Step 1 — the flow, end to end, on a practice counter

Design: `practice/counter/` (8-bit counter with enable and synchronous load), `tt_um_msohair_counter`.
First cloud run: GitHub Actions run 40507731039, 2026-10-27, LibreLane 3.0.14, sky130A PDK
`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`.

## 1. RTL

`src/counter.v`. Tiny Tapeout fixes the top-level interface:

| port | dir | meaning |
|---|---|---|
| `ui_in[7:0]` | in | 8 dedicated inputs |
| `uo_out[7:0]` | out | 8 dedicated outputs |
| `uio_in/uio_out/uio_oe[7:0]` | bidir | 8 bidirectional pins; `uio_oe=1` makes that pin an output |
| `clk`, `rst_n` | in | the project clock and an active-low reset, both from the devkit |
| `ena` | in | high while your design is selected; you may ignore it |

The rules that differ from FPGA work:
- **There is no FPGA fabric.** `initial` blocks, BRAM inference, PLLs and `$readmemh` are gone. Every flop must
  be reset explicitly, or it powers up as X (random on silicon).
- **Every output must be driven.** Unused outputs are tied to 0.
- **Unused inputs are collected into `_unused`** so the linter does not warn about them.

## 2. Testbench (cocotb)

`test/tb.v` is a thin Verilog wrapper. `test/test.py` holds the tests. A Python `CounterModel` is the golden
reference: every cycle the DUT output is compared with it bit for bit (2,000 random cycles plus directed edge
cases: reset, hold, 255→0 wrap, LOAD-beats-EN).

**Lesson learned on the first cloud run: where you sample matters.** The first version sampled at
`ReadOnly()` straight after the rising edge. That passes in RTL sim, where a flop's Q updates in the same
timestep as the edge. It FAILED gate-level sim (3/4 tests, `got 0, want 253`): the netlist is simulated with
`UNIT_DELAY=#1`, so Q changes one time unit *after* the edge, just as real silicon has clock-to-Q delay. The fix
is in the testbench, not the design: drive inputs on the falling edge and sample on the next falling edge,
mid-cycle. That is also how the RP2040 on the devkit will talk to the chip.

## 3. Simulation

- RTL: `cd test; make` (iverilog 12 + cocotb 2.1.0 run natively on Windows; use `mingw32-make`).
- Gate level: copy the hardened netlist to `test/gate_level_netlist.v`, set `PDK_ROOT`, run `make GATES=yes`.
  This simulates the actual standard cells (`sky130_fd_sc_hd`) that LibreLane placed, so it catches synthesis
  surprises: X-propagation from unreset flops, logic optimised away, and tests that only pass with zero delay.

## 4. Hardening: RTL → GDS (`.github/workflows/gds.yaml` → `TinyTapeout/tt-gds-action@ttsky26d`)

The action runs `tt_tool.py --create-user-config` (turns `info.yaml` + `src/config.json` into a LibreLane
config, with the die size fixed by the tile count), then `tt_tool.py --harden`, which runs LibreLane 3.0.14. The
72 steps in `runs/wokwi/` fall into these stages:

| steps | stage | what it does |
|---|---|---|
| 01–04 | Lint | Verilator lint. Errors stop the flow. |
| 05–09 | Synthesis | Yosys maps RTL onto sky130_fd_sc_hd cells. It checks for unmapped cells and `assign` statements in the netlist. |
| 10–12 | STA prep | Uses a generic SDC (`CLOCK_PERIOD` = 20 ns from `src/config.json`), so 50 MHz is the constraint. |
| 13–27 | Floorplan + power | Fixed die (one 1x1 tile), rows cut, tap/endcap cells inserted, power-grid stripes built, IO pins placed where the TT mux expects them. |
| 28–34 | Placement | Global placement, then repair (buffering/resizing), then detailed placement onto legal sites. |
| 35–38 | CTS | Clock tree synthesis: a buffer tree so `clk` reaches every flop with low skew, then timing repair. |
| 39–47 | Routing | Global route, antenna repair (diodes), detailed route (TritonRoute), routing-DRC check. |
| 52 | Fill | Filler/decap cells fill the empty rows (that is the 15,461 µm² of `fill_cell` below). |
| 54–56 | Signoff STA | Parasitics extracted (RCX), then timing at 9 corners: {min,nom,max wire} × {ff −40 °C 1.95 V, tt 25 °C 1.8 V, ss 100 °C 1.6 V}. |
| 57–58 | GDS | Magic and KLayout each write the layout. |
| 62–63 | DRC | Magic checks the layout against the foundry's geometric rules. |
| 64–67 | LVS | Magic extracts a SPICE netlist from the polygons, and Netgen compares it with the synthesised netlist. |
| 68–72 | Checkers | Setup/hold/slew/cap violation counts, then `manufacturability.rpt`. |

## 5. Reading the reports — counter results

`runs/wokwi/final/metrics.json` and `72-misc-reportmanufacturability/manufacturability.rpt`:

| metric | value | meaning |
|---|---|---|
| die area | 17,954.7 µm² | One 1x1 tile (~161 × 111.5 µm). |
| core area | 16,493.3 µm² | Placeable area inside the margins. |
| std-cell area | 1,032.2 µm² | Real logic: 8 flops = 170 µm², 50 logic cells = 382 µm², taps 282 µm², buffers 195 µm². |
| utilisation | 6.26 % | Logic ÷ core. The flow targets 60 % placement density, so the ceiling is roughly 50–60 %. |
| setup WNS | +12.39 ns (worst: ss/100 °C/1.6 V) | Positive slack is good: the longest path has 12.4 ns to spare at 50 MHz. |
| hold WNS | +0.13 ns (worst: ff/−40 °C/1.95 V) | Positive is good. Hold is worst at the fast corner because data arrives too *early* there. |
| DRC (Magic) | 0 | No geometry-rule violations. |
| LVS | 0 errors, 0 net/device differences | The layout is exactly the netlist we simulated. |
| antenna | 0 | No plasma-charging hazards on gates. |
| max-cap violations | 0 | |
| **max-slew violations** | **11, ss corner only** | Explained below. |

**The 11 max-slew warnings.** All 11 are pins on one net, driven by `fanout12`, a buffer the resizer inserted
for the high-fanout `LOAD`/reset control: about 10 gate inputs hang off it. At the slow corner its edge takes
0.884 ns to transition, against a 0.75 ns limit (slack −0.134 ns). They do not appear at the tt or ff corners.
Consequence: slightly more delay and short-circuit current on that net. Timing still closes with +12.4 ns of
setup slack at the same corner, so this is not a functional risk for the counter. **Not suppressed.** For the
real design I will watch for it on high-fanout control nets (mode/reset/enable). The fix, if it matters, is a
deliberate buffer tree or registering the control signal; the margins do not need to change.

**Other warnings in `warning.log`, and why each is acceptable:**
- `PNR_SDC_FILE / SIGNOFF_SDC_FILE not defined, using generic fallback SDC`: expected. TT designs constrain
  only `clk` at `CLOCK_PERIOD`. The IO paths go through the TT mux (~20 ns round trip, measured), which our SDC
  cannot see. This is why the silicon test plan runs the interface well below 50 MHz.
- `STA-1140 library ... already exists`: the same corner .lib is loaded more than once. Cosmetic.
- `RSZ-0020 found 2 floating nets`: these are the unused `ui_in` bits and `ena`, which the design intentionally
  ignores. Benign.
- `DRT-0349 LEF58_ENCLOSURE ... not supported`: a router limitation on a sky130 via rule. Magic DRC is the
  authoritative check, and it is clean.
- `Bterm VPWR/VGND declared as POWER/GROUND`: informational.

## 6. Tools on Windows — what runs where

| task | where | needs |
|---|---|---|
| RTL + gate-level sim | native Windows | Python 3.11 venv, cocotb 2.1.0, iverilog 12, mingw32-make, sky130_fd_sc_hd via `ciel` (into `E:\extras\pdk`) |
| Hardening | GitHub Actions (cloud) | nothing local |
| Hardening locally (optional) | Docker Desktop (WSL2 backend), or WSL2 directly | LibreLane container. Docker Desktop currently fails to start (vhdx "file exists"), and the WSL Ubuntu has no DNS, so the cloud flow is the route for now |
