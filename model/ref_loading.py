"""Reference loading by the 1-bit DAC: shared input/DAC caps vs separate DAC caps (PLAN.md §3.6).

A charge-level model of the modulator. It tracks every capacitor's charge and the three
reference nodes (VREFP, VCM, VREFN). The nodes are taps on a resistor ladder from VDD,
each with a decap. Every half period, the caps that switch onto a node share charge with
its decap. The ladder network (3x3, solved exactly with a matrix exponential) then
recovers the node for the rest of the phase. The integrators get the charge each cap
actually delivers, so any reference error that depends on the signal shows up as
distortion in the bitstream.

Schemes (both integrators use the same scheme):
  shared    Classic Boser-Wooley. In phi2, the Cs top plate goes from the sampled input
            to VREFP or VREFN (chosen by v). The reference supplies Cs*(Vref - u_x), and
            which input u_x it sees depends on v, so the average load goes as v*u ~ u^2.
            Vref_diff then moves with u^2, which gives a cubic term (HD3).
  separate  Cs samples the input in phi1 and is dumped to VCM in phi2. A separate Cdac
            is reset to VCM in phi1 and switched to VREFP or VREFN in phi2. VREFP always
            charges exactly one Cdac from VCM to VREFP, so its load is the same every
            cycle. Cdac * (VREFP - VREFN) = Cs * FS keeps the loop coefficient at
            a1 = 0.5. A wider reference spread therefore allows a smaller Cdac, which
            adds less kT/C noise and loads the summing node less.

Not modelled here: op-amp settling, switch resistance and noise. This model isolates the
reference. Outputs: results/ref_loading.txt, results/ref_loading.png
Run:  ../.venv/bin/python ref_loading.py
"""
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.linalg import expm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
N = 2 ** 15
KT = 1.380649e-23 * 300


@dataclass(frozen=True)
class Cfg:
    scheme: str = "shared"      # "shared" or "separate"
    vdd: float = 3.3
    spread: float = 1.0         # VREFP - VREFN (V); FS is always +-1 V differential
    fs: float = 2e6
    osr: int = 128
    i_lad: float = 50e-6        # ladder current (A)
    c_dec: float = 30e-12       # decap on each of VREFP, VCM, VREFN (F)
    cs1: float = 0.5e-12
    ci1: float = 1.0e-12
    cs2: float = 0.1e-12
    ci2: float = 0.2e-12

    @property
    def cdac1(self):
        return self.cs1 * 1.0 / self.spread if self.scheme == "separate" else self.cs1

    @property
    def cdac2(self):
        return self.cs2 * 1.0 / self.spread if self.scheme == "separate" else self.cs2


def ladder(c: Cfg):
    """Conductance matrix G and source vector b for nodes [VREFP, VCM, VREFN], plus nominal taps."""
    vcm = c.vdd / 2
    taps = np.array([vcm + c.spread / 2, vcm, vcm - c.spread / 2])
    seg = np.array([c.vdd - taps[0], taps[0] - taps[1], taps[1] - taps[2], taps[2]])  # top..bottom (V)
    r = seg / c.i_lad                                   # segment resistances
    g = 1 / r
    G = np.array([[g[0] + g[1], -g[1], 0],
                  [-g[1], g[1] + g[2], -g[2]],
                  [0, -g[2], g[2] + g[3]]])
    b = np.array([g[0] * c.vdd, 0.0, 0.0])
    return G, b, taps


def propagator(G, b, cnode, dt):
    """Exact affine map V(t+dt) = A V(t) + d for C dV/dt = -G V + b."""
    Cinv = np.diag(1 / cnode)
    A = expm(-Cinv @ G * dt)
    vss = np.linalg.solve(G, b)
    return A, (np.eye(3) - A) @ vss


