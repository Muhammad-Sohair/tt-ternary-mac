# SPDX-License-Identifier: Apache-2.0
"""TMAC silicon bring-up for the Tiny Tapeout demo board (MicroPython).

Copy this file and test/tmac_model.py to the board, then:
    import tmac_bringup; tmac_bringup.run_all(tt)

Board API used (tt-micropython-firmware README): tt.shuttle.<name>.enable(),
tt.ui_in[n] = v, tt.uo_out[n], tt.clock_project_PWM(hz), tt.clock_project_stop(),
tt.clock_project_once(), tt.reset_project(bool). `tt` is the DemoBoard object the
firmware creates at boot, in RPMode.ASIC_RP_CONTROL.

SPI is bit-banged with explicit delays so that each SCK phase is >= 8 project
clocks (the chip requires f_SCK <= f_clk/16). Each stage maps to a test in
docs/test_plan (notes/05_silicon_test_plan.md), which says what a failure means.
"""

import time

import tmac_model as M

PROJECT_HZ = 1_000_000          # bring-up clock; raised in stage S8
HALF_US = 20                    # >= 8 clocks at 1 MHz, with margin for Python jitter

SCK, CSN, MOSI, BIST = 0, 1, 2, 3
MISO, DONE, PASS_, ILL, SAT, BUSY, ACT = 0, 2, 3, 4, 5, 6, 7


def setup(tt, hz=PROJECT_HZ):
    tt.shuttle.tt_um_msohair_tmac.enable()
    tt.ui_in.value = 0b0010                      # CS_n high, SCK low, BIST low
    tt.clock_project_PWM(hz)
    tt.reset_project(True)
    time.sleep_ms(10)
    tt.reset_project(False)
    time.sleep_ms(10)


def xfer(tt, tx, nread=0, half_us=HALF_US):
    rx = []
    tt.ui_in[CSN] = 0
    time.sleep_us(half_us)
    for byte in list(tx) + [0] * nread:
        got = 0
        for i in range(7, -1, -1):
            tt.ui_in[MOSI] = (byte >> i) & 1
            time.sleep_us(half_us)
            got = (got << 1) | int(tt.uo_out[MISO])
            tt.ui_in[SCK] = 1
            time.sleep_us(half_us)
            tt.ui_in[SCK] = 0
        rx.append(got)
    time.sleep_us(half_us)
    tt.ui_in[CSN] = 1
    tt.ui_in[MOSI] = 0
    time.sleep_us(half_us)
    return rx


def s16(v):
    return v - 65536 if v & 0x8000 else v


def read_state(tt):
    rx = xfer(tt, [0x40], 2 * M.ROWS)
    acc = [s16(rx[1 + 2 * r] << 8 | rx[2 + 2 * r]) for r in range(M.ROWS)]
    sat_b, status = xfer(tt, [0x00], 2)[1:]
    return acc, sat_b, status


def compare(tt, m, tag):
    acc, sat_b, status = read_state(tt)
    ok = acc == m.acc and sat_b == m.sat_byte() and status == m.status()
    if not ok:
        print(tag, "MISMATCH acc", acc, "model", m.acc,
              "sat 0x%02x/0x%02x status 0x%02x/0x%02x" % (sat_b, m.sat_byte(), status, m.status()))
    return ok


class Rng:                          # MicroPython has no random.Random; tiny LCG instead
    def __init__(self, seed):
        self.s = seed

    def next(self, n):
        self.s = (self.s * 1103515245 + 12345) & 0x7FFFFFFF
        return self.s % n


# ---------------- stages (see the test plan) ----------------
def s1_alive(tt):
    rx = xfer(tt, [0x00], 2)
    print("S1 status during opcode: 0x%02x (want 0x81), pins uo=0x%02x" % (rx[0], int(tt.uo_out.value)))
    return rx[0] == 0x81


def s2_bist_pin(tt):
    tt.ui_in[BIST] = 1
    time.sleep_ms(1)
    tt.ui_in[BIST] = 0
    time.sleep_ms(5)                                 # 672 clocks = 0.67 ms at 1 MHz
    done, ok = int(tt.uo_out[DONE]), int(tt.uo_out[PASS_])
    sig = xfer(tt, [0x61], 2)[1:]
    sig = sig[0] << 8 | sig[1]
    print("S2 BIST pin: DONE=%d PASS=%d signature 0x%04x (want 0x%04x)" % (done, ok, sig, M.bist_expected()))
    return done == 1 and ok == 1 and sig == M.bist_expected()


def s3_hand_example(tt):
    xfer(tt, [0x70])
    xfer(tt, [0x10, 0xF2, 0xF2] + [121] * 6)         # row 0 all +1, rows 1-3 all 0 (121 = digits 1)
    xfer(tt, [0x20] + list(range(1, 11)))
    xfer(tt, [0x31])
    acc = read_state(tt)[0]
    print("S3 hand example: acc", acc, "(want [55, 0, 0, 0])")
    return acc == [55, 0, 0, 0]


