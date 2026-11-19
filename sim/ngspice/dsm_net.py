"""Netlist builders for the transistor-level modulator (PLAN.md §2-3).

Blocks:
  bias      Beta multiplier (07_bias.py, 10 uA) with a startup circuit. Mirrored into diode replicas
            that make every op-amp bias voltage: vbt (tail), vbp (top sources), vcp/vcn
            (wide-swing cascodes, 1/16 width) and vbn0 (the CMFB reference for the bottom sources).
  ota1/2    Fully differential folded cascode (08_ota_fc.py sizes). OTA2 is OTA1 at 1/4 width.
            Both run at the same current density, so they share every bias voltage.
  integ     SC integrator with bottom-plate sampling, a separate DAC cap (Cdac = Cs/2 on a 2 V
            reference spread; see model/ref_loading.py), a reset switch, and a switched-cap CMFB
            (Cc from each output to the bottom-source gates, refreshed by Cs_cm between VCM and vbn0).
  comp      StrongARM latch, matched inverters, NOR SR latch, 3.3 V devices.
  dac logic AND(phi2d, Q) and AND(phi2d, Qb) from NAND + inverter, 3.3 V devices.
  ladder    VREFP / VCM / VREFN taps from VDD (ideal resistors) with ideal decaps for now.
  clkgen    Standard-cell non-overlapping generator (cross-coupled NOR2 + dlyd_1 chains), giving
            phi1, phi1d, phi2, phi2d and their complements (11_clockgen.py). modulator() can also
            use ideal PULSE phases (real_clocks=False), which is faster for debugging.
            Bottom-plate sampling: phi1 (summing-node side) falls before phi1d (input side).
  The integrator outputs are wired to the OTA outputs swapped (see integrator()), which is what
  makes the loop polarity come out right.

Sign conventions: x1 = outp1 - outn1 grows with (u - v), so integrator 1 implements
x1[n+1] = x1[n] + (Cs1 u - Cdac1 v (VREFP - VREFN)) / Ci1 = x1 + 0.5 (u - v) with FS = 1 V diff.
"""
import spice

OTA1 = dict(inp=(10.0, 2.0, 6), tail=(5.5, 1.0, 2), ptop=(10.0, 4.0, 7),
            pcas=(8.5, 0.5, 2), ncas=(5.0, 0.5, 1), nbot=(10.0, 8.0, 2))
OTA2 = dict(inp=(7.5, 2.0, 2), tail=(2.75, 1.0, 1), ptop=(8.75, 4.0, 2),
            pcas=(4.25, 0.5, 1), ncas=(1.25, 0.5, 1), nbot=(5.0, 8.0, 1))

T_NO = 5e-9          # non-overlap between phases
T_BP = 4e-9          # bottom-plate advance: phi1 falls this long before phi1d
T_EDGE = 1e-9

CAPS = dict(cs1=0.5e-12, ci1=1.0e-12, cs2=0.1e-12, ci2=0.2e-12)
SPREAD = 2.0         # VREFP - VREFN (V); Cdac = Cs * 1 V / SPREAD
LADDER_I = 30e-6
DECAP = 30e-12


def mos(name, d, g, s, kind, wlm, w_scale=1.0):
    w, l, m = wlm
    model, body = ("nfet_03v3", "vss") if kind == "n" else ("pfet_03v3", "vdd")
    return f"{name} {d} {g} {s} {body} {model} W={w * w_scale:.4f}u L={l}u m={m}"