def simulate(c: Cfg, amp, fbin):
    G, b, taps = ladder(c)
    th = 1 / (2 * c.fs)
    P, M, Nn = 0, 1, 2                                  # node indices
    cd = np.full(3, c.c_dec)
    if c.scheme == "shared":
        # phi1: nothing on the references. phi2: one Cs1 and one Cs2 on each of VREFP and VREFN.
        ph1 = propagator(G, b, cd, th)
        ph2 = propagator(G, b, cd + np.array([c.cs1 + c.cs2, 0, c.cs1 + c.cs2]), th)
    else:
        # phi1: all four Cdacs reset onto VCM. phi2: one Cdac1 + one Cdac2 on each reference,
        # and all four Cs dumped onto VCM.
        ph1 = propagator(G, b, cd + np.array([0, 2 * (c.cdac1 + c.cdac2), 0]), th)
        ph2 = propagator(G, b, cd + np.array([c.cdac1 + c.cdac2, 2 * (c.cs1 + c.cs2),
                                              c.cdac1 + c.cdac2]), th)
    V = np.linalg.solve(G, b)
    for _ in range(int(20 * c.c_dec * 1e6 / max(c.i_lad, 1e-9) + 50)):   # settle the DC point
        V = ph1[0] @ V + ph1[1]
        V = ph2[0] @ V + ph2[1]
    vcm0 = taps[1]
    u = amp * np.sin(2 * np.pi * fbin * np.arange(N) / N)
    x1 = x2 = 0.0
    bits = np.empty(N)
    vsum = np.zeros(3)
    # top-plate voltages of the separate DAC caps after their phi1 reset (one per side, both integrators)
    vdac_reset = V[M]
    for n in range(N):
        q = 1.0 if x2 >= 0 else -1.0
        bits[n] = q
        up, un = vcm0 + u[n] / 2, vcm0 - u[n] / 2
        x1p, x1n = vcm0 + x1 / 2, vcm0 - x1 / 2
        # ---- phi2: charge sharing at the instant of switching, then ladder recovery
        Q = c.c_dec * V
        if c.scheme == "shared":
            # VREFP gets the Cs on the side v selects; VREFN gets the other one
            uP, uN = (up, un) if q > 0 else (un, up)
            xP, xN = (x1p, x1n) if q > 0 else (x1n, x1p)
            Q[P] += c.cs1 * uP + c.cs2 * xP
            Q[Nn] += c.cs1 * uN + c.cs2 * xN
        else:
            Q[P] += (c.cdac1 + c.cdac2) * vdac_reset
            Q[Nn] += (c.cdac1 + c.cdac2) * vdac_reset
            Q[M] += c.cs1 * (up + un) + c.cs2 * (x1p + x1n)
        cnode2 = c.c_dec + (np.array([c.cs1 + c.cs2, 0, c.cs1 + c.cs2]) if c.scheme == "shared"
                            else np.array([c.cdac1 + c.cdac2, 2 * (c.cs1 + c.cs2), c.cdac1 + c.cdac2]))
        V = Q / cnode2
        V = ph2[0] @ V + ph2[1]
        vrp, vcm_, vrn = V
        sel_p, sel_n = (vrp, vrn) if q > 0 else (vrn, vrp)
        if c.scheme == "shared":
            d1 = c.cs1 * ((up - sel_p) - (un - sel_n)) / c.ci1
            d2 = c.cs2 * ((x1p - sel_p) - (x1n - sel_n)) / c.ci2
        else:
            d1 = (c.cs1 * (u[n]) - c.cdac1 * (sel_p - sel_n)) / c.ci1
            d2 = (c.cs2 * x1 - c.cdac2 * (sel_p - sel_n)) / c.ci2
        x1, x2 = x1 + d1, x2 + d2
        # ---- phi1: separate scheme resets the Cdacs onto VCM (they hold VREFP / VREFN)
        if c.scheme == "separate":
            Q = c.c_dec * V
            Q[M] += (c.cdac1 + c.cdac2) * (vrp + vrn)
            V = Q / (c.c_dec + np.array([0, 2 * (c.cdac1 + c.cdac2), 0]))
        V = ph1[0] @ V + ph1[1]
        vdac_reset = V[M]
        vsum += V
    return bits, vsum / N, taps


