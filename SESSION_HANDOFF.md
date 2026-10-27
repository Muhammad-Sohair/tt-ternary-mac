# Session handoff — 2026-10-28

## Where things stand

- **Design signed off, NOT submitted.** `tt_um_msohair_tmac`: 4×5 ternary MAC array, 24-bit saturating
  accumulators, `sat16(acc >>> shift)` readout, SPI, BIST. 2x2 tiles, 50 MHz. Signed-off configuration = "V7";
  `main` now holds it (fast-forwarded from `eval/4x5-acc24-v3b`).
- Sign-off: 57.7 % utilisation, setup +5.69 ns / hold +0.107 ns worst-case, DRC/LVS/antenna 0. Residual:
  1 data net 5 ps over the 0.75 ns max-slew limit at nom ss (11 pins / 2 data nets at max-wire ss), accepted
  under the owner's rule (notes/04). Re-running V7 is byte-identical (deterministic flow).
- Verification: RTL 9/9; gate level 9/9 on the signed-off netlist including the 24-bit saturation test
  (local) and CI `gl_test`; mutation batch on the shipped RTL (results in notes/03).

## Step 0 facts (verified 2026-10-27; re-check before acting)

| item | value | source |
|---|---|---|
| next SKY shuttle | **TT SKY 26d**, closes **2026-11-30** | app.tinytapeout.com/shuttles |
| chips expected / ship | 2027-05-12 / from 2027-06-09 | tinytapeout.com/chips |
| tiles free on 26d | 70 of 512 (2026-10-27) | shuttle status page |
| price | 70 €/tile (so 280 € for 2x2); devkit 300 € or 100 € individual early-bird (limited); shipping 15 € | app.tinytapeout.com/calculator |
| Pakistan shipping | **[UNKNOWN]**: not listed as sanctioned in the terms (§6.2); no positive shipping list found. Ask TT before paying. | tinytapeout.com/terms |
| tile | 1x1 = 161.00 × 111.52 µm; 2x2 = 334.88 × 225.76 µm | tt-support-tools `tile_sizes.yaml` |
| IO | 8 in, 8 out, 8 bidir; inputs 66 MHz, outputs 33 MHz, mux round trip ~20 ns | tinytapeout.com/specs |

## What needs YOU (nothing below was done)

1. **Ask TT whether they ship to Pakistan** before paying anything.
2. **Submission and payment** at app.tinytapeout.com (account + payment are yours to do): 2x2 tiles = 280 €,
   plus a devkit if wanted. Deadline 2026-11-30.
3. Review the residual-slew acceptance in notes/04 once more before submitting.

## Repo map

- `src/` RTL · `test/` model + cocotb · `devkit/` MicroPython bring-up (syntax-checked only: no board
  available to run it) · `notes/01-05` the full story · `practice/counter/` Step 1.
- Branches: `eval/*` hold the evidence runs (keep; notes/04 cites them). Tag `acc24-shift-ref` = 4×10
  24-bit reference. Local worktrees `../tt-ternary-mac-{3x2,v2,v3b,v4b}` can be removed with
  `git worktree remove` once you no longer need them.

## Gotchas learned

- LibreLane area ≈ 1.55 × local YoWASP-Yosys (`_2` cells + repair). Use that factor for sizing.
- The TT flow reports max-slew but never fails on it (`MAX_SLEW_VIOLATION_CORNERS = [""]`).
- `DESIGN_REPAIR_MAX_SLEW_PCT` 60 made OpenROAD use 14 GiB and crash on the GitHub runner; 50 is OK.
- `gh run download` of GDS_logs is ~hundreds of MB; run it in the background.
- YoWASP Yosys only sees the current folder (WASI sandbox); keep the scripts and the .lib in `.syn/`.