def subckts():
    o1, o2 = OTA1, OTA2
    k = 16.0
    return f"""
.subckt bias vdd vss vbt vbp vcp vcn vbn0
* beta multiplier, 10 uA (07_bias.py)
MB1 n1 n1 vss vss nfet_03v3 W=10u L=2u
MB2 n2 n1 s2 vss nfet_03v3 W=10u L=2u m=4
XRB s2 vss vss ppolyf_u_1k r_width=2e-6 r_length=15.8e-6
MB3 n2 n2 vdd vdd pfet_03v3 W=20u L=2u
MB4 n1 n2 vdd vdd pfet_03v3 W=20u L=2u
* startup: st is high only while the multiplier is off; MS3 then pulls n2 down and n1 up
MS1 st vss vdd vdd pfet_03v3 W=0.5u L=20u
MS2 st n1 vss vss nfet_03v3 W=2u L=1u
MS3 n2 st n1 vss nfet_03v3 W=1u L=1u
* PMOS mirror outputs (10 uA per W=20/L=2) into NMOS diode replicas at OTA1 current density
MPT vbt n2 vdd vdd pfet_03v3 W=20u L=2u
{mos("MRT", "vbt", "vbt", "vss", "n", (o1['tail'][0] * o1['tail'][2] / 4, o1['tail'][1], 1))}
MPN vbn0 n2 vdd vdd pfet_03v3 W=20u L=2u
{mos("MRN", "vbn0", "vbn0", "vss", "n", (o1['nbot'][0], o1['nbot'][1], 1))}
MPC vcn n2 vdd vdd pfet_03v3 W=20u L=2u m=2
{mos("MRNC", "vcn", "vcn", "vss", "n", o1['ncas'], 1 / k)}
* NMOS mirror outputs (10 uA per W=10/L=2) from PMOS diode replicas
MNP vbp n1 vss vss nfet_03v3 W=10u L=2u
{mos("MRP", "vbp", "vbp", "vdd", "p", (o1['ptop'][0], o1['ptop'][1], 2), 0.875)}
MNC vcp n1 vss vss nfet_03v3 W=10u L=2u m=2
{mos("MRPC", "vcp", "vcp", "vdd", "p", o1['pcas'], 1 / k)}
.ends bias
""" + "".join(ota_subckt(n, s) for n, s in (("ota1", o1), ("ota2", o2))) + """
.subckt tg a b c cb vdd vss wn=1 wp=2
MN a c b vss nfet_03v3 W={wn*1e-6} L=0.28u
MP a cb b vdd pfet_03v3 W={wp*1e-6} L=0.28u
.ends tg

.subckt inv a y vdd vss
MN y a vss vss nfet_03v3 W=1u L=0.28u
MP y a vdd vdd pfet_03v3 W=2u L=0.28u
.ends inv

.subckt invs a y vdd vss
MN y a vss vss nfet_03v3 W=0.5u L=0.28u
MP y a vdd vdd pfet_03v3 W=1u L=0.28u
.ends invs

.subckt nor2 a b y vdd vss
MN1 y a vss vss nfet_03v3 W=1u L=0.28u
MN2 y b vss vss nfet_03v3 W=1u L=0.28u
MP1 m a vdd vdd pfet_03v3 W=4u L=0.28u
MP2 y b m vdd pfet_03v3 W=4u L=0.28u
.ends nor2

.subckt nand2 a b y vdd vss
MN1 y a m vss nfet_03v3 W=2u L=0.28u
MN2 m b vss vss nfet_03v3 W=2u L=0.28u
MP1 y a vdd vdd pfet_03v3 W=2u L=0.28u
MP2 y b vdd vdd pfet_03v3 W=2u L=0.28u
.ends nand2

.subckt comp inp inn clk q qb vdd vss
* StrongARM: clk high evaluates, clk low resets outp/outn (and a/b) to vdd.
* inp > inn pulls a, then outn, down first, so outp ends high.
MT t clk vss vss nfet_03v3 W=4u L=0.28u
M1 a inp t vss nfet_03v3 W=4u L=0.5u
M2 b inn t vss nfet_03v3 W=4u L=0.5u
M3 outn outp a vss nfet_03v3 W=2u L=0.28u
M4 outp outn b vss nfet_03v3 W=2u L=0.28u
M5 outn outp vdd vdd pfet_03v3 W=2u L=0.28u
M6 outp outn vdd vdd pfet_03v3 W=2u L=0.28u
M7 outn clk vdd vdd pfet_03v3 W=1u L=0.28u
M8 outp clk vdd vdd pfet_03v3 W=1u L=0.28u
M9 a clk vdd vdd pfet_03v3 W=1u L=0.28u
M10 b clk vdd vdd pfet_03v3 W=1u L=0.28u
* Matched small inverters isolate outp/outn from the SR latch. Driving a NAND latch directly
* loaded outp and outn unequally depending on its state, which gave 20-50 mV of hysteresis.
* NOR SR latch: outn low -> sn high -> q = 1; outp low -> q = 0; both reset high -> hold.
XB1 outp sp vdd vss invs
XB2 outn sn vdd vss invs
XN1 sp qb q vdd vss nor2
XN2 sn q qb vdd vss nor2
.ends comp
"""