def analyse(bits, fbin, osr):
    w = np.hanning(N)
    spec = np.abs(np.fft.rfft(bits * w)) ** 2
    bw = N // (2 * osr)
    sig = spec[fbin - 3:fbin + 4].sum()
    h3 = spec[3 * fbin - 3:3 * fbin + 4].sum()
    h2 = spec[2 * fbin - 3:2 * fbin + 4].sum()
    noise = spec[1:bw].sum() - sig
    return 10 * np.log10(sig / noise), 10 * np.log10(h3 / sig), 10 * np.log10(h2 / sig), spec


def run(c: Cfg, amp=0.5):
    bw = N // (2 * c.osr)
    fbin = int(bw / 9) | 1                 # low tone so HD3 (3 x fbin) lands in band
    bits, vavg, taps = simulate(c, amp, fbin)
    s, h3, h2, spec = analyse(bits, fbin, c.osr)
    return dict(sndr=s, hd3=h3, hd2=h2, spec=spec, fbin=fbin, droop=vavg - taps,
                rth=thevenin(c))


def thevenin(c: Cfg):
    G, _, _ = ladder(c)
    return np.linalg.inv(G)[0, 0]          # VREFP driving-point resistance (ohm)


def ktc_factor(c: Cfg):
    """In-band kT/C noise power relative to the shared-cap design with the same Cs1."""
    return 1 + (c.cdac1 / c.cs1 if c.scheme == "separate" else 0)


