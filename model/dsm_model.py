"""Behavioural model of the 2nd-order, 1-bit, switched-cap delta-sigma modulator (PLAN.md §2).

Boser-Wooley loop with two delaying integrators, all quantities in units of the
differential reference Vref (FS = +-1 = +-Vref):
    x1[n+1] = x1[n] + a1*(u[n] - v[n])
    x2[n+1] = x2[n] + a2*(x1[n] - v[n])        v[n] = sign(x2[n])
a1 = 0.5 is what makes NTF = (1 - z^-1)^2. a2 only scales x2, because the 1-bit
quantizer ignores scale.

The first integrator can include the op-amp non-idealities that are not noise-shaped:
  - finite DC gain A: leaky integrator p = 1 - 1/A (A ~ gain at the swing extremes)
  - settling in the integration half-period T/2 - t_no: single-pole loop with
    tau = 1 / (2 pi beta GBW), plus slew-rate limiting (Malcovati et al. model)
  - kT/C sampling noise: 4kT/Cs per sample, differential, with an op-amp excess factor
The second integrator stays ideal, because its errors are shaped by the first loop.

Outputs: results/dsm_summary.txt, results/dsm_sqnr.png, results/dsm_psd.png,
         results/dsm_nonideal.png
Run:  ../.venv/bin/python dsm_model.py
"""
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
N = 2 ** 16
KT = 1.380649e-23 * 300


@dataclass(frozen=True)
class Mod:
    osr: int = 128
    fs: float = 2e6            # sample rate (Hz)
    vref: float = 1.0          # differential reference (V): FS = +-vref differential
    a1: float = 0.5
    a2: float = 0.5
    gain: float = np.inf       # op-amp DC gain (V/V)
    gbw: float = np.inf        # op-amp GBW (Hz) with the integration-phase load
    beta: float = 0.59         # feedback factor Ci/(Ci+Cs+Cp) during integration
    sr: float = np.inf         # differential slew rate (V/s)
    t_no: float = 10e-9        # lost to non-overlap and the comparator per half-period
    cs: float = 0.0            # first-stage sampling cap per side (F); 0 = noiseless
    excess: float = 1.5        # op-amp noise excess over kT/C (multiplier on the noise power)
    order: int = 2


def settle(step, t, tau, sr):
    """Output change reached in time t when the ideal change is `step` (same units as sr*t)."""
    if np.isinf(tau):
        return 0.0
    if tau == 0 and np.isinf(sr):
        return step
    a = abs(step)
    if a <= sr * tau:                      # linear: never slews
        return step * (1 - np.exp(-t / tau))
    t0 = a / sr - tau                      # slews until the remaining error is sr*tau
    if t0 >= t:
        return np.sign(step) * sr * t
    return step - np.sign(step) * sr * tau * np.exp(-(t - t0) / tau)