def ota_subckt(name, s):
    return f"""
.subckt {name} inp inn outp outn vbn vbt vbp vcp vcn vdd vss
{mos("MT", "tail", "vbt", "vss", "n", s['tail'])}
{mos("M1", "f1", "inp", "tail", "n", s['inp'])}
{mos("M2", "f2", "inn", "tail", "n", s['inp'])}
{mos("MP3", "f1", "vbp", "vdd", "p", s['ptop'])}
{mos("MP4", "f2", "vbp", "vdd", "p", s['ptop'])}
{mos("MP5", "outn", "vcp", "f1", "p", s['pcas'])}
{mos("MP6", "outp", "vcp", "f2", "p", s['pcas'])}
{mos("MN5", "outn", "vcn", "b1", "n", s['ncas'])}
{mos("MN6", "outp", "vcn", "b2", "n", s['ncas'])}
{mos("MN3", "b1", "vbn", "vss", "n", s['nbot'])}
{mos("MN4", "b2", "vbn", "vss", "n", s['nbot'])}
.ends {name}
"""


def sw(name, a, b, ph, wn=2.0, wp=4.0):
    """Transmission gate closed while clock `ph` is high (needs ph and ph_b nodes)."""
    return f"X{name} {a} {b} {ph} {ph}_b vdd vss tg wn={wn} wp={wp}"


def integrator(i, inp, inn, outp, outn, cs, ci, cc, ccs, ota, cm_phase):
    """SC integrator i: inputs (inp, inn) sampled on phi1, transferred with the DAC on phi2.
    cm_phase is the phase in which the CMFB caps Cs_cm sit across Cc (refreshed in the other)."""
    cdac = cs * 1.0 / SPREAD
    ref = "ph1" if cm_phase == "ph2" else "ph2"
    p = f"i{i}"
    return f"""
* ---------------- integrator {i}
{sw(p + "S1P", inp, p + "tp", "ph1d")}
{sw(p + "S1N", inn, p + "tn", "ph1d")}
{sw(p + "S2P", p + "tp", "vcm", "ph2d")}
{sw(p + "S2N", p + "tn", "vcm", "ph2d")}
C{p}SP {p}tp {p}bp {cs}
C{p}SN {p}tn {p}bn {cs}
{sw(p + "S3P", p + "dp", "vcm", "ph1d", 1, 2)}
{sw(p + "S3N", p + "dn", "vcm", "ph1d", 1, 2)}
{sw(p + "S4P", p + "dp", "vrefp", "dacp", 1, 2)}
{sw(p + "S5P", p + "dp", "vrefn", "dacn", 1, 2)}
{sw(p + "S4N", p + "dn", "vrefn", "dacp", 1, 2)}
{sw(p + "S5N", p + "dn", "vrefp", "dacn", 1, 2)}
C{p}DP {p}dp {p}bp {cdac}
C{p}DN {p}dn {p}bn {cdac}
{sw(p + "S6P", p + "bp", "vcm", "ph1")}
{sw(p + "S6N", p + "bn", "vcm", "ph1")}
{sw(p + "S7P", p + "bp", p + "sp", "ph2")}
{sw(p + "S7N", p + "bn", p + "sn", "ph2")}
* The OTA's outputs are swapped onto (outn, outp): sp -> net outp is then the inverting path that
* Ci closes, and charge Q pushed into sp raises outp by Q/Ci, so x = outp - outn grows with Cs*in - Cdac*v*Vref.
C{p}IP {p}sp {outp} {ci}
C{p}IN {p}sn {outn} {ci}
{sw(p + "RP", p + "sp", outp, "rst", 1, 2)}
{sw(p + "RN", p + "sn", outn, "rst", 1, 2)}
X{p}OTA {p}sp {p}sn {outn} {outp} {p}vbn vbt vbp vcp vcn vdd vss {ota}
* switched-cap CMFB: Cc holds VCM - vbn0, so vbn = vbn0 when the output CM is VCM
C{p}CP {outp} {p}vbn {cc}
C{p}CN {outn} {p}vbn {cc}
C{p}MP {p}mpt {p}mpb {ccs}
C{p}MN {p}mnt {p}mnb {ccs}
{sw(p + "M1P", p + "mpt", outp, cm_phase, 0.5, 1)}
{sw(p + "M2P", p + "mpb", p + "vbn", cm_phase, 0.5, 1)}
{sw(p + "M3P", p + "mpt", "vcm", ref, 0.5, 1)}
{sw(p + "M4P", p + "mpb", "vbn0", ref, 0.5, 1)}
{sw(p + "M1N", p + "mnt", outn, cm_phase, 0.5, 1)}
{sw(p + "M2N", p + "mnb", p + "vbn", cm_phase, 0.5, 1)}
{sw(p + "M3N", p + "mnt", "vcm", ref, 0.5, 1)}
{sw(p + "M4N", p + "mnb", "vbn0", ref, 0.5, 1)}
* DC path for the op point only (13 ms time constant)
R{p}VBN {p}vbn vbn0 10G
"""


