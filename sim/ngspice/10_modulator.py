"""Transistor-level modulator transient (PLAN.md §5 W1 checkpoint, §6).

Everything is transistor level except the ladder resistors and decaps (ideal), the
input source and the `clk` square wave:
  - OTA1 and OTA2 with the real beta-multiplier bias and switched-cap CMFB.
  - Transmission-gate switches with bottom-plate sampling.
  - Separate DAC caps (Cdac = Cs/2 on a 2 V reference spread).
  - StrongARM comparator with inverters and a NOR SR latch, and the DAC gating logic.
  - The standard-cell non-overlapping clock generator (11_clockgen.py).
Netlist: dsm_net.py.

One run per corner, all in parallel: NFFT output bits after DISCARD cycles. The first
cycles cover reset release and the CMFB pulling the output CM in from the op point, which
works as a CM step test. Transient noise is off, so the SNDR here is quantization plus
distortion plus settling. kT/C is added analytically in the summary.
Outputs: results/modulator.txt, results/modulator.png
  --clkgen      use the standard-cell clock generator instead of ideal phases
                (results/modulator_clkgen.*; one tt run with --nfft 4096 takes a few hours)
  --nfft N      number of output bits (default 8192)
  corners...    subset of spice.CORNERS (default: all five, in parallel)
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import spice
import dsm_net

NFFT = 8192
DISCARD = 64
OSR = 128
FBIN = 7                     # 1.71 kHz at fs = 2 MHz; HD3 lands in band (bin 21 of 32)
AMP = 0.5                    # V differential: -6 dBFS (FS = +-1 V diff)
FS = 2e6
T = 1 / FS
RESET = 2
TSTEP = 50e-9                # output grid; samples at 450 ns into each cycle (phi2, settled)
KT = 1.380649e-23 * 300
REAL_CLOCKS = False         # --clkgen: standard-cell clock generator (about 15x slower per cycle)
PREFIX = "dsm"              # deck/data file prefix in out/
OUTNAME = "modulator"       # results/<OUTNAME>.txt and .png

DEVS = ["mt", "m1", "m2", "mp3", "mp4", "mp5", "mp6", "mn5", "mn6", "mn3", "mn4"]
MARGINS = [(f"{o}.{d}", f"abs(@m.x{o}ota.{d}[vds])-abs(@m.x{o}ota.{d}[vdsat])")
           for o in ("i1", "i2") for d in DEVS]
CURRENTS = [("ota1 tail", "@m.xi1ota.mt[id]"), ("ota1 bottom", "@m.xi1ota.mn3[id]"),
            ("ota2 tail", "@m.xi2ota.mt[id]"), ("ota2 bottom", "@m.xi2ota.mn3[id]"),
            ("bias ref", "@m.xbias.mb1[id]")]
BASE = ["q", "x1", "x2", "cm1", "cm2", "vref", "vbn1", "vbn2", "idd"]


def probes():
    """.save needs the raw device vectors; wrdata takes the expressions."""
    raw = set()
    for _, e in MARGINS + CURRENTS:
        for tok in e.replace("abs(", " ").replace(")", " ").replace("-", " ").split():
            if tok.startswith("@"):
                raw.add(tok)
    return sorted(raw), [e for _, e in MARGINS + CURRENTS]


def ideal_bits(n_total, start):
    """Behavioural loop with the same input samples (ideal integrators, a1 = a2 = 0.5)."""
    f_in = FBIN / (NFFT * T)
    t_rst = RESET * T + 0.75 * T
    x1 = x2 = 0.0
    bits = []
    for n in range(n_total):
        v = 1.0 if x2 >= 0 else -1.0
        bits.append(v)
        ts = n * T + T / 2 - dsm_net.T_NO        # sampled when phi1d opens
        u = AMP * np.sin(2 * np.pi * f_in * (ts - t_rst)) if ts > t_rst else 0.0
        x1, x2 = x1 + 0.5 * (u - v), x2 + 0.5 * (x1 - v)
    return np.array(bits[start:start + NFFT])


def spectrum(bits):
    w = np.hanning(NFFT)
    spec = np.abs(np.fft.rfft(bits * w)) ** 2
    bw = NFFT // (2 * OSR)
    sig = spec[FBIN - 3:FBIN + 4].sum()
    noise = spec[1:bw].sum() - sig
    hd = {k: spec[k * FBIN - 3:k * FBIN + 4].sum() for k in (2, 3)}
    return (10 * np.log10(sig / noise), {k: 10 * np.log10(v / sig) for k, v in hd.items()}, spec,
            sig / (w ** 2).sum() * 2)


def run_corner(corner):
    raw, exprs = probes()
    tag = f"{PREFIX}_{corner}"
    (spice.OUT / f"{tag}.txt").unlink(missing_ok=True)
    ncyc = NFFT + DISCARD + 1
    deck = dsm_net.modulator(corner, ncyc, AMP, FBIN, NFFT, fs=FS, reset_cycles=RESET,
                             probes=raw, tag=tag, tstep=TSTEP, real_clocks=REAL_CLOCKS)
    # wrdata gets the margin/current expressions instead of the raw device vectors
    deck = deck.replace(" ".join(raw) + "\n.endc", " ".join(exprs) + "\n.endc")
    t0 = time.time()
    log = spice.run(tag, deck, timeout=6 * 3600)
    wall = time.time() - t0
    d = spice.wrdata(f"{tag}.txt")
    t = d[:, 0]
    names = BASE + [m[0] for m in MARGINS] + [c[0] for c in CURRENTS]
    col = {n: d[:, 2 * i + 1] for i, n in enumerate(names)}
    vdd = spice.CORNERS[corner][2]
    start = RESET + DISCARD + 1
    n = np.arange(start, start + NFFT)
    ts = n * T + 450e-9
    s = {k: np.interp(ts, t, col[k]) for k in col}
    bits = np.where(s["q"] > vdd / 2, 1.0, -1.0)
    sndr, hd, spec, _ = spectrum(bits)
    # first cycles: output CM converging from the op point (CMFB step response)
    n0 = np.arange(0, start)
    cm_early = {k: np.interp(n0 * T + 450e-9, t, col[k]) for k in ("cm1", "cm2")}
    steady = t > start * T
    marg = {m[0]: float(np.min(col[m[0]][steady])) for m in MARGINS}
    cur = {c[0]: float(np.mean(np.abs(col[c[0]][steady]))) for c in CURRENTS}
    return dict(corner=corner, vdd=vdd, sndr=sndr, hd=hd, spec=spec, bits=bits, s=s,
                cm_early=cm_early, marg=marg, cur=cur, idd=float(-np.mean(col["idd"][steady])),
                wall=wall, log=log, ones=float((bits > 0).mean()))


def main():
    global REAL_CLOCKS, NFFT, FBIN, PREFIX, OUTNAME
    args = sys.argv[1:]
    if "--clkgen" in args:
        args.remove("--clkgen")
        REAL_CLOCKS, PREFIX, OUTNAME = True, "dsmc", "modulator_clkgen"
    if "--nfft" in args:
        i = args.index("--nfft")
        NFFT = int(args[i + 1])
        FBIN = max(3, (NFFT // (2 * OSR)) // 4 | 1)
        del args[i:i + 2]
    keys = args or list(spice.CORNERS)
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        res = list(pool.map(run_corner, keys))
    ideal = ideal_bits(RESET + DISCARD + 1 + NFFT, RESET + DISCARD + 1)
    sq, hd_i, spec_i, _ = spectrum(ideal)
    cs1, cdac1 = dsm_net.CAPS["cs1"], dsm_net.CAPS["cs1"] / dsm_net.SPREAD
    ktc = 1.5 * 4 * KT * (cs1 + cdac1) / cs1 ** 2 / OSR      # in-band input-referred power (V^2 diff)
    p_sig = (AMP / np.sqrt(2)) ** 2

    out = ["Transistor-level 2nd-order delta-sigma modulator (sim/ngspice/10_modulator.py, netlist dsm_net.py)",
           f"fs {FS / 1e6:.0f} MHz, OSR {OSR}, {NFFT} bits after {DISCARD} discarded cycles, "
           f"-6 dBFS ({AMP} V diff peak) tone at {FBIN / (NFFT * T) / 1e3:.2f} kHz",
           "Transistor level: OTAs + real bias + SC CMFB, TG switches, separate DAC caps (Cdac = Cs/2, 2 V spread),",
           "StrongARM + NOR SR latch, DAC logic" + (", standard-cell clock generator." if REAL_CLOCKS else "."),
           "Ideal: " + ("" if REAL_CLOCKS else "clock phases, ") + "ladder resistors and decaps, input source. No noise.",
           "",
           f"Ideal behavioural loop, same samples: SQNR {sq:.1f} dB, HD3 {hd_i[3]:.1f} dBc",
           f"kT/C (Cs1 + Cdac1, x1.5 op-amp excess) alone would limit SNR to "
           f"{10 * np.log10(p_sig / ktc):.1f} dB at this level",
           "",
           f"{'corner':12s} {'SNDR':>6s} {'+kT/C':>6s} {'HD2':>6s} {'HD3':>6s} {'ones':>6s} {'|x1|max':>8s} "
           f"{'|x2|max':>8s} {'CM1':>13s} {'CM2':>13s} {'Vref':>6s} {'IDD':>6s} {'sim':>5s}",
           f"{'':12s} {'dB':>6s} {'dB':>6s} {'dBc':>6s} {'dBc':>6s} {'':>6s} {'V':>8s} {'V':>8s} "
           f"{'min..max V':>13s} {'min..max V':>13s} {'V':>6s} {'uA':>6s} {'min':>5s}"]
    for r in res:
        s = r["s"]
        p_q = p_sig / 10 ** (r["sndr"] / 10)
        tot = 10 * np.log10(p_sig / (p_q + ktc))
        out.append(f"{r['corner']:12s} {r['sndr']:6.1f} {tot:6.1f} {r['hd'][2]:6.1f} {r['hd'][3]:6.1f} "
                   f"{r['ones']:6.3f} {np.abs(s['x1']).max():8.3f} {np.abs(s['x2']).max():8.3f} "
                   f"{s['cm1'].min():6.3f}..{s['cm1'].max():5.3f} {s['cm2'].min():6.3f}..{s['cm2'].max():5.3f} "
                   f"{np.mean(s['vref']):6.3f} {r['idd'] * 1e6:6.0f} {r['wall'] / 60:5.1f}")
    out += ["", "  SNDR = from the bitstream (Hann window, signal = bin +-3, DC skipped); +kT/C adds the analytic",
            "  sampling noise. |x|max and CM are sampled 450 ns into each cycle (phi2, settled), after the discard.",
            "", "Minimum saturation margin |Vds| - |Vdsat| during operation (mV, 50 ns grid, after the discard):"]
    hdr = f"  {'device':8s}" + "".join(f"{r['corner'][:5]:>8s}" for r in res)
    out.append(hdr)
    for m, _ in MARGINS:
        out.append(f"  {m:8s}" + "".join(f"{r['marg'][m] * 1e3:8.0f}" for r in res))
    out += ["", "Bias currents (uA, mean during operation):"]
    for c, _ in CURRENTS:
        out.append(f"  {c:12s}" + "".join(f"{r['cur'][c] * 1e6:8.1f}" for r in res))
    out += ["", "CMFB step response (output CM at the end of phi2, from the op point; cycles 0-10):"]
    for r in res:
        for k in ("cm1", "cm2"):
            out.append(f"  {r['corner'][:5]} {k}: " + " ".join(f"{v:.3f}" for v in r["cm_early"][k][:11]))
    txt = "\n".join(out)
    print(txt)
    (spice.RESULTS / f"{OUTNAME}.txt").write_text(txt + "\n")

    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    f = np.arange(NFFT // 2 + 1) / NFFT * FS
    ref = spec_i.max()
    ax[0, 0].semilogx(f[1:], 10 * np.log10(spec_i[1:] / ref + 1e-30), color="0.6", lw=0.7,
                      label=f"ideal model ({sq:.1f} dB)")
    for r in res:
        ax[0, 0].semilogx(f[1:], 10 * np.log10(r["spec"][1:] / ref + 1e-30), lw=0.6,
                          label=f"{r['corner']} ({r['sndr']:.1f} dB)")
    ax[0, 0].axvline(FS / (2 * OSR), color="k", ls=":", lw=0.8)
    ax[0, 0].set(xlabel="Hz", ylabel="dB re tone", title="Bitstream spectrum (Hann)", xlim=(200, 1e6),
                 ylim=(-150, 5))
    ax[0, 0].legend(fontsize=7)
    r0 = res[0]
    k = np.arange(400)
    ax[0, 1].plot(k, r0["s"]["x1"][:400], lw=0.8, label="x1 (V diff)")
    ax[0, 1].plot(k, r0["s"]["x2"][:400], lw=0.8, label="x2 (V diff)")
    ax[0, 1].step(k, r0["bits"][:400] * 0.2 - 2.0, lw=0.6, color="k", label="bit (offset)")
    ax[0, 1].set(xlabel="cycle", title=f"Integrator outputs, {r0['corner']}")
    ax[0, 1].legend(fontsize=7)
    for r in res:
        ax[1, 0].plot(r["cm_early"]["cm1"], "o-", ms=2, lw=0.8, label=f"{r['corner']} CM1")
    ax[1, 0].axhline(r0["vdd"] / 2, color="k", ls=":", lw=0.8)
    ax[1, 0].set(xlabel="cycle", ylabel="V", title="OTA1 output CM from the op point (SC CMFB step)")
    ax[1, 0].legend(fontsize=7)
    for r in res:
        ax[1, 1].hist(r["s"]["x1"], bins=80, histtype="step", label=r["corner"])
    ax[1, 1].set(xlabel="x1 (V diff)", title="First-integrator output distribution")
    ax[1, 1].legend(fontsize=7)
    for a in ax.flat:
        a.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(spice.RESULTS / f"{OUTNAME}.png", dpi=130)


if __name__ == "__main__":
    main()