def main():
    RESULTS.mkdir(exist_ok=True)
    out = ["Reference loading by the 1-bit DAC (model/ref_loading.py)",
           f"N = {N}, OSR 128, fs 2 MHz, -6 dBFS tone at bin {int(N // 256 / 9) | 1} (HD3 in band), "
           "Cs1 0.5 / Ci1 1 / Cs2 0.1 / Ci2 0.2 pF",
           "Only the reference is non-ideal here (ideal op-amps and switches, no noise).",
           "VREFP err = VREFP at the end of each cycle minus its unloaded value, averaged.", ""]
    base = Cfg()
    ilads = [10e-6, 30e-6, 100e-6, 300e-6, 1e-3, 3e-3]
    rows = {}
    for label, cfg in [("shared, 1 V spread, 30 pF", base),
                       ("shared, 1 V spread, 100 pF", replace(base, c_dec=100e-12)),
                       ("separate, 1 V spread (Cdac = Cs), 30 pF", replace(base, scheme="separate")),
                       ("separate, 2 V spread (Cdac = Cs/2), 30 pF",
                        replace(base, scheme="separate", spread=2.0))]:
        rows[label] = [run(replace(cfg, i_lad=i)) for i in ilads]
    ideal = run(replace(base, i_lad=1e3))          # effectively ideal references
    out.append(f"Ideal references: SQNR {ideal['sndr']:.1f} dB, HD3 {ideal['hd3']:.1f} dBc")
    out.append("")
    out.append(f"{'scheme':42s} {'I_lad':>7s} {'R_th':>8s} {'SNDR':>6s} {'HD3':>7s} {'VREFP err':>12s}")
    out.append(f"{'':42s} {'uA':>7s} {'kohm':>8s} {'dB':>6s} {'dBc':>7s} {'mV':>12s}")
    for label, rs in rows.items():
        for i, r in zip(ilads, rs):
            out.append(f"{label:42s} {i * 1e6:7.0f} {r['rth'] / 1e3:8.2f} {r['sndr']:6.1f} {r['hd3']:7.1f} "
                       f"{r['droop'][0] * 1e3:12.2f}")
        out.append("")
    # first-order explanation for the shared scheme
    out += ["Why shared caps are sometimes clean: a kick takes Cs*(VREFP - VCM - v*u/2) from VREFP and the",
            "mirror image from VREFN, so right after it Vref_diff = Vref0 - e*(1 - v*u), with e ~ Cs/C_dec.",
            "The DAC delivers v*Vref_diff = v*(Vref0 - e) + e*u: because v^2 = 1 the signal part is LINEAR",
            "in u (a gain error). Distortion comes only from the part of a kick still left in the NEXT cycle,",
            "when v has changed (v[n]*v[n-1]*u is not linear). A node that recovers within T/2 is clean; a",
            "slow node (tau >> T) keeps the average droop, and then",
            "  HD3 ~ (Z_PP - Z_PN) * fs * (Cs1 + Cs2) * A^2 / 4      (A in units of Vref)",
            "where Z_PP - Z_PN is the ladder's VREFP transfer resistance for a current taken from VREFP and",
            "returned into VREFN. More decap makes it WORSE in between, because it slows the recovery.",
            ""]
    for i in (10e-6, 30e-6):
        cfg = replace(base, i_lad=i, c_dec=100e-12)
        Z = np.linalg.inv(ladder(cfg)[0])
        k = (Z[0, 0] - Z[0, 2]) * base.fs * (base.cs1 + base.cs2)
        sim = rows["shared, 1 V spread, 100 pF"][ilads.index(i)]["hd3"]
        out.append(f"  100 pF, I_lad {i * 1e6:3.0f} uA (slow node): predicted HD3 {20 * np.log10(k * 0.25 / 4):6.1f} dBc, "
                   f"simulated {sim:6.1f} dBc")
    out += ["",
            "Separate DAC caps take the same charge every cycle, so they are clean at any ladder current and",
            "any decap. That lets the decap filter supply and ladder noise (which the bitstream would",
            "otherwise mix down from around fs/2) without trading it against distortion.",
            ""]
    out += ["",
            "kT/C cost of the separate DAC cap (in-band noise power relative to shared, same Cs1):",
            f"  Cdac = Cs   (1 V spread): x{ktc_factor(replace(base, scheme='separate')):.2f} "
            f"({10 * np.log10(ktc_factor(replace(base, scheme='separate'))):.1f} dB)",
            f"  Cdac = Cs/2 (2 V spread): x{ktc_factor(replace(base, scheme='separate', spread=2.0)):.2f} "
            f"({10 * np.log10(ktc_factor(replace(base, scheme='separate', spread=2.0))):.1f} dB)"]
    cgg = 0.27e-12
    for lab, cd in (("shared", 0.0), ("Cdac = Cs/2", 0.25e-12), ("Cdac = Cs", 0.5e-12)):
        beta = base.ci1 / (base.ci1 + base.cs1 + cd + 0.1e-12 + cgg)
        out.append(f"  beta in phi2, {lab:12s}: {beta:.2f}")
    txt = "\n".join(out)
    print(txt)
    (RESULTS / "ref_loading.txt").write_text(txt + "\n")

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for label, rs in rows.items():
        ax[0].semilogx(np.array(ilads) * 1e6, [r["hd3"] for r in rs], "o-", label=label)
    ax[0].axhline(-85, color="k", ls=":", lw=0.8, label="-85 dBc target")
    ax[0].set(xlabel="ladder current (uA)", ylabel="HD3 (dBc) at -6 dBFS", title="Reference-loading distortion")
    ax[0].legend(fontsize=7)
    f = np.arange(N // 2 + 1) / N * 2e6
    for label, idx in (("shared, 1 V spread, 30 pF", 1), ("separate, 2 V spread (Cdac = Cs/2), 30 pF", 1)):
        r = rows[label][idx]
        ax[1].semilogx(f[1:], 10 * np.log10(r["spec"][1:] / r["spec"].max()), lw=0.6,
                       label=f"{label}, {ilads[idx] * 1e6:.0f} uA")
    ax[1].axvline(2e6 / 256, color="k", ls=":", lw=0.8)
    ax[1].set(xlabel="Hz", ylabel="dB (re tone)", title="Bitstream spectrum", xlim=(100, 1e6), ylim=(-160, 5))
    ax[1].legend(fontsize=7)
    for a in ax:
        a.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(RESULTS / "ref_loading.png", dpi=130)


if __name__ == "__main__":
    main()
