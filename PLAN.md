# GF180 delta-sigma ADC: tapeout plan

Tiny Tapeout **TTGF26c**, closes **Mon Dec 7 2026, 20:00 UTC (12:00 PST)**. Solo. Presentation required (pre-silicon: chips are due back around May–June 2027).

**Switched from the PLL on Nov 11.** The integer-N PLL plan, its sims and the dummy tile that passed precheck are kept at git tag [`pll-plan`](https://github.com/robertliu4/501-pll/tree/pll-plan). The tile flow, the precheck lessons, the device data and the bias generator carry over. Anything marked **[A#]** is an assumption I made so I could keep going. They're collected in [§11](#11-assumptions-to-review) for you to check.

---

## 0. Where things stand (Wed Nov 11)

**Done**

- **The architecture is chosen:** a 2nd-order, 1-bit, fully differential switched-cap delta-sigma modulator, with the decimation filter run off chip in Python.
- **Behavioural model** (`model/dsm_model.py`, `model/results/dsm_summary.txt`). It sets every number in §2:
  - SQNR vs amplitude and OSR.
  - First-integrator swing.
  - First op-amp DC gain, GBW and slew rate.
  - kT/C noise.
  - Capacitor-ratio sensitivity.
- **First-integrator op-amp, first pass** (`sim/ngspice/08_ota_fc.py`, `sim/results/ota_fc.txt`). A fully differential folded cascode that **meets every spec at all 5 corners**, with ideal bias currents and an ideal CMFB:
  - 88 dB DC gain, and ≥ 66 dB over the full ±1.6 V swing.
  - 54–70 MHz GBW and 77° phase margin.
  - 53 V/µs slew rate.
  - 0.1 % settling in 42–49 ns.
  - 5.5–6.5 µV rms of in-band noise.
- **The Tiny Tapeout flow is proven.** On Oct 27 the dummy tile passed all 12 precheck checks, including GF180MCU DRC and antenna ([run 40534489155](https://github.com/robertliu4/501-pll/actions/runs/40534489155)). GitHub Pages hosts the 3D viewer at <https://robertliu4.github.io/501-pll/>.
  - The dummy is now renamed `tt_um_robertliu4_dsm`, with a Metal4 stub on `ua[2]` for `analog_pins: 3`.
  - Pushed on Nov 14: the precheck passes under the new name ([run 43665193187](https://github.com/robertliu4/501-pll/actions/runs/43665193187)), and the viewer shows the renamed tile.
  - **Pushing a tag also runs the workflow, and its viewer job deploys to Pages.** The job names no environment, so the `main`-only rule doesn't apply. Push tags only before or together with `main`, so that `main` deploys last.
- **Carried over from the PLL work:**
  - `sim/ngspice/spice.py` (models, corners, runner).
  - gm/ID tables (`01_devices.py`).
  - MOS-cap C–V data (`05_moscap.py`, now for decap only).
  - The beta-multiplier bias reference (`07_bias.py`).
  - The precheck rules in §7.

**Not done, and blocking layout:** Docker/OrbStack plus IIC-OSIC-TOOLS (xschem, Magic, KLayout, netgen) are still not installed (§12).

**Findings that shape this plan**

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| 1 | **MIM caps can't be used in a TT GF tile** (they need Via4/Metal5; the precheck forbids Metal5). MOS caps are too voltage-dependent for signal paths. The PDK has **no MOM cap model**. | TT precheck `tech_data.py`; `05_moscap.py`; PDK `libs.tech/ngspice` | Signal caps are hand-drawn metal-finger (MOM) caps on M1–M4, sized from extraction. Schematic sims use ideal caps. MOS caps are used only for decap. |
| 2 | **Capacitor ratios barely matter.** With a1 = 0.45 or 0.55 instead of 0.5, SQNR moves by less than 1 dB. a2 doesn't matter at all, because the 1-bit quantizer ignores scale. | `dsm_model.py` (§3.1) | Unit-cap MOM arrays need no trimming. Extraction only has to confirm that the ratio is within ±10 %. |
| 3 | **GF180 NMOS 1/f noise is about 3.6× PMOS** (noise power at equal area). With L = 1 µm devices the op-amp had **17 µV rms** of in-band noise, which is as large as the kT/C noise. Long devices (input pair W·L = 120 µm², sources L = 4–8 µm) bring it down to 6 µV. | `08_ota_fc.py` noise breakdown | Long-L current sources and a large input pair. If noise becomes the limit, a PMOS input pair is the fallback (§3.2). |
| 4 | **kT/C noise is closer than I said on Nov 10.** At the −6 dBFS operating point, with a 1.5× op-amp excess, Cs = 0.5 pF gives **85 dB**, not 90–93 dB (that figure was for a full-scale input). | `dsm_summary.txt` (5) | Still above the 75 dB target. Cs = 1 pF buys only +0.6 dB of total SNDR, so stay at 0.5 pF. |
| 5 | **An ideal CMFB with too much loop gain (30) made the common-mode loop burst** in the step test. At gain 3 it is clean. | `08_ota_fc.py` | The real switched-cap CMFB needs its own common-mode loop stability check (§6). |
| 6 | **The analog pins are now a hard requirement**, because the ADC input arrives on `ua[0]`/`ua[1]`. The TTGF0p3 factory test lists [board pins 16–21 for `ua[0..5]`](https://tinytapeout.com/chips/ttgf0p3/007), so at least one GF board routes them. | TT site | Ask on Discord for TTGF26c. Keep the **digital-only test modes** in §3.8 (inputs shorted to VCM, internal DC levels). |
| 7 | **Measured GF silicon has been 2–3× slower than simulation** (a standard-cell ring at TTGF0p2). | TT silicon feedback | The sample rate is the external `clk`, so slow silicon just runs slower. At fs = 2 MHz the op-amp settles in a fifth of the time it has. |
| 8 | The precheck runs **KLayout DRC only (no LVS)**, plus antenna and structural checks. | `tt-support-tools/precheck` | Run netgen LVS yourself, per block and at the top level. |

---

## 1. Hard constraints

| Item | Value | Source |
|---|---|---|
| Shuttle / deadline | TTGF26c (wafer.space Run #3), **2026-12-07 20:00 UTC** | TT API, verified Oct 26 |
| Template | `TinyTapeout/ttgf-analog-template` @ `ttgf26c`, gf180mcuD, merged into this repo | verified |
| Tile | **2×2 = 711.20 × 325.36 µm** (0.231 mm²) | `tt-support-tools/tech/gf180mcuD/def/analog`, verified |
| Supply | VDPWR = **3.3 V**. Optional VAPWR has an undocumented voltage; **we don't use it** [A1]. | template |
| Metal | M1–M4 only (**Metal5 forbidden**). Pins on M4. Power stripes are vertical M4, ≥ 0.8 µm wide, running within 10 µm of the top and bottom edges. | precheck, verified |
| Analog pins | **`ua[0..2]` used** (`analog_pins: 3`). GF pin R/C isn't published; SKY's is < 500 Ω and < 5 pF. The demo board puts a **10 kΩ pulldown** on analog pins (jumper). | [A2] |
| Digital I/O | `clk` ≤ 5 MHz in, `uo[0..1]` ≤ 5 MHz out. That's far below any I/O limit. | |
| Cost | €70 per tile → **2×2 = €280**; analog pins €0 at the moment | TT app config, Oct 26 |
| Precheck | KLayout `gf180mcu.drc` (all except density and antenna), a separate antenna check, the `PR_bndry` box must exactly match the template, pins must match the DEF, LEF power pins must be `USE POWER/GROUND`, Yosys syntax on `src/project.v`. **No LVS.** | verified |
| Precheck PDK | open_pdks **e8daeda** (2026-06-11), KLayout 0.30.8 (Nix, `tt-support-tools` main). The local install is 792ef67; run the final DRC against e8daeda. | verified |
| Files | `info.yaml`, `LICENSE`, `docs/info.md` (images < 512 kB each, < 1 MB total), `gds/<top>.gds`, `lef/<top>.lef`, `src/project.v`. Top module is **`tt_um_robertliu4_dsm`**. | |

---

## 2. Architecture (v1 spec, frozen unless a §11 assumption breaks)

```
 IN_SEL ui[1:0]                                                  rst_n: resets both integrators
       │
 ua[0] VINP ─┐  ┌──────────────────┐  x1  ┌──────────────────┐  x2  ┌────────────┐  v  ┌──────────┐
             ├─▶│ SC integrator 1  │─────▶│ SC integrator 2  │─────▶│ StrongARM  │────▶│ SR latch │──▶ uo[0] DOUT
 ua[1] VINN ─┘  │ Cs1 0.5p/Ci1 1p  │      │ Cs2 0.1p/Ci2 0.2p│      │ comparator │     └──────────┘
 (or VCM, or    │ OTA1: FD folded  │      │ OTA2: OTA1 at    │      └────────────┘          │
  ladder DC)    │ cascode, SC CMFB │      │ 1/4 current      │                              │
                └────────▲─────────┘      └────────▲─────────┘                              │
                         │   1-bit DAC: VREFP/VREFN onto Cs1 and Cs2, chosen by v            │
                         └─────────────────────────┴─────────────────────────────────────────┘
 clk ──▶ non-overlap clock generator (φ1, φ1d, φ2, φ2d; std cells) ──▶ switches, comparator, uo[1] CLK_OUT
 VDPWR ──▶ resistor ladder ──▶ VREFP 2.15 V · VCM 1.65 V · VREFN 1.15 V (MOS decap on each); VCM ──▶ ua[2]
 beta-multiplier bias (10 µA) ──▶ OTA1, OTA2, comparator preamp
```

Loop equations, in units of Vref (`model/dsm_model.py`):
- x1[n+1] = x1[n] + a1(u[n] − v[n])
- x2[n+1] = x2[n] + a2(x1[n] − v[n])
- v = sign(x2)

With a1 = 0.5, the noise transfer function is NTF = (1 − z⁻¹)² and the signal transfer function is STF = z⁻².

| Parameter | Value | Basis |
|---|---|---|
| Sample rate fs | **2 MHz** nominal from `clk`; works from 0.5 to 5 MHz | the op-amp settles in 49 ns of the 90 ns available at 5 MHz |
| OSR / bandwidth | **128** → 7.8 kHz at 2 MHz (19.5 kHz at 5 MHz) | |
| Full scale | ±Vref = **±1 V differential** (VREFP − VREFN = 1 V); SQNR peaks at −6 dBFS, and the loop overloads above about −2 dBFS | model §1 |
| SQNR (ideal) | **85.2 dB** peak (−6 dBFS) | model §1 |
| SNDR with kT/C (Cs1 = 0.5 pF) and the op-amp | **about 82 dB** in the model | model §5, §6 |
| Targets | ≥ 75 dB SNDR in the transistor-level sim at tt; ≥ 60 dB on silicon | |
| First integrator | Cs1 = 0.5 pF, Ci1 = 1 pF per side (a1 = 0.5). β = Ci/(Ci + Cs + Cp + Cgg) ≈ 0.53 | |
| First-integrator swing | \|x1\| ≤ 1.6 × Vref → **±1.6 V differential**, ±0.8 V per side around VCM | model §1 |
| OTA1 requirements | DC gain ≥ 40 dB over the swing (26 dB still gives 76 dB); GBW ≥ 6 MHz; SR ≥ 30 V/µs differential at fs = 5 MHz; in-band noise well below the 16 µV rms of kT/C | model §3–4 |
| OTA1 achieved (first pass, 5 corners) | 88 dB (≥ 66 dB at ±1.6 V), GBW 54–70 MHz, PM 77°, SR 53 V/µs, 0.1 % settling in 42–49 ns, 5.5–6.5 µV rms in band, 80 µA core current | `ota_fc.txt` |
| Second integrator | Cs2 = 0.1 pF, Ci2 = 0.2 pF. Its errors are shaped by the first integrator, so it can be small and slow. | |
| Comparator | StrongARM latch plus NAND SR latch. Offset and hysteresis are shaped by the loop, so tens of mV are fine. | |
| Clocking | Two non-overlapping phases plus early-off copies for bottom-plate sampling, from `clk` through standard cells. | |
| References | A ladder from VDPWR: VREFP 2.15, VCM 1.65, VREFN 1.15 V at 3.3 V (ratiometric), each node with tens of pF of MOS decap. The reference-loading question is open (§3.6). | |
| Bias | The beta multiplier from `07_bias.py` (10 µA, −12/+29 % over PVT), mirrored to OTA1's 40 µA tail. GBW and SR tolerate ±30 %. | |
| Power | About 0.4 mA from 3.3 V (estimate) | |
| Area | Active circuitry about 0.03 mm². The rest of the 0.231 mm² is decap and margin. | estimate |

---

## 3. Block-by-block decisions and trade-offs

### 3.1 Loop: 2nd order, 1 bit, Boser-Wooley, discrete time (decided Nov 10–11)
- **Why:**
  - It's the textbook first ΔΣ.
  - Gains are set by capacitor ratios and are insensitive to errors (±10 % costs < 1 dB).
  - A 1-bit DAC is inherently linear.
  - It's unconditionally stable at 2nd order.
  - The sample rate is just `clk`.
- **Rejected:**
  - **Continuous-time:** the loop gains are R·C, which spreads ±20–30 % in GF180 and would need trimming. It's also sensitive to clock jitter and loop delay.
  - **VCO-based (reusing the PLL ring):** 1st-order shaping, and the ring's nonlinearity limits it to about 35–45 dB.
  - **1st order:** 55 dB and idle tones.
  - **Multi-bit:** DAC mismatch needs dynamic element matching.
  - **3rd order and above:** stability needs careful coefficient design.
- **The numbers** (`dsm_summary.txt`):

  | OSR | 32 | 64 | 128 | 256 |
  |---|---|---|---|---|
  | SQNR at −6 dBFS | 55 dB | 70 dB | 85 dB | 100 dB |

  1st order at OSR 128 gives 55 dB.
- **Coefficients:**
  - a1 = 0.5 is what makes the NTF exactly (1 − z⁻¹)².
  - a1 = 0.4 lowers the x1 swing and is 0.6 dB better at −3 dBFS, but worse at −6 dBFS. **Keep 0.5** unless OTA1's swing gets tight.

### 3.2 OTA1: fully differential folded cascode, NMOS input (first pass done)
- **Topology:**
  - NMOS input pair (input CM = VCM = VDD/2).
  - PMOS top sources with PMOS cascodes.
  - NMOS cascodes on CMFB-controlled NMOS bottom sources.
  - Wide-swing cascode bias from diode replicas at 1/16 width.
- **Why:**
  - Output swing: the folded cascode keeps ≥ 66 dB over 0.7–2.3 V per side at ss/3.0 V.
  - Single stage, so no Miller compensation and fast settling.
  - Rejected: a telescopic cascode, which can't swing ±0.8 V per side at 3.0 V, and a two-stage Miller, which has more power and more poles to manage.
- **Sizes** (W per finger / L / fingers, µm):

  | Device | W / L / fingers | gm/ID | Note |
  |---|---|---|---|
  | Input pair | 10 / 2 / 6 | 15 | |
  | Tail | 5.5 / 1 / 2 | 8 | 40 µA |
  | PMOS top sources | 10 / 4 / 7 | 4.6 | 40 µA |
  | PMOS cascodes | 8.5 / 0.5 / 2 | | |
  | NMOS cascodes | 5 / 0.5 / 1 | | |
  | NMOS bottom sources | 10 / 8 / 2 | 5.4 | 20 µA |

  I_fold = I_tail/2 is the minimum for symmetric slewing. A larger I_fold does not raise the slew rate, which is I_tail/C_eff differentially.
- **Noise** (tt, 10 Hz–7.8 kHz, input-referred):

  | Source | 1/f | Thermal |
  |---|---|---|
  | Input pair | 5.3 µV | 0.8 µV |
  | Bottom sources | 1.9 µV | |
  | Top sources | 1.5 µV | |

  The 1/f corner is about 30 kHz. To halve the noise if needed:
  - Quadruple the input-pair area, at the cost of β (Cgg is already 0.27 pF).
  - Or switch to a PMOS input pair, about 2× lower 1/f, but the NMOS sources then carry the large current.
  - Chopping is a Tier 2 item and isn't needed at today's numbers.
- **Still ideal:**
  - **Bias currents:** next is the beta multiplier with mirrors.
  - **CMFB:** next is a switched-cap CMFB, two caps per side refreshed on φ1. Check common-mode loop stability, and check output CM over corners and the swing.
- **Watch:** the cascode-bias diodes (1/16 width) are the only thing setting the saturation margins (114–157 mV now). Re-check them with the real bias generator and at 85 °C/3.0 V.

### 3.3 OTA2
- The same topology at about 1/4 current (10 µA tail). Its load is about 0.3 pF.
- Its gain, noise and settling errors are divided by the first integrator's in-band gain, so a fast first pass is enough.
- Verify it only inside the full-loop transient.

### 3.4 Switches, sampling and clocks
- **Switches:** transmission gates on 3.3 V devices.
  - Ron·Cs ≈ 1 ns ≪ T/2 = 250 ns, so sampling settles completely, and Ron's signal dependence doesn't cause distortion. No bootstrapping needed.
- **Bottom-plate sampling:** the switch on the op-amp side opens first (φ1d is the delayed phase), so charge injection is signal-independent. Fully differential operation cancels the rest to first order.
- **Non-overlap generator:** the standard NAND/inverter-chain cross-coupled circuit from `clk`, giving about 5 ns of non-overlap with `dly` cells.
  - The standard cells are slow 5 V devices, which doesn't matter at ≤ 5 MHz.
  - Use `filltie` in every row (§7).
- **Comparator timing:** it fires at the end of the phase where x2 is stable. Its result drives the DAC switches in the next phase.

### 3.5 Comparator
- StrongARM latch (3.3 V devices) plus a NAND SR latch. DOUT is buffered by a standard-cell `buf` to `uo[0]`.
- Offset and hysteresis are shaped by the 2nd-order loop, so they don't need to be small. Check them with a quick Monte Carlo, not an optimization.
- Kickback onto x2 is also shaped, but give the input pair some isolation (keep the latch devices small).

### 3.6 DAC and references (open: decide in W1)
- **Default:** each Cs bottom plate is switched to VREFP or VREFN by v (shared input/DAC caps, classic Boser-Wooley).
  - The references come from a resistor ladder off VDPWR with MOS decap.
  - Ratiometric references are fine: the bitstream encodes Vin/Vref, and VCM noise is common mode.
- **The open problem:** with shared caps, the charge drawn from VREFP/VREFN each cycle depends on the input, so a reference with finite impedance droops in a signal-dependent way, which shows up as distortion.
  - **Add a reference RC with per-cycle charge kicks to `dsm_model.py`**, then size the ladder current and decap so the distortion is ≥ 85 dB down.
  - **Fallback:** a separate DAC cap that is reset each cycle. Each cycle then draws the same charge, so the error is linear (a gain error). It costs about 3 dB of kT/C noise and some β.
- **Reference noise:** in-band noise on Vref multiplies the signal. High-frequency noise mixes with the shaped bitstream. So decouple hard. Most of the tile area is free for decap.
- The TT supply noise level is unknown [A6].

### 3.7 Bias
- Reuse the beta multiplier: M1 10/2 µm, K = 4, about 7.9 squares of `ppolyf_u_1k`, giving 10 µA at tt. Add a startup circuit.
- Mirror it to OTA1 (40 µA), OTA2 (10 µA) and the cascode-bias replicas.
- Its spread of −12/+29 % over temperature moves GBW and SR by the same amount. There's margin at fs = 2 MHz.

### 3.8 Test modes and observability
- **`IN_SEL` (`ui[1:0]`):**

  | `IN_SEL` | Input | What it tests |
  |---|---|---|
  | 00 | `ua[0]`/`ua[1]`, external | normal operation |
  | 01 | both inputs shorted to VCM | Idle-channel noise, offset and idle tones. **Works with no analog pins.** |
  | 10 | ladder DC at +Vref/4 (Tier 1) | Bit density should be 0.625. **Works with no analog pins.** |
  | 11 | ladder DC at −Vref/4 (Tier 1) | Bit density should be 0.375. **Works with no analog pins.** |

  That's only a few extra switches on the input side.
- **`ORDER1` (`ui[2]`, Tier 1):** bypasses integrator 2 (x1 goes straight to the comparator). If integrator 2 fails on silicon, the chip still works as a 55 dB 1st-order modulator.
- **`rst_n` low:** shorts Ci1 and Ci2 (integrators reset) and holds DOUT.
- **Outputs:** DOUT on `uo[0]`. CLK_OUT on `uo[1]` is the comparator's latch phase, so a capture device can sample DOUT on the opposite edge.
- **Decimation:** off chip. Capture ≥ 65,536 bits with the demo board's RP2040/RP2350 PIO or a logic analyzer, then run sinc³ decimation and an FFT in Python.

**Pin map** (also in `info.yaml`):

| Pin | Function |
|---|---|
| `clk` | modulator clock fs (2 MHz nominal, 0.5–5 MHz) |
| `rst_n` | low: integrators reset, DOUT held |
| `ui[1:0]` | IN_SEL: 00 external, 01 shorted to VCM, 10 +Vref/4, 11 −Vref/4 |
| `ui[2]` | ORDER1 (Tier 1): 1 = bypass integrator 2 |
| `ui[7:3]`, `uio_*` | unused (inputs / tied 0) |
| `uo[0]` | DOUT, the 1-bit stream |
| `uo[1]` | CLK_OUT (latch phase) |
| `uo[7:2]` | tied 0 |
| `ua[0]` / `ua[1]` | VINP / VINN, ±0.5 V around VCM each at full scale |
| `ua[2]` | VCM_OUT: the ladder's VCM tap through a series resistor, so the pad and the external driver can't disturb the internal VCM node. Bias the external input driver from it. |

---

## 4. Scope tiers and cut-lines

| Tier | Contents | Must be done by |
|---|---|---|
| **0: the modulator** | Both integrators with OTA1/OTA2 and SC CMFB, comparator + SR latch, clock generator, ladder references + decap, bias, IN_SEL 00/01, DOUT, CLK_OUT, rst_n | Transistor-level loop ≥ 70 dB at tt by **Sun Nov 15** |
| **1: insurance** | ORDER1 bypass, IN_SEL 10/11 internal DC, VCM_OUT on `ua[2]` | Only if Tier 0 blocks are LVS-clean by **Sun Nov 22** |
| **2: stretch** | OTA1 chopping, VREFP/VREFN override pins on `ua[3]`/`ua[4]`, a second (PMOS-input or 3rd-order) variant in the leftover area | Only if everything else is clean by **Sun Nov 29** |

Cut decisions:
- **Nov 15:** if the transistor-level loop is below 70 dB at tt, find the limiting block with the Python model (pull the integrator's real transfer from the transistor sims) and fix that block only. Don't add features.
- **Nov 22:** if Tier 0 isn't LVS-clean, drop all of Tier 1 except IN_SEL 01, which is two switches.
- **Nov 29:** if top-level DRC/LVS isn't clean, ship whatever is, with unconnected inputs tied to VCM. Precheck must pass on the dummy-plus-partial design no matter what.

---

## 5. Schedule (Nov 11 – Dec 7)

Weeks run Monday to Sunday. Exams in early December are why everything aims at **submitting on Fri Dec 4**, with the weekend as buffer.

| Week | Dates | Work | Exit criterion |
|---|---|---|---|
| **W1** | Wed Nov 11 – Sun Nov 15 | 1) **Today:** install OrbStack (or Docker) and IIC-OSIC-TOOLS. ~~Push the renamed dummy, and check that the precheck is green as `tt_um_robertliu4_dsm`.~~ Done Nov 14.<br>2) Model the reference loading (§3.6), then pick shared or separate DAC caps.<br>3) OTA1: real bias, SC CMFB, CM loop stability. OTA2 at 1/4 current.<br>4) Comparator, switches, non-overlap clock generator.<br>5) **Transistor-level modulator transient:** 4,096–8,192 cycles at 2 MHz, ideal references first, then the ladder.<br>6) Redraw OTA1 in xschem, and lay out the input pair (common centroid) to learn the rules. | **CHECKPOINT Sun Nov 15:** transistor-level loop ≥ 70 dB SNDR at tt |
| **W2** | Nov 16 – Nov 22 | Corners and the reference/bias across PVT. Layout: OTA1, OTA2, comparator, switches with the MOM cap arrays (unit caps, common centroid), clock generator (hand-placed standard cells), bias, ladder. **DRC and LVS clean per block.** | **Sun Nov 22:** all Tier 0 blocks LVS-clean → Tier 1 go/no-go |
| **W3** | Nov 23 – Nov 29 | Floorplan, decap fill, top-level routing on M1–M4, power stripes, pins per the template DEF. Top-level DRC/LVS. LEF from the final GDS. **Precheck green on the real design.** Extract the MOM caps and check that a1 is within ±10 %. | **Sun Nov 29:** real GDS passes precheck |
| **W4** | Nov 30 – Fri Dec 4 | Post-layout: OTA1 settling with extracted parasitics, plus one loop transient at tt/ss/ff. Fix and re-run the precheck. Write `docs/info.md` (test procedure, Python decimation script). **Submit Fri Dec 4.** | Submitted |
| buffer | Sat Dec 5 – Mon Dec 7 noon PST | Only things that move the precheck. Deadline 20:00 UTC Mon. | |

**Presentation:** build figures as you go. Already slide-ready: `dsm_sqnr.png`, `dsm_psd.png`, `dsm_nonideal.png` and `ota_fc.png`. The deck is a W4 task, or after Dec 7 if the presentation is later [A5].

---

## 6. Verification plan

Run every row at tt_27C_3v3, ss_85C_3v0, ff_0C_3v6, sf and fs, unless the row says otherwise.

| Block | Simulation | Pass criterion |
|---|---|---|
| OTA1 | AC, swing, noise, closed-loop step (`08_ota_fc.py`) | Already passes with ideal bias/CMFB; re-run with the real ones |
| OTA1 CMFB | CM step and CM loop gain/phase | PM > 60°, output CM within ±50 mV of VCM over the swing |
| OTA1 | Integrator transient with real switches: a1 error, settling at fs = 5 MHz | Gain error < 10 %, residual nonlinearity well below the model's 85 dB |
| Comparator | Offset (Monte Carlo), metastability at 1 mV, kickback | Decides 1 mV within T/2 at ss; offset < 50 mV |
| Clocks | Non-overlap time across corners | ≥ 2 ns everywhere, both orders correct |
| References | Droop and settling under the per-cycle charge kicks; noise | Model says distortion ≥ 85 dB down |
| Loop | Transistor-level transient, 4,096–8,192 cycles, sine at −6 dBFS, FFT | ≥ 75 dB at tt, ≥ 70 dB at corners |
| Loop | Idle channel (input shorted), DC inputs ±Vref/4 | Bit density as expected; no idle tones above −90 dBFS in band |
| Loop | Startup from rst_n, overload recovery (0 dBFS burst, then −6 dBFS) | Recovers within 100 cycles |
| Post-layout | OTA1 step and one loop run at tt/ss/ff with extracted C | ≥ 70 dB |

- **Long transients:** a transistor-level loop needs about 200 time points per cycle. 8,192 cycles is about 1.6 M points, which could take an hour or more, so run them overnight.
  - Speed up the clock generator with XSPICE digital models.
  - Use the Python model for anything that needs 65,536 samples.
- **Monte Carlo note:** the mismatch wrappers are subcircuits. Check whether your netlist instantiates `nfet_03v3` as `M…` (binned model, **no mismatch**) or `X…` (the wrapper with mismatch). The sims so far use `M`.
- **ngspice notes:**
  - KLU doesn't support `.noise`; switch with `option sparse` first.
  - Read device parameters as `let x = @m1[gm]`.

---

## 7. Layout plan

- **Floorplan:**
  - The analog pins are on the bottom edge (M4, 43.68 µm pitch): `ua[0]` at x ≈ 327 µm, `ua[1]` at 284 µm, `ua[2]` at 240 µm.
  - The digital pins are on the top edge: `clk` at x ≈ 331, `uo[0]` at 200.
  - So put the **input switches, Cs1/Ci1 and OTA1 at the bottom centre**, just above `ua[0]`/`ua[1]`.
  - Integrator 2 and the comparator go in the middle, and the **clock generator, SR latch and output buffers along the top**.
  - The ladder and decap fill the sides.
- **Matching and symmetry:**
  - Mirror the whole differential path about one vertical axis.
  - Common-centroid input pair (ABBA) with dummies.
  - Interdigitate the cascode and source devices.
  - Build Cs/Ci from **unit MOM caps**, interdigitated and with dummies. The ratio needs only ±10 % (finding 2), but symmetry between the two sides keeps the CM clean.
- **Coupling:**
  - Keep the summing nodes (OTA inputs) short and shielded.
  - Route clocks on M1/M2 away from them, and never parallel to x1.
  - Put guard rings around OTA1 and the comparator.
  - Keep the comparator's supply separate from OTA1's bias if you can.
- **Standard cells:** hand-place them (there's no automatic place-and-route in the analog template). Use the 7-track `gf180mcu_fd_sc_mcu7t5v0` cells, which is what TT GF uses.
- **Verify:**
  - KLayout DRC with the PDK deck, matching precheck, at the e8daeda PDK version.
  - netgen LVS per block and at the top level.
  - Magic extraction for MOM cap values and post-layout sims.
- **Precheck rules learned from the dummy** (`tt-support-tools/precheck`):
  - The LEF must list all 51 template pins with exactly the DEF rectangles (one rect each). It also needs VDPWR and VGND on Metal4, at least 0.8 µm wide, reaching within 10 µm of the top and bottom edges.
  - Every LEF port needs a `Metal4_Label` (46/10) polygon covering it, drawn in the **top cell** (shapes in subcells don't count).
  - Analog pin check: each used `ua` pin (`analog_pins: 3` means `ua[0..2]`) needs Metal4 or Via3 touching the 0.1–0.5 µm ring around the pin. Unused pins must have nothing there.
  - `inv_1` and most logic cells have no well taps. Put a `filltie` in every row.
  - Via1 can land on a 0.33 µm std-cell pin (0.03–0.035 µm side enclosure is legal when the line-end enclosure is ≥ 0.06 µm). Don't add an M1 pad there, because it breaks M1 spacing to the neighbouring pin.
- **Known trap from TTGF0p3:** a project was disabled because its LEF didn't match its GDS (a missing VAPWR stripe). Generate the LEF from the final GDS every time.

---

## 8. Silicon test plan (for the presentation)

1. **No analog pins needed:**
   - Power up and run `clk` = 2 MHz from the board.
   - With IN_SEL = 01 (inputs shorted to VCM), capture DOUT. The density should be 0.5 + offset. The decimated noise floor gives the idle-channel noise.
   - With IN_SEL = 10/11, the densities should be 0.625/0.375. That gives gain and offset.
2. **Full measurement:** drive a 1 kHz differential sine at −6 dBFS into `ua[0]`/`ua[1]`, biased at VCM_OUT.
   - Use an audio-grade source plus a single-ended-to-differential driver.
   - Capture 65,536+ bits, then run sinc³ decimation and an FFT for SNDR, SFDR and dynamic range (SNDR vs amplitude).
3. **Sample rate sweep:** fs from 0.5 to 5 MHz shows where settling breaks (it ties back to the OTA1 slew/GBW plots).
4. **ORDER1 mode (Tier 1):** 1st- vs 2nd-order noise shaping on the same chip. It makes a good presentation slide.
5. **Supply sensitivity:** inject a tone on VDPWR, if the board allows it.

---

## 9. Presentation outline

1. The problem and the spec: why ΔΣ, and why 2nd order, 1 bit, OSR 128.
2. Behavioural model: NTF, SQNR vs amplitude/OSR, and how each OTA spec was derived (gain, GBW, SR, kT/C).
3. The GF180 constraints that drove the design (the findings table): no MIM, no MOM model, NMOS 1/f, slow silicon, pin access.
4. OTA1: topology, gm/ID sizing, gain vs swing, noise breakdown before and after resizing, step response across corners.
5. Comparator, switches, clocking.
6. References and the reference-loading analysis.
7. Full-loop transistor-level spectrum vs the model.
8. Layout: floorplan, matching, the pre- vs post-layout table.
9. Silicon test plan, with the digital-only fallback.

---

## 10. Risk register

| Risk | L | I | Mitigation |
|---|---|---|---|
| Tool setup eats days of W1 | M | H | Install today; the precheck flow is already proven with the dummy |
| Solo layout of everything in about 2 weeks | H | H | Few distinct blocks (two OTAs of one design, one comparator); unit-cap arrays; tiers and cut-lines; your layout background |
| Analog pins not reachable on the GF board | M | H | IN_SEL short and DC modes test the loop through digital pins only; ask on Discord |
| Transistor-level loop sims too slow to iterate | M | M | Python model with extracted block behaviour; overnight runs; XSPICE clocks |
| Reference loading causes distortion | M | M | Model it in W1; decap; separate DAC caps as the fallback |
| CMFB instability | M | M | Explicit CM loop analysis (finding 5) |
| MOM cap values off (no model) | M | L | Ratio needs only ±10 %; absolute value only sets kT/C and load |
| 1/f noise higher on silicon | L | M | 10 dB of margin (6 vs 16 µV); chopping is Tier 2 |
| Supply noise from the shared TT supply | M | M | Fully differential; ratiometric references with decap; separate analog/digital rails inside the tile |
| LEF/GDS mismatch disables the project | L | H | Regenerate the LEF from the final GDS; precheck after every change |
| Exams compress W4 | H | M | Submit Fri Dec 4; nothing new after Nov 29 |

---

## 11. Assumptions to review

- **[A1]** No VAPWR; everything runs from VDPWR at 3.3 V.
- **[A2]** GF analog pins behave roughly like SKY's (< 500 Ω, < 5 pF), the TTGF26c board routes `ua[0..2]`, and the 10 kΩ pulldown jumper can be removed.
- **[A5]** The presentation is after the Dec 7 submission. If it's earlier, the slides move into W3/W4.
- **[A6]** Only the selected TT project is clocked, so supply noise comes mostly from the mux/controller and the board.
- **[A7]** You're paying for or ordering a 2×2 analog slot (€280) on TTGF26c, or the course is.
- **[A8]** Author "Robert Liu", and top module renamed `tt_um_robertliu4_dsm`. The repo keeps the name `501-pll` (renaming it on GitHub is your call; the Pages URL would change).
- **[A12]** Full scale ±1 V differential and fs = 2 MHz are my picks. The bandwidth (7.8 kHz) suits audio-band test equipment. Raise fs toward 5 MHz for 19.5 kHz.
- **[A13]** You're OK with a course/presentation story that is a ΔΣ ADC instead of a PLL (check with whoever grades it).

## 12. To-do (you)

1. Read §0, §2 and §11, and flag anything wrong (especially A12 and A13).
2. **Install OrbStack (or Docker Desktop), then IIC-OSIC-TOOLS** (`curl -fsSL https://osic.tools/install.sh | bash`, about 20 GB).
3. **Ask on the TT Discord:**
   - Does the TTGF26c board route `ua[0..5]`?
   - What are the GF analog-pin R/C?
   - Is there any guidance on GF VDPWR noise?
4. Buy or confirm the slot.

---

## 13. Repo layout and how to rerun

```
PLAN.md                  this file
info.yaml, src/, docs/   Tiny Tapeout template (pinout filled in for the ADC)
.github/workflows/       TT GDS + precheck + viewer actions (@ttgf26c), run on every push
layout/                  make_dummy_gds.py (dummy tile: template pins, stripes, one inverter, ua[2] stub) + tt_analog_2x2.def
gds/, lef/               what the TT action submits; currently the dummy from layout/make_dummy_gds.py
model/
  dsm_model.py           ΔΣ behavioural model: SQNR, swing, OTA gain/GBW/SR, kT/C -> results/dsm_*
  loop_design.py, pll_tran.py   PLL (archived, see tag pll-plan)
sim/ngspice/             ngspice decks generated from Python (GF180 models via ciel)
  spice.py               model includes, corners, runner
  01_devices.py          gm/ID, Vth
  05_moscap.py           MOS cap C-V (decap)
  07_bias.py             beta-multiplier reference spread over PVT
  08_ota_fc.py           OTA1 folded cascode: op point, AC, swing, noise, closed-loop step, 5 corners
  02/03/04/06_*.py       PLL VCO, dividers, prescaler, charge pump (archived)
sim/results/             plots and tables
```

```bash
python3 -m venv .venv && .venv/bin/pip install numpy scipy matplotlib ciel gdstk
.venv/bin/ciel enable --pdk-family gf180mcu 792ef67037d74c8c51811eab3ce23cf793491296
brew install ngspice
cd model && ../.venv/bin/python dsm_model.py
cd ../sim/ngspice && ../../.venv/bin/python 08_ota_fc.py
cd ../../layout && ../.venv/bin/python make_dummy_gds.py
```
