# SPDX-License-Identifier: Apache-2.0
"""Bit-exact Python reference model of the TMAC chip.

This is the golden model the cocotb tests compare against, and the source of
the BIST signature baked into the RTL:

    python test/tmac_model.py --write-rtl     # rewrites the constants in src/tt_um_msohair_tmac.v

Every rule here mirrors one in the RTL; the comments name the file.
It runs unchanged under MicroPython on the devkit (devkit/tmac_bringup.py
imports it), so the host-only imports live inside the functions that use them.
"""

ROWS, COLS, ACC_W = 4, 10, 16
BPR = COLS // 5                     # packed bytes per row
NBYTES = ROWS * BPR
ACC_MAX, ACC_MIN = (1 << (ACC_W - 1)) - 1, -(1 << (ACC_W - 1))
BIST_ITERS, BIST_SEED = 32, 0xACE1

# 2-bit weight codes (tmac_core.v / FPGA ternary_pe.sv)
CODE = {-1: 0b11, 0: 0b00, +1: 0b01}
WEIGHT = {v: k for k, v in CODE.items()}


# ---------------- PACKING_FORMAT v1.0 ----------------
def pack5(ws):
    """Five weights in {-1,0,+1} -> one byte, d = w + 1, lowest index = least-significant digit."""
    assert len(ws) == 5
    return sum((w + 1) * 3 ** i for i, w in enumerate(ws))


def decode(byte):
    """trit_decoder.v: byte -> (five weights, illegal). Illegal bytes decode to all zero."""
    if byte > 242:
        return [0] * 5, True
    ws = []
    for _ in range(5):
        ws.append(byte % 3 - 1)
        byte //= 3
    return ws, False


def pack_matrix(W):
    """ROWS x COLS weights -> NBYTES packed bytes in load order (row-major, 5 columns per byte)."""
    out = []
    for r in range(ROWS):
        for b in range(BPR):
            out.append(pack5(W[r][5 * b:5 * b + 5]))
    return out


# ---------------- arithmetic ----------------
def sat(v, lo, hi):
    return (min(max(v, lo), hi), v > hi or v < lo)


def to_s8(b):
    return b - 256 if b >= 128 else b


# ---------------- the chip ----------------
class TMAC:
    def __init__(self):
        self.reset()

    def reset(self):
        self.W = [[0] * COLS for _ in range(ROWS)]
        self.a = [0] * COLS
        self.acc = [0] * ROWS
        self.sat_flags = [False] * ROWS
        self.illegal = False
        self.bist_done = self.bist_pass = False
        self.signature = 0

    # core operations
    def write_wbyte(self, idx, byte):
        ws, bad = decode(byte)
        r, b = divmod(idx % NBYTES, BPR)
        self.W[r][5 * b:5 * b + 5] = ws
        self.illegal |= bad

    def write_act(self, idx, byte):
        self.a[idx % COLS] = to_s8(byte)

    def dot(self, r):
        return sum(w * x for w, x in zip(self.W[r], self.a))

    def compute(self, clear):
        for r in range(ROWS):
            v = self.dot(r) + (0 if clear else self.acc[r])
            self.acc[r], s = sat(v, ACC_MIN, ACC_MAX)
            self.sat_flags[r] |= s

    def clear(self):
        self.acc = [0] * ROWS
        self.sat_flags = [False] * ROWS
        self.illegal = False

    # readout views
    def status(self, busy=False):
        return (0x80 | busy << 6 | self.bist_done << 5 | self.bist_pass << 4
                | self.illegal << 3 | any(self.sat_flags) << 2 | 1)

    def sat_byte(self):
        return sum(1 << r for r in range(ROWS) if self.sat_flags[r])

    def weight_codes(self):
        flat = [CODE[w] for row in self.W for w in row]
        out = []
        for j in range(0, len(flat), 4):
            grp = flat[j:j + 4] + [0] * (4 - len(flat[j:j + 4]))
            out.append(grp[0] | grp[1] << 2 | grp[2] << 4 | grp[3] << 6)
        return out

    # BIST (tmac_bist.v)
    def run_bist(self, expected=None):
        lfsr, sig = BIST_SEED, 0
        self.clear()                        # BIST start pulses acc_rst

        def nxt(x):
            return (x >> 1) ^ 0xB400 if x & 1 else x >> 1

        for it in range(BIST_ITERS):
            for i in range(NBYTES):
                raw = lfsr & 0xFF
                self.write_wbyte(i, raw - 243 if raw > 242 else raw)
                lfsr = nxt(lfsr)
            for i in range(COLS):
                self.write_act(i, lfsr & 0xFF)
                lfsr = nxt(lfsr)
            self.compute(clear=(it % 4 == 0))
            fold = 0
            for r in range(ROWS):
                u = self.acc[r] & ((1 << ACC_W) - 1)
                row16 = (u & 0xFFFF) ^ (u >> 16)
                k = r % 16
                fold ^= ((row16 << k) | (row16 >> ((16 - k) % 16))) & 0xFFFF
            fb = ((sig >> 15) ^ (sig >> 13) ^ (sig >> 12) ^ (sig >> 10)) & 1
            sig = (((sig << 1) & 0xFFFF) | fb) ^ fold
        self.signature = sig
        self.bist_done = True
        self.bist_pass = expected is None or sig == expected
        return sig


def write_rtl_constants(sig):
    import pathlib
    import re
    top = pathlib.Path(__file__).resolve().parent.parent / "src" / "tt_um_msohair_tmac.v"
    text = top.read_text()
    block = (
        "  // BEGIN GENERATED BIST CONSTANTS (test/tmac_model.py --write-rtl; do not edit)\n"
        f"  localparam        BIST_ITERS    = {BIST_ITERS};\n"
        f"  localparam [15:0] BIST_SEED     = 16'h{BIST_SEED:04X};\n"
        f"  localparam [15:0] BIST_EXPECTED = 16'h{sig:04X};\n"
        "  // END GENERATED BIST CONSTANTS\n"
    )
    new, n = re.subn(r"  // BEGIN GENERATED BIST CONSTANTS.*?// END GENERATED BIST CONSTANTS\n", block, text, flags=re.S)
    assert n == 1, "marker block not found"
    top.write_text(new, newline="\n")
    return top


def bist_expected():
    return TMAC().run_bist()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-rtl", action="store_true")
    args = ap.parse_args()
    sig = bist_expected()
    print(f"BIST signature: 0x{sig:04X}")
    if args.write_rtl:
        print("updated", write_rtl_constants(sig))
