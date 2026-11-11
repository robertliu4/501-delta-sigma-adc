"""First-integrator op-amp: fully differential folded cascode, first-pass sizing (PLAN.md §3.2).

NMOS input pair (input CM = VDD/2), PMOS top sources with PMOS cascodes, NMOS cascoded
bottom sources. The bias currents are ideal, and every bias voltage comes from a diode
replica so it tracks the corner. CMFB is ideal here (a VCVS from the output CM to the
bottom-source gates); the real switched-cap CMFB comes later.

Specs it is checked against come from model/dsm_model.py (results/dsm_summary.txt):
  DC gain >= 40 dB over the first-integrator swing, |Vod| <= 1.6 V (1.6 x Vref, Vref = 1 V diff)
  loop crossover with beta = 0.59 >= 6 MHz (GBW >= ~10 MHz), PM >= 60 deg
  differential slew rate >= 30 V/us (fs = 5 MHz); settle the largest step (0.75 V diff)
  to 0.1 % in 90 ns (T/2 - t_no at fs = 5 MHz)
  in-band (10 Hz - 7.8 kHz) input-referred noise well below the 16 uV rms kT/C noise of Cs = 0.5 pF
Tests per corner: operating point (saturation margins), open-loop AC, DC gain vs output
swing, noise, and a closed-loop capacitive step (Cs 0.5 pF, Ci 1 pF, Cp 0.1 pF, CL 0.3 pF).
Outputs: results/ota_fc.txt, results/ota_fc.png
"""
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import spice

# device sizes: (W per finger um, L um, fingers) and branch currents
S = dict(
    inp=(10.0, 2.0, 6),     # M1/M2 input pair: gm/ID ~ 15; W*L = 120 um^2 for 1/f noise
    tail=(5.5, 1.0, 2),     # MT tail
    ptop=(10.0, 4.0, 7),    # MP3/MP4 top sources (I_in + I_fold): long L, low gm/ID for 1/f noise
    pcas=(8.5, 0.5, 2),     # MP5/MP6 PMOS cascodes
    ncas=(5.0, 0.5, 1),     # MN5/MN6 NMOS cascodes
    nbot=(10.0, 8.0, 2),    # MN3/MN4 bottom sources (CMFB-controlled): GF NMOS 1/f is ~4x PMOS
)
I_TAIL = 40e-6
I_FOLD = 20e-6              # current in each output branch; >= I_TAIL/2, so SR_diff = I_TAIL / C_eff
K_PCAS = 16.0               # wide-swing bias: diode width = cascode width / K; large because the
K_NCAS = 16.0               # long-L sources need ~0.3 V more Vds than a square-law K = 4 gives
BETA = 0.59                 # integration-phase feedback factor (model/dsm_model.py)
CL_EFF = 0.7e-12            # per side: CL + Ci*(Cs+Cp)/(Ci+Cs+Cp)
CS, CI, CP, CL = 0.5e-12, 1.0e-12, 0.1e-12, 0.3e-12
STEP = 0.75                 # largest first-integrator output step, V differential
VOD_MAX = 1.6
BW = 7.8125e3


def dev(name, d, g, s, b, kind, key, w_scale=1.0):
    w, l, m = S[key]
    model = "nfet_03v3" if kind == "n" else "pfet_03v3"
    return f"{name} {d} {g} {s} {b} {model} W={w * w_scale:.3f}u L={l}u m={m}"


def core():
    """The op-amp and its bias. Nodes: inp inn outp outn vdd 0 vcm."""
    i_top = I_TAIL / 2 + I_FOLD
    return "\n".join([
        "* bias replicas (ideal currents, diode-connected copies of each device)",
        f"IBT vdd vbt {I_TAIL}", dev("MBT", "vbt", "vbt", "0", "0", "n", "tail"),
        f"IBP vbp 0 {i_top}", dev("MBP", "vbp", "vbp", "vdd", "vdd", "p", "ptop"),
        f"IBN vdd vbn0 {I_FOLD}", dev("MBN", "vbn0", "vbn0", "0", "0", "n", "nbot"),
        f"IBPC vcp 0 {I_FOLD}", dev("MBPC", "vcp", "vcp", "vdd", "vdd", "p", "pcas", 1 / K_PCAS),
        f"IBNC vdd vcn {I_FOLD}", dev("MBNC", "vcn", "vcn", "0", "0", "n", "ncas", 1 / K_NCAS),
        "* input pair and tail",
        dev("MT", "tail", "vbt", "0", "0", "n", "tail"),
        dev("M1", "f1", "inp", "tail", "0", "n", "inp"),
        dev("M2", "f2", "inn", "tail", "0", "n", "inp"),
        "* top sources and PMOS cascodes (inp up -> f1 down -> outn down)",
        dev("MP3", "f1", "vbp", "vdd", "vdd", "p", "ptop"),
        dev("MP4", "f2", "vbp", "vdd", "vdd", "p", "ptop"),
        dev("MP5", "outn", "vcp", "f1", "vdd", "p", "pcas"),
        dev("MP6", "outp", "vcp", "f2", "vdd", "p", "pcas"),
        "* NMOS cascodes and CMFB-controlled bottom sources",
        dev("MN5", "outn", "vcn", "b1", "0", "n", "ncas"),
        dev("MN6", "outp", "vcn", "b2", "0", "n", "ncas"),
        dev("MN3", "b1", "vbn", "0", "0", "n", "nbot"),
        dev("MN4", "b2", "vbn", "0", "0", "n", "nbot"),
        "* ideal CMFB",
        "Bocm ocm 0 V={(v(outp)+v(outn))/2}",
        "Ecm vbn vbn0 ocm vcm 3",            # gain 30 made the CM loop unstable (bursts in the step test)
    ])


