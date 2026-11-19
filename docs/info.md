<!---
Datasheet for the TT GF26c submission. Images must be < 512 kB each and < 1 MB in total.
DRAFT: fill in measured/post-layout numbers before submitting.
-->

## How it works

A 2nd-order, 1-bit, fully differential switched-capacitor delta-sigma modulator (Boser-Wooley loop).

- **Sampling:** the differential input on `ua[0]`/`ua[1]` is sampled at the `clk` rate (2 MHz nominal).
- **Loop:** two switched-capacitor integrators shape the quantization noise away from low frequencies, with NTF = (1 − z⁻¹)². A comparator then makes the 1-bit decision.
- **Output:** the bitstream comes out on `uo[0]`. Decimate it off chip (sinc³ filter, then an FFT) to get a high-resolution, low-bandwidth result.
- **Expected performance:** at an oversampling ratio of 128 (7.8 kHz bandwidth at 2 MHz), the design target is about 80 dB SNDR at −6 dBFS.

Internals:
- **Op-amps:** fully differential folded cascodes with switched-capacitor common-mode feedback.
- **Comparator:** a StrongARM latch followed by an SR latch.
- **References:** an on-chip resistor ladder from the 3.3 V supply with decoupling: VREFP 2.65 V, VCM 1.65 V, VREFN 0.65 V. The 1-bit DAC uses separate capacitors (half the sampling capacitor) switched between VREFP and VREFN, so the references see the same load every cycle. The full scale is ±1 V differential.
- **Clocking:** non-overlapping clocks generated from `clk` with standard cells.

## How to test

1. Apply a 2 MHz clock on `clk`, set `ui[1:0]` = 01 (inputs shorted to VCM), and release `rst_n`.
2. Capture `uo[0]` (DOUT) on the falling edge of `uo[1]` (CLK_OUT). The ones density should be about 0.5.
3. Set `ui[1:0]` = 00 and drive a differential sine (for example 1 kHz, 0.5 V peak differential) into `ua[0]`/`ua[1]`, biased at the VCM on `ua[2]`.
4. Capture at least 65,536 bits, then run sinc³ decimation and an FFT in Python to get SNDR.

`ui[1:0]` = 10 or 11 selects an internal DC input of +Vref/4 or −Vref/4, which should give ones densities of 0.625 or 0.375. `ui[2]` = 1 bypasses the second integrator (1st-order mode).

## External hardware

- A low-distortion differential signal source (an audio-grade generator plus a single-ended-to-differential driver biased from `ua[2]`).
- A way to capture the bitstream: the demo board's RP2040/RP2350, or a logic analyzer.