def simulate(m: Mod, amp, fbin=None, seed=1):
    """Run the modulator on a coherent sine and return (bitstream, fbin, max|x1|, max|x2|, p9999|x1|)."""
    fbin = fbin or (N // (2 * m.osr)) // 3 | 1        # odd bin near BW/3
    u = amp * np.sin(2 * np.pi * fbin * np.arange(N) / N)
    if m.cs > 0:
        sigma = np.sqrt(m.excess * 4 * KT / m.cs) / m.vref
        u = u + np.random.default_rng(seed).normal(0, sigma, N)
    p = 1.0 if np.isinf(m.gain) else 1.0 - 1.0 / m.gain
    ideal_settle = np.isinf(m.gbw) and np.isinf(m.sr)
    tau = 0.0 if np.isinf(m.gbw) else 1 / (2 * np.pi * m.beta * m.gbw)
    t_int = 1 / (2 * m.fs) - m.t_no
    sr = m.sr / m.vref                                  # slew in units of Vref per second
    x1 = x2 = 0.0
    v = np.empty(N)
    x1s = np.empty(N)
    s2 = 0.0
    for n in range(N):
        q = 1.0 if (x2 if m.order == 2 else x1) >= 0 else -1.0
        v[n] = q
        step = m.a1 * (u[n] - q)
        d1 = step if ideal_settle else settle(step, t_int, tau, sr)
        if m.order == 2:
            x1, x2 = p * x1 + d1, x2 + m.a2 * (x1 - q)
        else:
            x1 = p * x1 + (u[n] - q)
        x1s[n] = x1
        s2 = max(s2, abs(x2))
    return v, fbin, np.abs(x1s).max(), s2, np.percentile(np.abs(x1s), 99.99)


def sndr(v, fbin, osr):
    w = np.hanning(N)
    spec = np.abs(np.fft.rfft(v * w)) ** 2
    bw = N // (2 * osr)
    sig = spec[fbin - 3:fbin + 4].sum()
    noise = spec[1:bw].sum() - sig            # skip DC; Hann leakage is 3 bins wide
    return 10 * np.log10(sig / noise), spec


def run(m, amp=0.5):
    """SQNR averaged (in dB) over four tone frequencies, since one tone gives +-2 dB of scatter
    from idle tones; swing is the worst of the four."""
    bw = N // (2 * m.osr)
    res = []
    for div in (5, 4, 3, 2.5):
        v, fbin, s1, _, p1 = simulate(m, amp, fbin=int(bw / div) | 1)
        res.append((sndr(v, fbin, m.osr)[0], s1, p1))
    r = np.array(res)
    return r[:, 0].mean(), r[:, 1].max(), r[:, 2].max()


def main():
    RESULTS.mkdir(exist_ok=True)
    base = Mod()
    out = [f"2nd-order 1-bit Boser-Wooley modulator, N = {N} samples, Hann window, coherent tone near BW/3",
           f"defaults: {base}", ""]

    # 1. SQNR and first-integrator swing vs amplitude (ideal)
    amps_db = np.array([-80, -60, -40, -30, -20, -15, -10, -8, -6, -5, -4, -3, -2, -1.5, -1, -0.5])
    rows = [run(base, 10 ** (a / 20)) for a in amps_db]
    sq = np.array([r[0] for r in rows])
    out.append("1) ideal, OSR 128: SQNR and first-integrator swing vs input (x Vref; swing is max / 99.99th pct)")
    for a, (s, s1, p1) in zip(amps_db, rows):
        out.append(f"   {a:6.1f} dBFS  SQNR {s:6.1f} dB   |x1| max {s1:4.2f}  p99.99 {p1:4.2f}")
    k = int(np.argmax(sq))
    out.append(f"   peak SQNR {sq[k]:.1f} dB at {amps_db[k]} dBFS")

    # 2. vs OSR, and 1st order for comparison
    out.append("\n2) ideal, -6 dBFS: SQNR vs OSR (BW = fs / (2 OSR); at fs = 2 MHz)")
    for osr in (32, 64, 128, 256):
        out.append(f"   OSR {osr:3d}  BW {2e6 / (2 * osr) / 1e3:6.2f} kHz  SQNR {run(replace(base, osr=osr))[0]:6.1f} dB")
    out.append(f"   1st order, OSR 128: {run(replace(base, order=1))[0]:.1f} dB")

    # 3. op-amp DC gain
    out.append("\n3) first op-amp DC gain at -6 dBFS (second integrator ideal)")
    gains = [20, 30, 50, 100, 200, 300, 1000, 3000]
    sq_gain = [run(replace(base, gain=g))[0] for g in gains]
    for g, s in zip(gains, sq_gain):
        out.append(f"   A = {g:5d} ({20 * np.log10(g):4.1f} dB)  SQNR {s:6.1f} dB")

    # 4. settling: GBW (no slew limit) and slew rate (at a GBW with margin), at the fastest clock
    fs_max = 5e6
    out.append(f"\n4) first op-amp settling at fs = {fs_max / 1e6:.0f} MHz (T/2 - t_no = {(1 / (2 * fs_max) - base.t_no) * 1e9:.0f} ns),"
               f" beta = {base.beta}, Vref = {base.vref} V diff, -6 dBFS")
    gbws = [2e6, 4e6, 6e6, 8e6, 12e6, 20e6, 40e6]
    sq_gbw = [run(replace(base, fs=fs_max, gbw=g))[0] for g in gbws]
    for g, s in zip(gbws, sq_gbw):
        tau = 1 / (2 * np.pi * base.beta * g)
        out.append(f"   GBW {g / 1e6:5.1f} MHz  (T/2 = {(1 / (2 * fs_max) - base.t_no) / tau:4.1f} tau)  SQNR {s:6.1f} dB")
    srs = [5e6, 10e6, 20e6, 30e6, 50e6, 100e6]
    gbw_sr = 20e6
    sq_sr = [run(replace(base, fs=fs_max, gbw=gbw_sr, sr=s))[0] for s in srs]
    out.append(f"   slew rate at GBW = {gbw_sr / 1e6:.0f} MHz (differential V/us; the largest step is a1*(|u|+1)*Vref = "
               f"{base.a1 * 1.5 * base.vref:.2f} V at -6 dBFS):")
    for s, q in zip(srs, sq_sr):
        out.append(f"   SR {s / 1e6:5.0f} V/us  SQNR {q:6.1f} dB")

    # 5. kT/C (with op-amp excess) at -6 dBFS
    out.append(f"\n5) sampling noise 4kT/Cs x {base.excess} (op-amp excess), -6 dBFS, OSR 128, Vref {base.vref} V diff")
    css = [0.1e-12, 0.25e-12, 0.5e-12, 1e-12]
    sq_cs = [run(replace(base, cs=c))[0] for c in css]
    for c, s in zip(css, sq_cs):
        ideal = 10 * np.log10((0.5 * base.vref) ** 2 / 2 / (base.excess * 4 * KT / c / base.osr))
        out.append(f"   Cs = {c * 1e12:4.2f} pF  SNR(noise alone) {ideal:5.1f} dB  SNDR with quantization {s:6.1f} dB")

    # 6. everything at once, at the proposed spec
    spec = replace(base, gain=10 ** (40 / 20), gbw=20e6, sr=50e6, cs=0.5e-12)
    out.append("\n6) proposed first op-amp floor (40 dB at the swing extremes, GBW 20 MHz, SR 50 V/us diff)"
               " + Cs 0.5 pF, -6 dBFS")
    for fs in (0.5e6, 2e6, 5e6):
        out.append(f"   fs {fs / 1e6:3.1f} MHz  BW {fs / 256 / 1e3:5.2f} kHz  SNDR {run(replace(spec, fs=fs))[0]:6.1f} dB")

    txt = "\n".join(out)
    print(txt)
    (RESULTS / "dsm_summary.txt").write_text(txt + "\n")

    # figures
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.plot(amps_db, sq, "o-", label="SQNR (ideal)")
    ax.plot(amps_db, amps_db + sq.max() - amps_db[k], "k:", lw=0.8, label="slope 1 dB/dB")
    ax2 = ax.twinx()
    ax2.plot(amps_db, [r[1] for r in rows], "s--", color="C3", label="max |x1| / Vref")
    ax2.set_ylabel("first-integrator swing (x Vref)", color="C3")
    ax.set(xlabel="input (dBFS)", ylabel="SQNR (dB)", title="2nd-order 1-bit, OSR 128", ylim=(0, 100))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(RESULTS / "dsm_sqnr.png", dpi=130)

    v, fbin, *_ = simulate(base, 0.5)
    s, spec_ = sndr(v, fbin, base.osr)
    f = np.arange(len(spec_)) / N
    psd = spec_ / spec_[fbin - 3:fbin + 4].sum()
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.semilogx(f[1:] * 2e6, 10 * np.log10(psd[1:] + 1e-20), lw=0.6, label=f"output, -6 dBFS ({s:.1f} dB in band)")
    ntf = np.abs(1 - np.exp(-2j * np.pi * f[1:])) ** 4
    ref = (f[1:] > 0.2) & (f[1:] < 0.3)                   # scale the NTF shape to the measured floor
    ntf_level = 10 * np.log10(ntf * np.median(psd[1:][ref]) / np.median(ntf[ref]))
    ax.semilogx(f[1:] * 2e6, ntf_level, "k--", lw=0.8, label="|NTF|^2 = |1 - z^-1|^4 (40 dB/dec)")
    ax.axvline(2e6 / (2 * base.osr), color="g", ls=":", label="BW at fs = 2 MHz")
    ax.set(xlabel="frequency at fs = 2 MHz (Hz)", ylabel="dB relative to the tone", ylim=(-180, 5),
           title="Output spectrum (Hann, 65536 points)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(RESULTS / "dsm_psd.png", dpi=130)

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    ax[0].semilogx(gains, sq_gain, "o-")
    ax[0].set(xlabel="op-amp DC gain (V/V)", ylabel="SQNR (dB)", title="DC gain")
    ax[1].semilogx(np.array(gbws) / 1e6, sq_gbw, "o-", label="no slew limit")
    ax[1].semilogx(np.array(srs) / 1e6, sq_sr, "s--", label=f"slew (V/us) at GBW {gbw_sr / 1e6:.0f} MHz")
    ax[1].set(xlabel="GBW (MHz)  /  SR (V/us)", title=f"Settling at fs = {fs_max / 1e6:.0f} MHz")
    ax[1].legend(fontsize=7)
    ax[2].semilogx(np.array(css) * 1e12, sq_cs, "o-")
    ax[2].set(xlabel="Cs per side (pF)", title=f"kT/C x {base.excess}")
    for a in ax:
        a.grid(alpha=0.3, which="both")
        a.set_ylim(40, 90)
    fig.suptitle("First-integrator non-idealities at -6 dBFS, OSR 128")
    fig.tight_layout()
    fig.savefig(RESULTS / "dsm_nonideal.png", dpi=130)


if __name__ == "__main__":
    main()