DEVICES = ["mt", "m1", "m2", "mp3", "mp4", "mp5", "mp6", "mn5", "mn6", "mn3", "mn4"]
GROUP = {"mt": "MT tail", "m1": "M1/M2 input pair", "m2": "M1/M2 input pair",
         "mp3": "MP3/MP4 top sources", "mp4": "MP3/MP4 top sources",
         "mp5": "MP5/MP6 PMOS cascodes", "mp6": "MP5/MP6 PMOS cascodes",
         "mn3": "MN3/MN4 bottom sources", "mn4": "MN3/MN4 bottom sources",
         "mn5": "MN5/MN6 NMOS cascodes", "mn6": "MN5/MN6 NMOS cascodes"}


def header(corner_key):
    corner, temp, vdd = spice.CORNERS[corner_key]
    return vdd, f"""{spice.models(corner, mim=False, res=False)}
.temp {temp}
VDD vdd 0 {vdd}
VCM vcm 0 {vdd / 2}
{core()}
"""


def open_loop_deck(corner_key, tag):
    vdd, head = header(corner_key)
    lets = "\n".join(f"let {d}_{p} = @{d}[{p}]" for d in DEVICES for p in ("vds", "vdsat", "id", "gm"))
    prints = " ".join(f"{d}_{p}" for d in DEVICES for p in ("vds", "vdsat", "id", "gm"))
    return f"""* {tag}
{head}
VD vd 0 0 AC 1
Ep inp vcm vd 0 0.5
En inn vcm vd 0 -0.5
CLP outp 0 {CL_EFF}
CLN outn 0 {CL_EFF}
.control
op
{lets}
let cgs_in = @m1[cgg]
print {prints} cgs_in v(outp) v(outn) v(vbn) v(f1) v(b1) v(tail)
ac dec 40 10 2e9
wrdata {tag}_ac.txt v(outp)-v(outn)
dc VD -4m 4m 2u
wrdata {tag}_dc.txt v(outp)-v(outn)
option sparse
noise v(outp,outn) VD dec 20 10 {BW} 1
setplot noise2
print all
noise v(outp,outn) VD dec 20 1 1e8
setplot noise3
wrdata {tag}_noise.txt inoise_spectrum
.endc
.end
"""


def step_deck(corner_key, tag):
    vdd, head = header(corner_key)
    return f"""* {tag}
{head}
* step on the Cs bottom plates: +STEP/2 on the p side, -STEP/2 on the n side, scaled by Ci/Cs
VSP sp 0 PWL(0 {vdd / 2} 100n {vdd / 2} 101n {vdd / 2 + STEP / 2 * CI / CS})
VSN sn 0 PWL(0 {vdd / 2} 100n {vdd / 2} 101n {vdd / 2 - STEP / 2 * CI / CS})
CSP sp inp {CS}
CSN sn inn {CS}
CPP inp 0 {CP}
CPN inn 0 {CP}
CIP outn inp {CI}
CIN outp inn {CI}
RDP inp vcm 1e12
RDN inn vcm 1e12
CLP outp 0 {CL}
CLN outn 0 {CL}
.ic v(inp)={vdd / 2} v(inn)={vdd / 2} v(outp)={vdd / 2} v(outn)={vdd / 2}
.control
tran 0.05n 450n 0 0.1n
wrdata {tag}_tran.txt v(outp)-v(outn)
.endc
.end
"""


def crossing(f, y, level):
    """First f where y falls through level (log-interpolated)."""
    i = np.where((y[:-1] >= level) & (y[1:] < level))[0]
    if not len(i):
        return np.nan
    i = i[0]
    return float(np.exp(np.interp(level, [y[i + 1], y[i]], [np.log(f[i + 1]), np.log(f[i])])))