def clkgen_inst(vdd, fs):
    """`clk` from an ideal 50 % square wave into the standard-cell generator (phi1 while clk is low)."""
    T = 1 / fs
    return (clkgen_subckt() +
            f"VCLK clk 0 PULSE({vdd} 0 0 {T_EDGE} {T_EDGE} {T / 2 - T_EDGE} {T})\n"
            "XCG clk ph1 ph1_b ph1d ph1d_b ph2 ph2_b ph2d ph2d_b vdd vss clkgen")


def clocks(vdd, fs):
    T = 1 / fs
    on = T / 2 - T_NO - T_EDGE
    lines = []
    for name, delay, width in (("ph1", 0, on - T_BP), ("ph1d", 0, on),
                               ("ph2", T / 2, on - T_BP), ("ph2d", T / 2, on)):
        d = delay + T_EDGE
        lines.append(f"V{name} {name} 0 PULSE(0 {vdd} {d} {T_EDGE} {T_EDGE} {width} {T})")
        lines.append(f"V{name}_b {name}_b 0 PULSE({vdd} 0 {d} {T_EDGE} {T_EDGE} {width} {T})")
    return "\n".join(lines)


def modulator(corner_key, ncycles, amp, fbin, nfft, fs=2e6, reset_cycles=2, save_all=False, probes=(),
              tag=None, tstep=10e-9, real_clocks=False):
    corner, temp, vdd = spice.CORNERS[corner_key]
    T = 1 / fs
    vcm = vdd / 2
    taps = (vcm + SPREAD / 2, vcm, vcm - SPREAD / 2)
    seg = (vdd - taps[0], taps[0] - taps[1], taps[1] - taps[2], taps[2])
    r = [s / LADDER_I for s in seg]
    f_in = fbin / (nfft * T)
    t_rst = reset_cycles * T + 0.75 * T          # release in the middle of a phi2
    c = CAPS
    tstop = (ncycles + reset_cycles + 1) * T
    saves = "" if save_all else (
        ".save v(q) v(outp1) v(outn1) v(outp2) v(outn2) v(vrefp) v(vrefn) v(vcm) v(i1vbn) v(i2vbn) "
        "v(vinp) v(vinn) vdd#branch " + " ".join(probes))
    return f"""* delta-sigma modulator {corner_key} amp={amp} fbin={fbin}/{nfft}
{spice.models(corner, mim=False, res=True, stdcells=real_clocks)}
.temp {temp}
.options method=gear reltol=1e-4 interp
{subckts()}
VDD vdd 0 {vdd}
VSS vss 0 0
* reference ladder (ideal resistors and decaps for now)
RL1 vdd vrefp {r[0]:.1f}
RL2 vrefp vcm {r[1]:.1f}
RL3 vcm vrefn {r[2]:.1f}
RL4 vrefn vss {r[3]:.1f}
CDP vrefp vss {DECAP}
CDM vcm vss {DECAP}
CDN vrefn vss {DECAP}
XBIAS vdd vss vbt vbp vcp vcn vbn0 bias
{clkgen_inst(vdd, fs) if real_clocks else clocks(vdd, fs)}
VRST rst 0 PWL(0 {vdd} {t_rst} {vdd} {t_rst + T_EDGE} 0)
VRSTB rst_b 0 PWL(0 0 {t_rst} 0 {t_rst + T_EDGE} {vdd})
* differential input around the ideal VCM (an external source)
VINP vinp 0 SIN({vcm} {amp / 2} {f_in} {t_rst})
VINN vinn 0 SIN({vcm} {-amp / 2} {f_in} {t_rst})
{integrator(1, "vinp", "vinn", "outp1", "outn1", c['cs1'], c['ci1'], 0.2e-12, 0.1e-12, "ota1", "ph1")}
{integrator(2, "outp1", "outn1", "outp2", "outn2", c['cs2'], c['ci2'], 0.05e-12, 0.025e-12, "ota2", "ph2")}
* comparator evaluates on phi1 (x2 is final at the end of phi2 and held through phi1)
XCMP outp2 outn2 ph1 q qb vdd vss comp
* DAC control: dacp = phi2d AND q, dacn = phi2d AND qb (with complements for the TGs)
XA1 ph2d q dacp_b vdd vss nand2
XA2 dacp_b dacp vdd vss inv
XA3 ph2d qb dacn_b vdd vss nand2
XA4 dacn_b dacn vdd vss inv
.ic v(q)={vdd} v(qb)=0
{saves}
.control
tran {tstep} {tstop} 0 2n
wrdata {tag or 'dsm_' + corner_key}.txt v(q) v(outp1)-v(outn1) v(outp2)-v(outn2) (v(outp1)+v(outn1))/2 (v(outp2)+v(outn2))/2 v(vrefp)-v(vrefn) v(i1vbn) v(i2vbn) i(VDD) {' '.join(probes)}
.endc
.end
"""

