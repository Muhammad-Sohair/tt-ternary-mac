![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg)

# TMAC: a ternary (1.58-bit) MAC array for Tiny Tapeout SKY130

A 4 × 5 array of multiplier-free ternary processing elements, hardened for the Tiny Tapeout **SKY 26d**
shuttle (SkyWater 130 nm, 2x2 tiles). It carries an FPGA BitNet-style accelerator
([LLM-on-a-FPGA](https://github.com/Muhammad-Sohair/LLM-on-a-FPGA), 512 PEs on a Zynq-7020) onto silicon:
the same base-3 weight packing (5 trits per byte), the same add/subtract/pass PE, and the same
`sat16(acc >>> shift)` requantisation contract. All of it was rewritten for an ASIC flow, with no FPGA
primitives.

**Status:** designed, verified and signed off; **not yet submitted** to the shuttle. The datasheet is in
[docs/info.md](docs/info.md).

## Sign-off summary (LibreLane 3.0.14, sky130A, 50 MHz, 9 PVT/RC corners)

| | |
|---|---|
| utilisation | 57.7 % of a 2x2 tile (41,866 µm² std cells) |
| setup / hold WNS | **+5.69 ns** (worst, ss/100 °C/1.6 V) / **+0.107 ns** (ff/−40 °C) |
| DRC / LVS / antenna | 0 / 0 / 0 |
| max-slew | 1 data net 5 ps over 0.75 ns at nom ss: documented in [notes/04](notes/04_signoff.md), not suppressed |
| verification | bit-exact Python model; 9 cocotb tests in RTL **and gate level**; all 256 weight bytes; mutation-tested |
| reproducibility | re-running the signed-off configuration gives a byte-identical netlist (0/312 metrics differ) |

## How the design works

```
SPI (mode 0) -> command decoder -> packed weight bytes -> trit decoder -> W[4][5] (2-bit codes)
                                -> int8 activations a[5] ------------------------------+
BIST (LFSR -> core -> MISR) -mux->  4 rows x 5 ternary PEs: dot = sum (a XOR neg)&nz + popcount(neg)
                                    pipelined 24-bit saturating accumulators
MISO <- status / sat16(acc >>> shift) / raw 24-bit / weights / BIST signature
```

## The engineering story (the useful part)

The `notes/` folder is a log of what happened, including the mistakes:

1. [Flow walkthrough](notes/01_flow_walkthrough.md): RTL → cocotb → GDS → reading timing/DRC/LVS reports,
   on a practice counter. The first gate-level run failed because the testbench sampled too early.
2. [Spec and options](notes/02_spec.md): three sized options. My area estimate turned out to be 1.55× too
   optimistic, and why.
3. [RTL and verification](notes/03_rtl_and_verification.md): the owner's design decisions, 8 bugs found
   and what each taught (one synthesis-only bug Vivado would have accepted), mutation testing.
4. [Hardening and sign-off](notes/04_signoff.md): 22 hardening runs. Pipelining and a reset synchroniser to
   close 50 MHz at ss/100 °C. Chasing max-slew from 1,325 violations down to one net, including a wrong
   theory I had to retract, and every warning explained.
5. [Silicon test plan](notes/05_silicon_test_plan.md): staged bring-up on the TT devkit, with what each
   failure would mean. The script is [devkit/tmac_bringup.py](devkit/tmac_bringup.py) (MicroPython, reuses
   the same Python model).

## Running it (Windows, no WSL or Docker needed)

```
python -m venv .venv && .venv\Scripts\pip install -r test/requirements.txt
cd test && mingw32-make                       # RTL simulation (iverilog 12 + cocotb 2.1)
mingw32-make GATES=yes                        # gate level: netlist from the gds action, PDK_ROOT set
python tmac_model.py --write-rtl              # regenerate the BIST signature after model/BIST changes
```

Hardening runs in GitHub Actions (`.github/workflows/gds.yaml`). The SKY130 cell models for gate-level
simulation come from `ciel` (`ciel enable --pdk-family sky130 -l sky130_fd_sc_hd <version>`).

`practice/counter/` holds the Step 1 design. The `acc24-shift-ref` tag and the `eval/4x10-acc24-3x2` branch
keep the 4 × 10 versions for a later multi-tile chip.

## License

Apache-2.0. Built on the Tiny Tapeout SKY template (Apache-2.0).