def run_corner(corner_key):
    tag = f"ota_{corner_key}"
    for suffix in ("_ac.txt", "_dc.txt", "_noise.txt", "_step_tran.txt"):
        (spice.OUT / f"{tag}{suffix}").unlink(missing_ok=True)
    log = spice.run(tag, open_loop_deck(corner_key, tag))
    vals = spice.meas(log)
    ac = spice.wrdata(f"{tag}_ac.txt")
    f, a_re, a_im = ac[:, 0], ac[:, 1], ac[:, 2]
    a = a_re + 1j * a_im
    mag = 20 * np.log10(np.abs(a))
    ph = np.unwrap(np.angle(a)) * 180 / np.pi
    loop = mag + 20 * np.log10(BETA)
    fc = crossing(f, loop, 0.0)
    pm = 180 + np.interp(np.log(fc), np.log(f), ph) if np.isfinite(fc) else np.nan
    gbw = crossing(f, mag, 0.0)

    dc = spice.wrdata(f"{tag}_dc.txt")
    vid, vod = dc[:, 0], dc[:, 1]
    g = np.gradient(vod, vid)
    gain_db = 20 * np.log10(np.maximum(np.abs(g), 1e-3))
    ok = gain_db >= 40
    lo = vod[ok].min() if ok.any() else np.nan
    hi = vod[ok].max() if ok.any() else np.nan
    g_at = [float(np.interp(v, vod, gain_db)) for v in (-VOD_MAX, 0.0, VOD_MAX)]

    nz = spice.wrdata(f"{tag}_noise.txt")
    fn, sn = nz[:, 0], nz[:, 1]                          # V/sqrt(Hz), input-referred
    band = (fn >= 10) & (fn <= BW)
    vn_band = np.sqrt(np.trapezoid(sn[band] ** 2, fn[band]))
    white = np.median(sn[(fn > 1e6) & (fn < 3e6)])
    f_corner = crossing(fn, sn, np.sqrt(2) * white)

    log2 = spice.run(tag + "_step", step_deck(corner_key, tag + "_step"))
    tr = spice.wrdata(f"{tag}_step_tran.txt")
    t, y = tr[:, 0], tr[:, 1]
    y0 = np.interp(99e-9, t, y)
    yf = np.mean(y[t > 350e-9])            # final value: mean of the last 100 ns
    after = t > 103e-9                     # skip the instantaneous Cs-Ci feedthrough during the input edge
    sr = np.max(np.abs(np.gradient(y, t))[after]) / 1e6
    err = np.abs(y - yf)
    outside = np.where((t > 101e-9) & (err > 1e-3 * abs(yf - y0)))[0]
    t_settle = (t[outside[-1]] - 101e-9) * 1e9 if len(outside) else 0.0

    sat = {d: abs(vals.get(f"{d}_vds", np.nan)) - abs(vals.get(f"{d}_vdsat", np.nan)) for d in DEVICES}
    # in-band input-referred noise per device (both devices of a pair), from the noise2 summary
    contrib = {}
    for m in re.finditer(r"^inoise_total\.(\w+)\.(1overf|id)\s*=\s*(\S+)", log, re.M):
        key = (GROUP.get(m.group(1), m.group(1)), m.group(2))
        contrib[key] = contrib.get(key, 0.0) + float(m.group(3)) ** 2
    return dict(corner=corner_key, adc=mag[0], gbw=gbw, fc=fc, pm=pm, lo=lo, hi=hi, g_at=g_at,
                vn=vn_band, white=white, fcorner=f_corner, sr=sr, ts=t_settle, step=yf - y0,
                sat=sat, cgs=vals.get("cgs_in", np.nan), vals=vals, contrib=contrib,
                ac=(f, mag, ph), dc=(vod, gain_db), noise=(fn, sn), tran=(t, y), log=log + log2)


