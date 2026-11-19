"""StrongARM comparator + inverters + NOR SR latch (dsm_net.py `comp`), checked at 5 corners (PLAN.md §3.5, §6).

The comparator evaluates while phi1 is high; its result has to be stable before phi2d
switches the DAC (about T/2 later). Each case drives the inputs from VCM +- dv/2 through
R_SRC with C_SRC to ground, a rough model of OTA2's output during phi1, so the
differential kickback glitch can be read too.
  t_dec    clk rise (50 %) to q settling past 50 %, for dv = +-1 mV and +-30 uV, starting
           from the opposite decision (so any hysteresis would show as a wrong decision)
  kick     peak differential input disturbance during evaluation, dv = 1 mV
Offset is not simulated: the devices are instantiated as M (no mismatch), and the loop
noise-shapes offset and hysteresis anyway (PLAN.md §3.5).
Output: results/comparator.txt
"""
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import spice
import dsm_net

R_SRC = 5e3
C_SRC = 0.2e-12
T = 500e-9
DVS = (1e-3, -1e-3, 30e-6, -30e-6)


def run(corner, dv):
    model, temp, vdd = spice.CORNERS[corner]
    tag = f"cmp_{corner}_{dv * 1e6:+.0f}u"
    vcm = vdd / 2
    deck = f"""* comparator {tag}
{spice.models(model, mim=False, res=False)}
.temp {temp}
{dsm_net.subckts()}
VDD vdd 0 {vdd}
VSS vss 0 0
VCK ck 0 PULSE(0 {vdd} {T / 2} 1n 1n {T / 2 - 1e-9} {T})
VP sp 0 {vcm + dv / 2}
VN sn 0 {vcm - dv / 2}
RP sp inp {R_SRC}
RN sn inn {R_SRC}
CP inp 0 {C_SRC}
CN inn 0 {C_SRC}
XC inp inn ck q qb vdd vss comp
.ic v(q)={0 if dv > 0 else vdd} v(qb)={vdd if dv > 0 else 0}
.control
tran 0.02n {1.5 * T} 0 0.05n
wrdata {tag}.txt v(ck) v(q) v(inp)-v(inn) v(xc.outp) v(xc.outn) v(qb)
.endc
.end
"""
    (spice.OUT / f"{tag}.txt").unlink(missing_ok=True)
    spice.run(tag, deck)
    d = spice.wrdata(f"{tag}.txt")
    t, ck, q, vin = d[:, 0], d[:, 1], d[:, 3], d[:, 5]
    t_ck = t[np.argmax((ck > vdd / 2) & (t > T / 4))]
    want_high = dv > 0
    ok = (q > vdd / 2) if want_high else (q < vdd / 2)
    after = t > t_ck
    bad = np.where(after & ~ok)[0]
    settled = t[bad[-1] + 1] if len(bad) and bad[-1] + 1 < len(t) else (t_ck if not len(bad) else np.nan)
    t_dec = settled - t_ck
    win = (t > t_ck - 2e-9) & (t < t_ck + 50e-9)
    kick = np.max(np.abs(vin[win] - dv))
    return dict(corner=corner, dv=dv, t_dec=t_dec, kick=kick, correct=bool(ok[-1]))


def main():
    jobs = [(c, dv) for c in spice.CORNERS for dv in DVS]
    with ThreadPoolExecutor(max_workers=5) as pool:
        res = list(pool.map(lambda a: run(*a), jobs))
    out = ["StrongARM comparator + matched inverters + NOR SR latch (dsm_net.py comp), clk 2 MHz",
           "(the first version drove a NAND SR latch directly and had 20-50 mV of hysteresis at tt)",
           f"inputs from VCM +- dv/2 through {R_SRC / 1e3:.0f} kohm with {C_SRC * 1e12:.1f} pF to ground", "",
           f"{'corner':12s}" + "".join(f"{'t_dec ' + format(dv * 1e6, '+.0f') + 'uV':>15s}" for dv in DVS)
           + f"{'kick (1 mV)':>13s}",
           f"{'':12s}" + "".join(f"{'ns':>15s}" for _ in DVS) + f"{'mV diff':>13s}"]
    for c in spice.CORNERS:
        rs = [r for r in res if r["corner"] == c]
        out.append(f"{c:12s}" + "".join(f"{r['t_dec'] * 1e9:12.2f} {'ok' if r['correct'] else 'X '}" for r in rs)
                   + f"{rs[0]['kick'] * 1e3:13.1f}")
    out += ["", "  t_dec = clk rise to q settled on the correct side; ok = final decision correct.",
            "  The DAC switches about T/2 - t_no later (245 ns at 2 MHz, 95 ns at 5 MHz)."]
    txt = "\n".join(out)
    print(txt)
    (spice.RESULTS / "comparator.txt").write_text(txt + "\n")


if __name__ == "__main__":
    main()