def s4_decoder(tt):
    bad = []
    for b in range(256):
        xfer(tt, [0x10, b])
        codes = xfer(tt, [0x50], 2)[1:]
        ws, illegal = M.decode(b)
        want = 0
        for k, w in enumerate(ws):
            want |= M.CODE[w] << (2 * k)
        st = xfer(tt, [0x00], 2)[2]
        if (codes[0] | codes[1] << 8) & 0x3FF != want or bool(st & 0x08) != illegal:
            bad.append(b)
        if illegal:
            xfer(tt, [0x70])
    print("S4 decoder: %d/256 bytes wrong %s" % (len(bad), bad[:16]))
    return not bad


def s5_random(tt, trials=200, seed=1):
    rng, m, fails = Rng(seed), M.TMAC(), 0
    xfer(tt, [0x70])
    for t in range(trials):
        W = [[rng.next(3) - 1 for _ in range(M.COLS)] for _ in range(M.ROWS)]
        wb = M.pack_matrix(W)
        xfer(tt, [0x10] + wb)
        for i, b in enumerate(wb):
            m.write_wbyte(i, b)
        acts = [rng.next(256) for _ in range(M.COLS)]
        xfer(tt, [0x20] + acts)
        for i, a in enumerate(acts):
            m.write_act(i, a)
        clear = t % 3 == 0
        xfer(tt, [0x31 if clear else 0x30])
        m.compute(clear)
        if not compare(tt, m, "S5 trial %d" % t):
            fails += 1
    print("S5 random matvec: %d/%d trials failed" % (fails, trials))
    return fails == 0


def s6_saturation(tt):
    m = M.TMAC()
    xfer(tt, [0x70])
    W = [[1] * 10, [-1] * 10, [-1] * 10, [1] * 5 + [0] * 5]
    xfer(tt, [0x10] + M.pack_matrix(W))
    xfer(tt, [0x20] + [127] * 10)
    for i, b in enumerate(M.pack_matrix(W)):
        m.write_wbyte(i, b)
    for i in range(10):
        m.write_act(i, 127)
    for _ in range(27):
        xfer(tt, [0x30])
        m.compute(False)
    ok = compare(tt, m, "S6 saturation") and m.acc[:3] == [M.ACC_MAX, M.ACC_MIN, M.ACC_MIN]
    print("S6 saturation:", "ok" if ok else "FAIL")
    return ok


def s7_streamed(tt, chunks=4, nvec=8, seed=3):
    rng, m = Rng(seed), M.TMAC()
    xfer(tt, [0x70])
    for c in range(chunks):
        W = [[rng.next(3) - 1 for _ in range(M.COLS)] for _ in range(M.ROWS)]
        xfer(tt, [0x10] + M.pack_matrix(W))
        for i, b in enumerate(M.pack_matrix(W)):
            m.write_wbyte(i, b)
        stream = []
        for _ in range(nvec):
            acts = [rng.next(256) for _ in range(M.COLS)]
            stream += acts
            for i, a in enumerate(acts):
                m.write_act(i, a)
            m.compute(False)
        xfer(tt, [0x21] + stream)
    ok = compare(tt, m, "S7 streamed")
    print("S7 streamed K=%d matvec:" % (chunks * nvec * 10), "ok" if ok else "FAIL")
    return ok


def s8_clock_sweep(tt, freqs=(1_000_000, 5_000_000, 10_000_000, 25_000_000, 50_000_000)):
    """BIST at increasing project clocks: BIST runs entirely on-chip, so the highest
    passing frequency is the datapath's real Fmax at this board's voltage/temperature."""
    results = {}
    for hz in freqs:
        tt.clock_project_PWM(hz)
        time.sleep_ms(5)
        tt.ui_in[BIST] = 1
        time.sleep_ms(1)
        tt.ui_in[BIST] = 0
        time.sleep_ms(5)
        results[hz] = (int(tt.uo_out[DONE]), int(tt.uo_out[PASS_]))
        print("S8 BIST @ %d Hz: DONE=%d PASS=%d" % ((hz,) + results[hz]))
    tt.clock_project_PWM(PROJECT_HZ)
    return results


def run_all(tt):
    """Pass the firmware's DemoBoard object: tmac_bringup.run_all(tt)."""
    setup(tt)
    out = {}
    for name, fn in (("S1", s1_alive), ("S2", s2_bist_pin), ("S3", s3_hand_example), ("S4", s4_decoder),
                     ("S5", s5_random), ("S6", s6_saturation), ("S7", s7_streamed)):
        out[name] = fn(tt)
    out["S8"] = s8_clock_sweep(tt)
    print("SUMMARY", out)
    return out