def main():
    keys = list(spice.CORNERS)
    with ThreadPoolExecutor(max_workers=5) as pool:
        res = list(pool.map(run_corner, keys))

    out = ["Fully differential folded-cascode OTA, first pass (ideal bias currents, ideal CMFB)",
           f"sizes (W/finger um, L um, fingers): {S}",
           f"I_tail {I_TAIL * 1e6:.0f} uA, I_fold {I_FOLD * 1e6:.0f} uA per side; "
           f"core current {(I_TAIL + 2 * I_FOLD) * 1e6:.0f} uA; open-loop load {CL_EFF * 1e12:.2f} pF per side, beta {BETA}",
           "",
           f"{'corner':12s} {'Adc':>6s} {'GBW':>6s} {'fc*':>6s} {'PM':>5s} {'gain>=40dB over Vod':>20s} "
           f"{'A@-1.6/0/+1.6 V':>17s} {'vn band':>8s} {'1/f fc':>7s} {'SR':>6s} {'t_0.1%':>7s} {'min sat':>8s}",
           f"{'':12s} {'dB':>6s} {'MHz':>6s} {'MHz':>6s} {'deg':>5s} {'V diff':>20s} {'dB':>17s} "
           f"{'uVrms':>8s} {'kHz':>7s} {'V/us':>6s} {'ns':>7s} {'mV':>8s}"]
    for r in res:
        worst = min(r["sat"], key=r["sat"].get)
        out.append(f"{r['corner']:12s} {r['adc']:6.1f} {r['gbw'] / 1e6:6.1f} {r['fc'] / 1e6:6.1f} {r['pm']:5.1f} "
                   f"{r['lo']:+9.2f} .. {r['hi']:+5.2f}   "
                   f"{r['g_at'][0]:5.1f}/{r['g_at'][1]:4.1f}/{r['g_at'][2]:4.1f} "
                   f"{r['vn'] * 1e6:8.2f} {r['fcorner'] / 1e3:7.1f} {r['sr']:6.1f} {r['ts']:7.1f} "
                   f"{r['sat'][worst] * 1e3:5.0f} {worst}")
    out += ["",
            "* fc = loop crossover with beta = 0.59 (PM is measured there). vn band = input-referred noise",
            "  integrated over 10 Hz - 7.8 kHz; 1/f fc = where the noise density is sqrt(2) x the white floor.",
            "  SR and t_0.1% come from the closed-loop step (0.75 V diff output, Cs 0.5 / Ci 1 / Cp 0.1 / CL 0.3 pF).",
            "  min sat = smallest |Vds| - |Vdsat| over the signal-path devices at the operating point.",
            "",
            "operating point, tt (Vds, Vdsat, Id, gm):"]
    v = res[0]["vals"]
    for d in DEVICES:
        out.append(f"  {d:4s} Vds {v.get(d + '_vds', np.nan):+6.3f}  Vdsat {v.get(d + '_vdsat', np.nan):+6.3f}  "
                   f"Id {v.get(d + '_id', np.nan) * 1e6:+7.2f} uA  gm {v.get(d + '_gm', np.nan) * 1e6:7.1f} uS  "
                   f"gm/Id {v.get(d + '_gm', np.nan) / max(abs(v.get(d + '_id', np.nan)), 1e-12):5.1f}")
    out.append(f"  input-device Cgg (M1) {res[0]['cgs'] * 1e15:.0f} fF")
    out.append("\nin-band (10 Hz - 7.8 kHz) input-referred noise by device pair, tt (uV rms; 1/f and thermal):")
    c = res[0]["contrib"]
    for n in sorted({k[0] for k in c}, key=lambda n: -c.get((n, "1overf"), 0) - c.get((n, "id"), 0)):
        out.append(f"  {n:24s} 1/f {np.sqrt(c.get((n, '1overf'), 0)) * 1e6:5.2f}   thermal {np.sqrt(c.get((n, 'id'), 0)) * 1e6:5.2f}")
    txt = "\n".join(out)
    print(txt)
    (spice.RESULTS / "ota_fc.txt").write_text(txt + "\n")

    fig, ax = plt.subplots(2, 2, figsize=(12, 8))
    for r in res:
        f, mag, ph = r["ac"]
        ax[0, 0].semilogx(f, mag, label=r["corner"])
        ax[0, 1].semilogx(f, ph)
        vod, gdb = r["dc"]
        ax[1, 0].plot(vod, gdb, label=r["corner"])
        t, y = r["tran"]
        ax[1, 1].plot(t * 1e9, y, label=r["corner"])
    ax[0, 0].set(xlabel="Hz", ylabel="open-loop |A| (dB)", title=f"Open-loop gain, {CL_EFF * 1e12:.1f} pF per side")
    ax[0, 1].set(xlabel="Hz", ylabel="phase (deg)", title="Phase", ylim=(-270, 10))
    ax[1, 0].axvspan(-VOD_MAX, VOD_MAX, color="g", alpha=0.08, label="first-integrator swing")
    ax[1, 0].axhline(40, color="k", ls=":", lw=0.8)
    ax[1, 0].set(xlabel="Vod (V diff)", ylabel="incremental gain (dB)", title="DC gain vs output swing", ylim=(0, 100))
    ax[1, 1].axvline(191, color="k", ls=":", lw=0.8, label="end of T/2 at fs = 5 MHz")
    ax[1, 1].set(xlabel="ns", ylabel="Vod (V)", title="Closed-loop step (largest integrator step)", xlim=(90, 300))
    for a in ax.flat:
        a.grid(alpha=0.3, which="both")
    ax[0, 0].legend(fontsize=7)
    ax[1, 1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(spice.RESULTS / "ota_fc.png", dpi=130)


if __name__ == "__main__":
    main()
