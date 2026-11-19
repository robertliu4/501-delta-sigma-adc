"""Non-overlapping clock generator from standard cells (PLAN.md §3.4), checked at 5 corners.

clkgen (dsm_net.py) turns `clk` into phi1/phi1d (high while clk is low) and phi2/phi2d,
each with a complement for the transmission gates. Every output is loaded with LOAD
(about ten TG gates). Edges are measured over a few cycles at 2 MHz and 5 MHz:
  non-overlap   phi_d of one phase is off before the other phase turns on. A TG is off once
                its NMOS gate is below Vth (about 20 % VDD) AND its PMOS gate (phi_b) is above
                VDD - |Vtp| (about 80 %), so it is measured between the 20 % / 80 % points.
  bottom plate  phi (summing-node switch) falls before phi_d (input switch), at 50 %.
  skew          phi vs phi_b at 50 %.
Output: results/clockgen.txt
"""
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import spice
import dsm_net

LOAD = 0.3e-12
FREQS = (2e6, 5e6)
NCYC = 4


def edges(t, y, level, rising):
    s = np.sign(y - level)
    idx = np.where((s[:-1] < 0) & (s[1:] >= 0))[0] if rising else np.where((s[:-1] > 0) & (s[1:] <= 0))[0]
    return np.array([t[i] + (level - y[i]) * (t[i + 1] - t[i]) / (y[i + 1] - y[i]) for i in idx])


def run(corner, f):
    model, temp, vdd = spice.CORNERS[corner]
    T = 1 / f
    tag = f"clk_{corner}_{f / 1e6:.0f}"
    sigs = ["ph1", "ph1_b", "ph1d", "ph1d_b", "ph2", "ph2_b", "ph2d", "ph2d_b"]
    loads = "\n".join(f"C{s} {s} 0 {LOAD}" for s in sigs)
    deck = f"""* clock generator {tag}
{spice.models(model, mim=False, res=False, stdcells=True)}
.temp {temp}
VDD vdd 0 {vdd}
VSS vss 0 0
{dsm_net.clkgen_subckt()}
VCLK clk 0 PULSE(0 {vdd} {T / 4} 2n 2n {T / 2 - 2e-9} {T})
XCG clk {" ".join(sigs)} vdd vss clkgen
{loads}
.control
tran 0.05n {(NCYC + 1) * T} 0 0.05n
wrdata {tag}.txt {" ".join(f"v({s})" for s in sigs)} i(VDD)
.endc
.end
"""
    (spice.OUT / f"{tag}.txt").unlink(missing_ok=True)
    spice.run(tag, deck)
    d = spice.wrdata(f"{tag}.txt")
    t = d[:, 0]
    v = {s: d[:, 2 * i + 1] for i, s in enumerate(sigs)}
    idd = -np.mean(d[:, 2 * len(sigs) + 1][t > T])
    lo, mid, hi = 0.2 * vdd, 0.5 * vdd, 0.8 * vdd
    late = lambda arr: arr[arr > T]

    def gap(off_ph, on_ph):
        """Smallest time from off_ph (and its _b) being off to on_ph (and its _b) starting to turn on."""
        off_n = late(edges(t, v[off_ph], lo, False))
        off_p = late(edges(t, v[off_ph + "_b"], hi, True))
        on_n = late(edges(t, v[on_ph], lo, True))
        on_p = late(edges(t, v[on_ph + "_b"], hi, False))
        g = []
        for a in on_n:
            prev = off_n[off_n < a]
            if len(prev):
                g.append(a - prev[-1])
        for a in on_p:
            prev = off_p[off_p < a]
            if len(prev):
                g.append(a - prev[-1])
        return min(g) if g else np.nan

    def bp(early, late_ph):
        e = late(edges(t, v[early], mid, False))
        l = late(edges(t, v[late_ph], mid, False))
        return min(l[l > x][0] - x for x in e if (l > x).any())

    def skew(ph):
        a = late(edges(t, v[ph], mid, True))
        b = late(edges(t, v[ph + "_b"], mid, False))
        return max(abs(b[np.argmin(np.abs(b - x))] - x) for x in a)

    r1, f1 = late(edges(t, v["ph1"], mid, True)), late(edges(t, v["ph1d"], mid, False))
    high1 = np.array([x - r1[r1 < x][-1] for x in f1 if (r1 < x).any()])
    return dict(corner=corner, f=f, no12=gap("ph1d", "ph2"), no21=gap("ph2d", "ph1"),
                bp1=bp("ph1", "ph1d"), bp2=bp("ph2", "ph2d"),
                skew=max(skew(p) for p in ("ph1", "ph1d", "ph2", "ph2d")), idd=idd,
                width=float(np.median(high1)) if len(high1) else np.nan)


def main():
    jobs = [(c, f) for f in FREQS for c in spice.CORNERS]
    with ThreadPoolExecutor(max_workers=5) as pool:
        res = list(pool.map(lambda a: run(*a), jobs))
    out = ["Non-overlapping clock generator (dsm_net.clkgen_subckt, standard cells at VDPWR)",
           f"delay cells {dsm_net.CLK_DLY}, each output loaded with {LOAD * 1e12:.1f} pF",
           "", f"{'corner':12s} {'fclk':>5s} {'no 1->2':>8s} {'no 2->1':>8s} {'bp ph1':>7s} {'bp ph2':>7s} "
           f"{'skew':>6s} {'ph1 width':>9s} {'IDD':>6s}",
           f"{'':12s} {'MHz':>5s} {'ns':>8s} {'ns':>8s} {'ns':>7s} {'ns':>7s} {'ns':>6s} {'ns':>9s} {'uA':>6s}"]
    for r in res:
        out.append(f"{r['corner']:12s} {r['f'] / 1e6:5.0f} {r['no12'] * 1e9:8.2f} {r['no21'] * 1e9:8.2f} "
                   f"{r['bp1'] * 1e9:7.2f} {r['bp2'] * 1e9:7.2f} {r['skew'] * 1e9:6.2f} {r['width'] * 1e9:9.1f} "
                   f"{r['idd'] * 1e6:6.1f}")
    out += ["", "  no = non-overlap: from one phase's late tap being off (NMOS gate < 20 % VDD and PMOS gate",
            "  > 80 % VDD) to the other phase starting to turn on, worst of the two TG halves.",
            "  bp = bottom-plate advance: phi falls before phi_d (50 %). ph1 width = phi1 rise to phi1d fall."]
    txt = "\n".join(out)
    print(txt)
    (spice.RESULTS / "clockgen.txt").write_text(txt + "\n")


if __name__ == "__main__":
    main()
