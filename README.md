# 501-delta-sigma-adc

2nd-order, 1-bit, switched-cap **delta-sigma ADC modulator** for **Tiny Tapeout TTGF26c** (GF180MCU, 3.3 V), due **2026-12-07 20:00 UTC**. The project started as an integer-N PLL; that work is kept at tag [`pll-plan`](https://github.com/robertliu4/501-delta-sigma-adc/tree/pll-plan).

- **[PLAN.md](PLAN.md):** the plan, architecture decisions and trade-offs, schedule, risks and open assumptions. Start here.
- `model/dsm_model.py`: behavioural modulator model that sets the block specs. Results are in `model/results/`.
- `sim/ngspice/`: transistor-level simulations on the GF180 models (ngspice + ciel PDK). Results are in `sim/results/`.
- `layout/`: the dummy-tile generator used to prove the precheck flow.
- `info.yaml`, `src/`, `docs/`, `.github/`: the Tiny Tapeout GF analog template.

Rerun everything with the commands at the end of PLAN.md.