SC = "gf180mcu_fd_sc_mcu7t5v0__"
CLK_DLY = (("dlyd_1",) * 3, ("dlyd_1",) * 2)   # (chain before the early tap: non-overlap,
                                               #  chain early -> late tap: bottom-plate advance)


def clkgen_subckt(dly=None):
    """Non-overlapping two-phase generator from standard cells (5 V cells run at 3.3 V).
    phi1 is high while clk is low. n1 = NOR(clk, phi2d): phi1 can only rise after phi2d has fallen
    (the non-overlap is one NOR + one delay cell + one buffer). Each phase has an early tap
    (phi1, for the summing-node switches) and a later tap one delay cell on (phi1d, for the
    input-side switches), so bottom-plate sampling opens the summing-node side first. Every
    tap drives a buf_4 / inv_4 pair, so phi and phi_b come off the same node."""
    c = lambda inst, cell, pins: f"X{inst} {pins} vdd vdd vss vss {SC}{cell}"
    d0, d1 = dly or CLK_DLY
    lines = [".subckt clkgen clk ph1 ph1_b ph1d ph1d_b ph2 ph2_b ph2d ph2d_b vdd vss",
             c("I0", "inv_2", "clk clkb"),
             c("N1", "nor2_1", "clk ph2d n1"),
             c("N2", "nor2_1", "clkb ph1d n2")]
    def chain(tagc, cells, a, b):
        nodes = [a] + [f"{tagc}{j}" for j in range(len(cells) - 1)] + [b]
        return [c(f"{tagc}{j}", cell, f"{nodes[j]} {nodes[j + 1]}") for j, cell in enumerate(cells)]
    for k, n in (("1", "n1"), ("2", "n2")):
        lines += chain(f"D{k}a", d0, n, f"a{k}") + chain(f"D{k}b", d1, f"a{k}", f"b{k}")
        lines += [c(f"B{k}a", "buf_4", f"a{k} ph{k}"), c(f"V{k}a", "inv_4", f"a{k} ph{k}_b"),
                  c(f"B{k}b", "buf_4", f"b{k} ph{k}d"), c(f"V{k}b", "inv_4", f"b{k} ph{k}d_b")]
    lines.append(".ends clkgen")
    return "\n".join(lines) + "\n"
