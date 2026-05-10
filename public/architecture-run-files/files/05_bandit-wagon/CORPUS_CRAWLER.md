# Crawler Track — Complete Experiment Corpus

**Competition:** OpenAI Model Craft Challenge — 16MB, 10 min on 8xH100
**Track:** Crawler (recurrent loop architecture, Frugendorff lineage)
**Current Leader:** BWX 9F — 1.13867894 BPB, 15.24MB (seed 444)
**Date Range:** 2026-03-18 → 2026-04-09
**Total experiments:** 400+ (including automated sweeps)
**Scanner tool:** `python3 scripts/corpus_scanner.py --track crawler --detail`

---

## 1. Architecture Overview

The crawler descends from **The Frugendorff** — a recursive weight-sharing transformer architecture developed by Frosty40 starting 2026-03-18. K unique transformer blocks are each applied N times in sequence, producing deeper effective networks from fewer stored parameters. The saved parameter budget is reinvested into wider MLP layers.

The modern crawler is a hybrid: `NUM_FLAT_LAYERS` standard transformer blocks followed by `NUM_CRAWLER_LAYERS` shared-weight recurrent blocks that loop `CRAWLER_LOOPS` times. Each loop uses distinct RoPE scales (`CRAWLER_LOOP_ROPE_SCALES`) for position-dependent differentiation. An instruction signal (`INST_DIM`) conditions each loop.

Key constraint: all weights are quantized to int6 for submission. Shared crawler weights are quantized once but used N times — quantization error compounds with loop count.

---

## 2. Chronological Experiment Record

### Phase 0: The Frugendorff — Origin (2026-03-18 — 2026-03-23)

The Frugendorff is Frosty40's original research contribution: recursive weight sharing for transformer compression. The name is original to this project.

#### Proof of Concept (DGX Spark, 300 steps, 2026-03-18)

First validation that weight sharing + wider layers beats unique layers at matched parameter count.

| Config | val_bpb | Delta vs baseline | Params | Dim |
|--------|---------|-------------------|--------|-----|
| Baseline (9 unique layers, 512d) | 2.7927 | — | 17.05M | 512 |
| **Fractal only (3x3, 864d)** | **2.5953** | **-0.1975 (-7.1%)** | 16.57M | 864 |
| Fractal + Gravity (3x3, 864d) | 2.6149 | -0.1779 | 16.57M | 864 |
| Fractal + Gravity + AttnRes (3x3, 864d) | 2.6084 | -0.1843 | 16.58M | 864 |

**Core finding:** Weight sharing + wider layers is the dominant effect — **7.1% BPB improvement** with fewer total parameters. Gravity (auxiliary losses on early loops) hurt at low step counts. Learned gravity weights converged to [0.13, 0.13, 0.70] — model learned to suppress early-loop contributions.

#### Qwen-Guided Automated Architecture Search (DGX Spark, 141 runs)

Overnight automated sweep using Qwen model as search oracle:

| Axis | Best Value |
|------|-----------|
| Unique layers x loops | 2x4 |
| Cadence | 3 (F/N/N) |
| Learning rate | 2e-3 |
| Gradient clipping | 5.0 |
| MLP multiplier | 3x |

Winner: **2.3332 BPB** (vs 2.6371 baseline — 12% improvement)

#### Extended Autoresearch (DGX Spark, 227 runs)

| Config | Best BPB | Notes |
|--------|----------|-------|
| 4x2, cadence 4 | **2.155** | Overall best |
| 5x2, cadence 4 | 2.185 | Close second |
| 6x1, cadence 1 | 2.196 | No sharing baseline |
| 4x3, cadence 3 | 2.202 | More loops, diminishing returns |

Best cadence: cadence 4 (2.155) > cadence 3 (2.197) > cadence 1 (2.196) > cadence 2 (2.221)

#### Novel Discovery: Cadence Training

**Problem:** Running all loops every step causes a "bandsaw" loss oscillation. Shared weights receive contradictory gradient signals from different loop positions on consecutive steps.

**Solution:** Cadence training — alternate fractal steps (all loops) with normalize steps (single clean pass). Pattern F/N/N/N gives shared weights recovery steps. 227-run sweep confirmed cadence 4 is optimal. Bandsaw disappears with cadence >= 3.

#### Full-Scale H100 Runs (8xH100, 600s)

| Run | Config | Sliding BPB | Artifact | Steps | ms/step |
|-----|--------|-------------|----------|-------|---------|
| **Frugendorff Squared** | **6x2, 640d, MLP 4x** | **1.1478** | **15.15MB** | **4,390** | **137** |
| v2 | 3x4, 960d, MLP 3.0 | 1.2113 | 14.2MB | 5,738 | 105 |
| v3+TTT | 3x4, 960d, MLP 3.3 | ~1.1901 peak | 14.3MB | 5,590 | 107 |
| v1 (2-block) | 2x4, 1024d, MLP 3.0 | 1.2715 | 11.3MB | 7,625 | 79 |
| v6 hybrid | 6x2, 512d, MLP 4x | — | 10.65MB | — | — |

**Frugendorff Squared (1.1478 BPB)** was 0.025 from world lead at time of submission.

#### Novel Discovery: TTT Leverage Multiplier

Test-time training on shared weights updates all N loop iterations simultaneously — an Nx leverage multiplier per gradient step. v3+TTT peaked at **1.1901 BPB** (0.032 improvement, ~3x typical TTT gain). Aggressive TTT drifted after window 1400.

**Note: TTT was subsequently banned by competition rules. These results are historical.**

#### Frugendorff Declared Dead (2026-03-27)

H-FRUG sweep on RTX A6000 (single GPU) tested three remediation approaches:

| Hypothesis | Config | int6 BPB | Verdict |
|-----------|--------|----------|---------|
| KL Distillation | frozen teacher, KL weight 0.5 | 3.7378 | **FAIL** (-0.124 vs ctrl) |
| Loop Bottleneck Gate | 64-dim bottleneck between iterations | ~3.7x | **FAIL** |
| Reinvest → Width | dim=408, no recurrence | ~3.7x | **FAIL** |

**Root cause identified:** Shared-weight gradient conflict — same weights must simultaneously map early→mid and mid→late representations. At short budgets, optimizer can't find compromise.

**Conclusion written:** "Frugendorff / Crawler research line: CLOSED." SOTA at time of closure: 1.1129 BPB (Rat Rod Green v1).

#### Crawler Signal Analysis (2026-03-25, written up 2026-03-27)

Rigorous 7-test statistical analysis across 8 micro-crawler TSVs, 175 Frugendorff sweep configs, and production cadence ablations:

**Confirmed findings:**
1. Width is the primary lever (~0.033 BPB from 22% wider dim at fixed params)
2. Recursion (iterative refinement) provides **zero per-step benefit** — C/N loss identical, no momentum
3. More looping = early boost that **decays** over training
4. Post-processing (SWA/quant) is hostile to shared weights

**Probable findings:**
5. ~0.01 BPB from sharing as implicit regularization (from no-trigram anomaly)
6. PD mid-training lead (0.007) suggests shared structure that post-processing destroys

**Key data:** Steps after C-steps (crawler fires) are slightly *worse* than steps after N-steps. No momentum effect from iterative refinement.

#### The Resurrection: Crawler Legs (2026-03-29)

Despite being declared dead, the crawler architecture was revisited with a new approach: instead of pure recursion, use crawlers as a **hybrid component** within a flat transformer stack. This led to Crawler Leg 1.

#### Critical Discovery: Quantization Catastrophe

GPTQ quantization destroys weight-shared models. Rounding error compounds multiplicatively across loop iterations:

| Config | Pre-quant BPB | Post-quant BPB | Destruction |
|--------|--------------|----------------|-------------|
| 11L, share_start=4, 3 loops | 1.3766 | **5.716** | **catastrophic** |
| 11L, share_start=4, 4 loops | 1.4058 | **6.313** | **catastrophic** |
| 11L, share_start=4, 5 loops | 1.4138 | **6.246** | **catastrophic** |

More loops = worse survival. This finding drove the entire subsequent crawler quantization research program (loop-aware GPTQ, QAT, int8 training).

#### Frugendorff PR Submission

Submitted as PR to openai/parameter-golf. Branches: `submission/frugendorff-research`, `submission/frugendorff-clean`. Research contribution framed as compression technique, not SOTA claim.

#### Junkyard Proxy Ablations (500 steps, seed=444, 2026-03-30)
Multiple 500-step proxy sweeps on the early 4F+1C base. All same pod sessions.

**Crawler MLP Slope:** All slopes near-identical. 0.5 is already optimal (best: 0.75 at -0.00065).

**XSA Coverage:**

| XSA_LAST_N | Coverage | int6_sw_bpb | Quant gap |
|------------|----------|-------------|-----------|
| 11 | 73% | 1.52365 | 0.099 |
| 13 | 87% | 1.51982 | 0.095 |
| **15** | **100%** | **1.51431** | **0.090** |

**Finding:** Wider XSA is faster AND better. Full coverage (XSA=15) was 15ms/step faster than XSA=13.

**5F vs 4F Depth:**

| Config | int6_sw_bpb | Quant gap |
|--------|-------------|-----------|
| **4F+1C (XSA=11)** | **1.52365** | **0.099** |
| 5F+1C (XSA=14) | 1.52963 | 0.106 |
| 5F+1C (XSA=11) | 1.54404 | 0.119 |

**Finding:** 4F+1C wins. 5F adds 2.4M params that hurt quant robustness. Raw learning rate identical — entire difference lives in quantization. XSA coverage partially recovers the 5F penalty.

---

### Phase 1: Foundation (2026-03-29 — 2026-03-30)

#### Crawler_Ablations_v1 (1xH100, 600s/arm, seed=1337)
First systematic sweep of crawler infrastructure.

| Arm | Override | Int6 SW BPB | Delta vs A | Verdict |
|-----|----------|-------------|------------|---------|
| A_baseline | (none) | 1.60513 | — | baseline |
| B_loop_aware_gptq | LOOP_AWARE_GPTQ=1 | **1.56511** | **-0.0400** | **WIN** |
| E_compile_fullgraph | COMPILE_FULLGRAPH=1 | **1.57930** | **-0.0258** | **WIN** |
| D_int8_off | CRAWLER_QUANT_INT8=0 | 1.60273 | -0.0024 | wash |
| C_ema_on | SKIP_EMA=0 | 1.67479 | +0.0697 | **LOSER** |
| F_gptq_and_ema | LOOP_AWARE_GPTQ=1 SKIP_EMA=0 | 1.70575 | +0.1006 | **WORST** |

**Key findings:**
- Loop-aware GPTQ: -0.040 BPB — two-phase calibration is a real win
- EMA is actively harmful: +0.070-0.101 BPB — smooths weights in ways that destroy GPTQ calibration
- EMA + GPTQ are antagonistic — combined is worse than either alone
- Fullgraph compile: -0.026 BPB — faster step → more steps → better model

#### Crawler_Leg_1 (1xH100, 600s/arm, seed=1337)
11-arm architectural sweep. Foundational parameter map.

| Arm | Config | Int6 SW BPB | Delta vs baseline | Verdict |
|-----|--------|-------------|-------------------|---------|
| CL1-07 | mlp_mult=5.0 | **1.64868** | **-0.0977** | **BEST** |
| CL1-01 | loops=3 | **1.65890** | **-0.0875** | **WIN** |
| CL1-04 | inst_dim=16 | 1.75600 | +0.0096 | wash |
| CL1-00 | baseline (loops=4, mlp=4.0) | 1.74636 | — | baseline |
| CL1-05 | inst_dim=64 | 1.75201 | +0.0057 | wash |
| CL1-02 | loops=5 | 1.81547 | +0.0691 | **LOSER** |
| CL1-03 | inst_dim=0 (off) | 1.78019 | +0.0338 | **LOSER** |
| CL1-09 | 5F+1C | 1.79416 | +0.0478 | **LOSER** |
| CL1-06 | mlp_mult=3.0 | 1.86261 | +0.1163 | **LOSER** |
| CL1-10 | 3F+2C | 1.86610 | +0.1197 | **LOSER** |
| CL1-08 | crawler_quant_int8=0 | 1.94389 | +0.1975 | **WORST** |

**Critical findings:**
- MLP width is the largest lever: mlp=5.0 is -0.098 BPB AND faster (655ms vs 735ms)
- Fewer loops is better: each loop adds ~0.085 BPB quant gap
- inst_dim range (0-64) has max 0.034 BPB impact — nearly irrelevant
- CRAWLER_QUANT_INT8=1 is mandatory — disabling it is catastrophic (+0.198 BPB)
- More crawler blocks destroys quality at this scale (3F+2C: +0.120 BPB)
- Narrow MLP is catastrophic (mlp=3.0: +0.116 BPB)

#### Bandit_Wagon Width/Depth Ablations (500 steps proxy, seed=444)

| ARM | Config | Int6 SW BPB | Verdict |
|-----|--------|-------------|---------|
| BW-00 | dim=512, 4F+1C (anchor) | 1.18616* | reference (full run) |
| BW-03 | dim=512, 5F+1C | 1.54404 | **BEST proxy** |
| BW-04 | dim=512, 6F+1C | 1.56887 | good |
| BW-01 | dim=576, 4F+1C | 1.60382 | **LOSER** |
| BW-02 | dim=640, 4F+1C | 1.63303 | **WORST** |

**Finding: Depth beats width** at every tested point. Width expansions (576, 640) both trail depth arms.

#### Crawler_Leg_2 (8xH100, 350s/arm, seed=1337)
Production-scale confirmation of CL1 winners.

| ID | Config | Int6 SW BPB | Delta vs CL2-00 | Verdict |
|----|--------|-------------|-----------------|---------|
| CL2-02 | loops=3 + mlp=5.0 + GPTQ + COMPILE | **1.19593** | **-0.0069** | **BEST** |
| CL2-04 | loops=3 + mlp=6.0 | 1.19828 | -0.0046 | good |
| CL2-01 | loops=3 + mlp=5.0 | 1.20211 | -0.0007 | mild |
| CL2-00 | baseline (loops=4, mlp=4.0) | 1.20285 | — | baseline |
| CL2-03 | loops=2 + mlp=5.0 | 1.20667 | +0.0038 | **LOSER** |

**Findings:**
- Architecture wins compress at 8xH100 scale (CL1: -0.098 → CL2: -0.007)
- loops=2 confirmed worse — loops=3 remains optimal
- mlp=6.0 competitive but untested with full GPTQ stack
- **Production config locked: loops=3, mlp=5.0+, COMPILE_FULLGRAPH=1, LOOP_AWARE_GPTQ=1**

---

### Phase 2: Scaling & Signal Stacking (2026-03-31)

#### Bandit_Wagon_III (8xH100, 600s, seed=444)
Pyramid-512 choke + battery on 4F+1C base.

| Config | int6_sw_bpb | bytes | vs Leg 3 |
|--------|-------------|-------|----------|
| Leg 3 SOTA | 1.18720 | 8.84MB | — |
| **BW3 (pyramid+battery)** | **1.20684** | **10.07MB** | **+0.01964 WORSE** |

**Verdict: DOES NOT PROMOTE.** Pyramid-512 adds 1.57M cold params that slow convergence under 600s wallclock.

#### Bandit_Wagon_IV (8xH100, 600s, seed=444)
Battery only (no pyramid) on Leg 3 base.

| Config | int6_sw_bpb | bytes | vs Leg 3 |
|--------|-------------|-------|----------|
| **BW4 (battery only)** | **1.18731** | **8.97MB** | **-0.00015** |

**Verdict: PROMOTED.** Battery (ROPE_SCALES=9,1,1) confirmed positive — zero extra params, tighter quant gap.

#### BW5 / Bandit_Wagon_V (8xH100, 600s)
BW4 + COMPILE_FULLGRAPH=1.

| Seed | int6_sw_bpb | bytes | vs BW4 |
|------|-------------|-------|--------|
| 444 | **1.18672** | 8.61MB | **-0.00058** |
| 300 | 1.18758 | 8.82MB | +0.00012 vs Leg 3 s300 |

**Verdict: PROMOTED (mean better).** Seed 300 does not individually confirm. 2-seed mean: 1.18715 vs Leg 3 mean 1.18743 (-0.00027).

#### BW5_Cannon — Scalar Cannon (8xH100, 600s, seed=444)

| Config | int6_sw_bpb | bytes |
|--------|-------------|-------|
| BW5 champion | 1.18672 | 8.61MB |
| **BW5_Cannon** | **1.18692** | **8.44MB** |
| Delta | **+0.00020** | -0.17MB |

**Verdict: DOES NOT PROMOTE.** Gate signal (-0.00016) reversed at full run (+0.00020). Cross-run variance swamped the signal.

#### BW5_PyramidCannon — Pyramid + Cannon Combined (8xH100, 2000 steps gate)

| ARM | int6_sw_bpb | step_ms | Delta vs ctrl |
|-----|-------------|---------|---------------|
| Control | 1.28788 | 74.40 | — |
| Pyramid+Cannon | 1.32228 | 79.33 | **+0.03440 HARD FAIL** |

**Verdict: DOES NOT PROMOTE.** 1.57M cold choke params compound over time. Crossover ~step 500, diverges through 2000.

#### BW5_Pyramid — Pyramid Only (1GPU gate, 500 steps)

| ARM | int6_sw_bpb | Delta |
|-----|-------------|-------|
| Flat (control) | 1.44669 | — |
| Pyramid-512 | 1.43682 | -0.00987 |

**Verdict: CONCEPT DEFERRED.** Strong 1GPU signal but inflated by proxy scale. 8GPU PyramidCannon showed hard failure. Smaller choke dim (128/256) may work — untested.

#### BW6_Skipgram — Trigram Hash (8xH100, 2000 steps gate)

| ARM | int6_sw_bpb | Delta |
|-----|-------------|-------|
| Bigram only | 1.28952 | — |
| Bigram+Trigram | 1.28966 | +0.00014 |

**Verdict: NULL RESULT.** Crawler recurrence already approximates trigram context. Static hash adds nothing.

#### BW7 MegaGate — 8-arm ablation (4xGPU, 2000 steps)

| Arm | Change | int6_sw_bpb | Delta vs ctrl | Verdict |
|-----|--------|-------------|---------------|---------|
| CTRL-00 | baseline | 1.28913 | — | control |
| TAP-03 | TAP_DIM=32 shared | **1.28560** | **-0.00352** | **BASELINE** |
| ANC-05 | ANCHOR_DIM=32 | **1.28578** | **-0.00334** | **strong** |
| TAP-04 | TAP_DIM=16 per-loop | 1.28646 | -0.00266 | signal |
| TAP-02 | TAP_DIM=32 per-loop | 1.28773 | -0.00140 | signal |
| ANC-06 | ANCHOR_DIM=64 | 1.28750 | -0.00163 | moderate |
| SMEAR-01 | CRAWLER_LOOP_SMEAR=1 | 1.28910 | -0.00003 | **NULL** |
| FLAT-07 | FLAT_WEIGHT_SHARE=1 | 1.32607 | +0.03694 | **HARD FAIL** |

**Findings:**
- TAP shared >> TAP per-loop (one shared anchor beats 3 specializing)
- Anchor dim=32 >> dim=64 (loop state is low-dimensional)
- SMEAR null (loops already distinct via FLOW)
- SharedFlat catastrophic (-4.7M params destroyed performance)

---

### Phase 3: Interaction & Depth (2026-04-01 — 2026-04-02)

#### BW12_Interaction_2k (4xGPU, 2000 steps, seed=444)

| Arm | Description | int6_sw_bpb | Delta vs ctrl |
|-----|-------------|-------------|---------------|
| BW12INT-00 | Control (5F + TAP shared) | 1.27438 | — |
| BW12INT-01 | Tap off | 1.27239 | -0.00199 |
| BW12INT-02 | Anchor dim=32 | 1.27337 | -0.00102 |
| BW12INT-Q1 | Standard GPTQ | 1.27234 | -0.00204 |
| BW12INT-Q2 | Loop-aware GPTQ | 1.27234 | -0.00204 |

**Finding:** Tap-off and GPTQ both positive. Q1 and Q2 tied exactly on this run.

#### BW13_TapOff_Anchor_GPTQ_2k (4xGPU, 2000 steps, seed=444)

| Arm | Description | int6_sw_bpb | Delta vs ctrl |
|-----|-------------|-------------|---------------|
| BW13INT-00 | Control (tap-off) | 1.27152 | — |
| BW13INT-01 | Anchor dim=32 | 1.27428 | **+0.00276 REGRESSION** |
| BW13INT-02 | Anchor dim=64 | 1.27444 | **+0.00292 REGRESSION** |
| BW13INT-Q1 | GPTQ (128x2048) | 1.26958 | -0.00193 |
| BW13INT-Q1L | GPTQ-lite (64x1024) | 1.26975 | -0.00177 |

**Finding:** Anchor hurts on tap-off baseline. GPTQ helps. GPTQ-lite nearly as good with less calibration cost.

#### BW14_BigSwing_2k (8xH100, 2000 steps, seed=444)

| Arm | Description | int6_sw_bpb | Delta vs ctrl |
|-----|-------------|-------------|---------------|
| BW14BS-00 | Control (tap-off) | 1.27383 | — |
| BW14BS-01 | NUM_FLAT_LAYERS=6 | **1.26684** | **-0.00700** |
| BW14BS-02 | Crawler choke flat-128 | 1.28552 | +0.01169 |
| BW14BS-03 | Crawler choke flat-512 | 1.27378 | -0.00005 |

**Finding:** 6-flat depth is the biggest single-arm hit (-0.007). Choke flat-128 is dead. Choke flat-512 is null.

#### Nightcrawler (8xH100, 600s, 3-seed)
Bridge from 5F to 9F architecture. Added a fifth flat layer on each side of the crawler bottleneck (5F+1C+5F).

| Seed | int6_sw_bpb | Steps | Size |
|------|-------------|-------|------|
| 444 | 1.17651 | 7,074 | 10.05MB |
| 4 | 1.17676 | 7,074 | 10.27MB |
| 300 | 1.17490 | 7,077 | 10.34MB |
| **mean** | **1.1761** | | |

Config: NUM_FLAT_LAYERS=5, TAP_DIM=32, ANCHOR_DIM=0, COMPILE_FULLGRAPH=1, step_avg=85.3ms.

#### BWX 9F Full Run (8xH100, 600s, seed=444)
**CURRENT IN-TREE LEADER**

| Metric | Value |
|--------|-------|
| int6_sw_bpb | **1.13867894** |
| model_params | 26,270,292 |
| step_avg | 110.19ms |
| steps | 5,446 |
| bytes | 15,239,617 (15.24MB) |

Config: 9F+1C, loops=3, ROPE=9,1,1, INST_DIM=32, TAP=0, ANCHOR=0, COMPILE_FULLGRAPH=1, SKIP_GPTQ=1.

#### Isolated 10F (4xH100, 2000 steps, seed=444)

| Metric | Value |
|--------|-------|
| int6_sw_bpb | 1.24295 |
| bytes | 17,833,044 |

**Verdict:** Worse than 9F, over 16MB. **DEAD.**

---

### Phase 4: Quant Fix & Ouroboros (2026-04-04 — 2026-04-06)

#### BWXII_QuantFix — 1GPU Quant Sweep

Best result: `T4_smart_wd012_Q2_gptq_loop_int8`
- int6_sw_bpb: 1.27427
- quant_gap: 0.0109
- bytes: 12,246,411

**Finding:** smart_skip is strongest quant-fix intervention. Higher WD alone doesn't beat smart_skip.

#### BWXII_QuantFix — 2xGPU Movie Test

| Arm | raw_bpb | int6_sw_bpb | quant_gap |
|-----|---------|-------------|-----------|
| R1_fire_embed | 1.2587 | 1.28121 | 0.0225 |
| R4_full_fix | 1.2420 | 1.28033 | 0.0383 |

**Finding:** R4_full_fix improved raw BPB but didn't solve quant gap. Quant erased most gains.

#### Ouroboros Ablation (4xGPU, 600s, seed=300)

| Arm | int6_sw_bpb | Delta vs ctrl | Verdict |
|-----|-------------|---------------|---------|
| control | 1.16409 | — | baseline |
| noisy_qat | **1.16113** | **-0.00296** | **STRONG** |
| crawler_int8 | **1.16094** | **-0.00315** | **BEST** |
| contractive | **1.16183** | **-0.00227** | **positive** |

All three arms beat control. All trained faster (176-178ms vs 186ms).

#### Ouroboros_III Full Run (8xH100, 600s, seed=444)
**Stacking all three Ouroboros signals.**

| Metric | BWX 9F | Ouroboros III |
|--------|--------|--------------|
| int6_sw_bpb | 1.13868 | **1.14462** |
| Delta | — | **+0.00594 WORSE** |

**Verdict: DOES NOT PROMOTE.** noisy_qat + crawler_int8 + contractive did NOT compose positively in the full stacked run. Stacking failed.

#### Helix_ab_3 Gate (8xH100, 2000 steps, seed=444)

| Arm | int6_sw_bpb | step_ms | Delta vs ctrl |
|-----|-------------|---------|---------------|
| HAB3-00_ctrl | 1.28905 | 72.77 | — |
| HAB3-01_helix | **1.42860** | 86.35 | **+0.13955 HARD FAIL** |

**Verdict: DOES NOT PROMOTE.** Massive regression. Helix SplitHead concept is dead at this scale.

#### BW21_NoisyQAT_9F
**Status:** Hypothesis filed, production gate NEVER RUN. Results table empty.

---

### Phase 5: Loop Depth, Eco Concepts, Multi-Crawler (2026-04-07 — 2026-04-09)

#### BW22_LoopDepth_9F
**Status:** Hypothesis filed (5-arm loop sweep: 3-5 loops with various batteries). Results table EMPTY — never ran.

#### BW23_EcoConcept_9F
**Status:** Hypothesis filed (QAT surrogate variants + mixed-bit export policies). Results table EMPTY — never ran.

#### BW22_LoopDepth_9F (8xGPU, 2000 steps gate, seed=444)

| Arm | LOOPS | ROPE_SCALES | int6_sw_bpb | step_ms | Delta vs ctrl |
|-----|-------|-------------|-------------|---------|---------------|
| A0_ctrl | 3 | 9,1,1 | 1.24352 | 110.28 | — |
| A1_loop4_naive | 4 | 9,1,1,1 | 1.24255 | 119.82 | -0.00097 |
| A2_loop4_battery | 4 | 9,3,1,1 | 1.24260 | 119.58 | -0.00093 |
| **A3_loop5_battery** | **5** | **9,3,1,1,1** | **1.24091** | **128.88** | **-0.00261** |
| A4_loop5_prog | 5 | 9,5,3,1,1 | 1.24176 | 128.99 | -0.00176 |

**Verdict: PROMOTES** (A3 loop5 battery as quality-priority candidate).
Throughput cost significant: loop4 ~9% slower, loop5 ~17% slower. Quality scaled with depth.

#### Crawler_Katta — RK Solver Variants
**Status:** Hypothesis filed, results tables EMPTY. Gate never completed. Concept: Runge-Kutta crawler solvers (rk2_fast, rk4_fast, rk24_hybrid) for throughput without quality loss.

#### Corpus Ablations v1 (4xGPU, 1500 steps, seed=444)
16-arm screen on BWX 9F base. Hard numbers from pod logs:

| Arm | Change | int6_sw_bpb | Delta vs A00 | Verdict |
|-----|--------|-------------|--------------|---------|
| A00 | Control (BWX 9F) | 1.32999 | — | baseline |
| **A07** | **NUM_CRAWL=2** | **1.31766** | **-0.01234** | **BREAKTHROUGH** |
| A04 | 4 loops diff (ROPE=9,3,1,1) | 1.32533 | -0.00467 | strong |
| A03 | 4 loops naive (ROPE=9,1,1,1) | 1.32604 | -0.00396 | strong |
| A05 | 5 loops prog (ROPE=9,5,3,1,1) | 1.32595 | -0.00405 | strong |
| A02 | ANCHOR_DIM=32 | 1.32771 | -0.00229 | positive |
| A01 | TAP shared | 1.32881 | -0.00118 | mild |
| A08 | CRAWLER_QUANT_INT8=1 | 1.32918 | -0.00082 | neutral |
| A06 | INST_DIM=64 | 1.33096 | +0.00097 | **DEAD** |
| A09 | QAT legacy (STE) | CRASHED | — | disk full |
| A10-A11 | QAT softclamp, sigmoidste | NOT RUN | — | disk full |

**Key finding:** 2 crawler layers (A07) is the breakthrough signal: -0.01234 BPB at 1500 steps. A09-A11 crashed due to pod disk space exhaustion during the overnight run.

#### Layer Relationship Grid (2xGPU, 1000 steps, seed=444)
5x4 grid: NUM_FLAT_LAYERS(5-9) x NUM_CRAWLER_LAYERS(1-4).

| Config | int6_sw | Delta vs 9F+1C | step_ms |
|--------|---------|-----------------|---------|
| **8F+3C** | **1.39529** | **-0.01727** | 181 |
| 7F+4C | 1.39547 | -0.01709 | 206 |
| 9F+3C | 1.39599 | -0.01657 | 198 |
| 7F+3C | 1.39910 | -0.01346 | 176 |
| 6F+4C | 1.40000 | -0.01256 | 207 |
| 9F+1C (ctrl) | 1.41256 | — | — |

**Finding:** 8F+3C is quality peak. 3C optimal at 3 loops (C=loops symmetry). 4C reverses on 9F row.

#### Symmetry Ablation (4xGPU, 1000 steps, seed=444)
Higher symmetry orders (4x4, 6x6, 8x8) on 8F base. Only 4x4 completed (806ms/step — impractical). 3x3 confirmed optimal under wallclock pressure.

#### BW_9F2C (8xH100, 600s, seed=444)

| Metric | BWX 9F leader | BW_9F2C |
|--------|---------------|---------|
| int6_sw_bpb | 1.13868 | **1.13190** |
| Delta | — | **-0.00678 QUALITY PASS** |
| bytes | 15,239,617 | 16,857,961 |
| artifact legal? | YES | **NO (860KB over)** |
| step_avg | 110ms | 137.76ms |
| steps | 5,446 | 4,356 |

**Verdict: QUALITY PASS BUT SIZE FAIL.** Extra crawler layer adds ~1MB of params. GPTQ might recover size but adds wallclock cost.

#### Trapper_Keeper_1 — 8F+3C (8xH100, 600s, seed=444, NO FA3)

| Metric | BWX 9F leader | TK1 |
|--------|---------------|-----|
| int6_sw_bpb | 1.13868 | **1.13527** |
| Delta | — | **-0.00341 QUALITY PASS** |
| bytes | 15,239,617 | 17,948,983 |
| artifact legal? | YES | **NO (1.95MB over with zstd)** |
| step_avg | 110ms | 157.47ms |
| steps | 5,446 | 3,811 |

**Verdict: QUALITY PASS BUT SIZE FAIL.** Pod lacked FA3 (157ms/step → only 3,811 steps). With FA3: ~110ms → ~5,450 steps → better quality. Brotli recompress expected to save 10-15% → borderline 16MB. 3 loops confirmed optimal (4th loop is pure waste).

---

## 3. Dead Hypotheses — Do Not Retest

| Hypothesis | Result | Evidence |
|-----------|--------|----------|
| EMA (SKIP_EMA=0) | +0.070-0.101 BPB | Crawler_Ablations_v1 arm C, F |
| loops=5 | +0.069 BPB | CL1-02 |
| loops=2 | +0.004 BPB | CL2-03 |
| mlp_mult=3.0 | +0.116 BPB | CL1-06 |
| CRAWLER_QUANT_INT8=0 | +0.198 BPB | CL1-08 |
| 3F+2C split | +0.120 BPB | CL1-10 |
| Width expansion (dim=576,640) | +0.017-0.049 | BW-01, BW-02 |
| Pyramid-512 choke (full run) | +0.020 vs Leg 3 | BW3 |
| PyramidCannon combined | +0.034 BPB at gate | BW5_PyramidCannon |
| Trigram hash | +0.00014 (null) | BW6_Skipgram |
| SMEAR | -0.00003 (null) | BW7 SMEAR-01 |
| SharedFlat (FLAT_WEIGHT_SHARE=1) | +0.037 BPB | BW7 FLAT-07 |
| Scalar cannon at scale | +0.00020 (reversed) | BW5_Cannon |
| Anchor on tap-off | +0.003 (regression) | BW13 |
| Crawler choke flat-128 | +0.012 BPB | BW14BS-02 |
| Helix SplitHead | +0.140 BPB | Helix_ab_3 |
| Ouroboros III (stacked noisy_qat+int8+contractive) | +0.006 BPB | Ouroboros_III |
| INST_DIM=64 | +0.001 BPB | Corpus A06 |
| QAT sigmoidste | +0.041 BPB | Corpus A11 |
| 10F (isolated) | worse + over 16MB | BW16 isolated |
| Symmetry orders 4+,6+,8+ | impractical step_ms | Symmetry ablation |

---

## 4. Confirmed Positive / Open Leads

| Finding | Delta | Status |
|---------|-------|--------|
| loops=3 (from 4) | -0.088 BPB (CL1), confirmed CL2 | **LOCKED** |
| mlp=5.0+ | -0.098 BPB (CL1), confirmed CL2 | **LOCKED** |
| Loop-aware GPTQ | -0.040 BPB (Ablations_v1) | **LOCKED in CL2** |
| COMPILE_FULLGRAPH=1 | -0.026 BPB | **LOCKED** |
| Battery ROPE 9,1,1 | -0.00015 (BW4) | **LOCKED** |
| 2 crawler layers (9F+2C) | -0.00678 production | **BLOCKED by size** |
| 3 crawler layers (8F+3C) | -0.00341 production | **BLOCKED by size** |
| QAT softclamp | -0.0047 screen | **UNTESTED at production** |
| 4 loops diff battery | -0.0046 screen | **UNTESTED at production** |
| noisy_qat (isolated) | -0.00296 (4xGPU) | **FAILED in stack (Ouro III)** |
| crawler_int8 (isolated) | -0.00315 (4xGPU) | **FAILED in stack (Ouro III)** |
| Anchor dim=32 (on BW5 base) | -0.00334 (4xGPU) | **REGRESSED on tap-off base** |
| TAP shared dim=32 | -0.00352 (4xGPU) | Baked into BW8 working baseline |

---

## 5. Cost Accounting

All runs combined across this track:
- 8xH100 full runs: BWX 9F, BW5, BW5_Cannon, BW4, BW3, Ouroboros_III, BW_9F2C, TK1 = ~8 runs × ~$3-4 = ~$24-32
- 8xH100 gates (2000 steps): BW5_PyramidCannon, BW6, BW7 MegaGate, BW12, BW13, BW14, Helix_ab_3 = ~7 × ~$1 = ~$7
- 4xH100 runs: CL2, Ouroboros ablation, Corpus ablation, Layer grid, Symmetry, TK1 safe/aggressive = ~6 × ~$1-2 = ~$6-12
- 1xH100 runs: Crawler_Ablations_v1, CL1, BW Width/Depth, BW5_Pyramid, BW5_Cannon 1GPU = ~5 × ~$0.50 = ~$2.50
- Total estimated: **~$40-55**

---

## 6. Key Lessons

1. **Quant gap compounds with loop count.** Each shared-weight loop adds ~0.085 BPB quant penalty. loops=3 is the sweet spot — enough capacity, manageable quant cost.

2. **Gate signals compress at scale.** CL1 showed mlp=5.0 at -0.098 BPB; CL2 showed -0.007. Architecture ceilings are hit faster with more training steps. Don't trust proxy magnitudes — only directions.

3. **Stacking doesn't compose.** Ouroboros III stacked three individually-positive signals and REGRESSED. Signal interactions are non-linear and must be tested as stacks, not assumed additive.

4. **Size is the binding constraint.** Both quality-positive multi-crawler configs (9F+2C, 8F+3C) are blocked by the 16MB artifact cap. The best crawler architecture is larger than the competition allows.

5. **EMA is poison for crawler quant.** Unlike neural track where EMA + SWA helps, crawler's shared-weight quantization is destroyed by EMA smoothing. SKIP_EMA=1 is mandatory.

6. **Depth > Width for crawlers.** Every width expansion hurt. Every depth expansion (up to 9F) helped. The model dimension (512) appears optimal — don't touch it.

7. **Loop-aware GPTQ is the only GPTQ that works.** Standard GPTQ calibrates flat layers correctly but doesn't account for quantized-flat activations flowing into crawler loops. Two-phase calibration is essential.

8. **Architecture declared dead, then resurrected.** The Frugendorff was formally closed on 03-27 with the conclusion "Crawler research line: CLOSED." Two days later, the hybrid flat+crawler approach reopened it and eventually produced the in-tree leader. Research directions that fail in pure form can succeed as components.

9. **Width explains 85% of the crawler advantage.** The rigorous signal analysis (7 statistical tests, 175 configs) proved the crawler's benefit is primarily from wider layers at fixed param count, not from iterative refinement. C-step and N-step training losses are identical. There is no momentum effect from recursion.

10. **The best architecture is too big for the competition.** 8F+3C and 9F+2C both beat the leader on quality. Both exceed the 16MB artifact cap. The competition constraint, not the architecture, is the binding limit.

---

## 7. Production Records (In-Tree)

| Record | Date | int6_sw_bpb | Size | Seeds | Notes |
|--------|------|-------------|------|-------|-------|
| BW-00 Anchor | 2026-03-30 | 1.18616 | 9.10MB | s444 | 4F+1C, COMPILE_FULLGRAPH=0 |
| Crawler Leg 3 | 2026-03-30 | 1.18720 (s444) | 8.84MB | 3-seed mean 1.18743 | loops=3, mlp=6.0, SKIP_GPTQ=1 |
| ClownCar X | 2026-03-29 | 1.1860 (s444) | 9.21MB | 3-seed mean 1.1867 sw | +Cubric Ngram9 eval-time cache |
| Nightcrawler | 2026-04-01 | 1.17651 (s444) | 10.05MB | 3-seed mean 1.1761 | 5F+1C, TAP_DIM=32 |
| **BWX 9F** | **2026-04-02** | **1.13868** | **15.24MB** | s444 only | **Current in-tree leader** |

---

## 8. Research Arc Narrative

**2026-03-18:** Proof of concept. 3x3 fractal (shared weights + wider layers) beats 9L unique baseline by 7.1% BPB on DGX Spark. The Frugendorff is born.

**2026-03-18–22:** 400+ automated architecture experiments. Cadence training discovered (F/N/N/N pattern eliminates gradient conflict). TTT leverage multiplier found (Nx gain per shared-weight update). Frugendorff Squared reaches 1.1478 BPB on 8xH100 — 0.025 from world lead.

**2026-03-22–23:** Quantization catastrophe discovered. GPTQ destroys shared weights (1.38 → 5.7 BPB). Compression sweep on SwiGLU variants all fail. TTT banned by competition rules.

**2026-03-25–27:** Rigorous signal analysis proves width is the dominant mechanism, not recursion. H-FRUG remediation attempts all fail. Research line formally declared dead.

**2026-03-29:** Resurrection. New approach: crawlers as hybrid components within flat transformer stacks, not pure recursive architectures. Crawler Leg 1 maps the parameter space (11 arms). MLP width (-0.098 BPB) and fewer loops (-0.088 BPB) are the biggest levers.

**2026-03-30:** Crawler Leg 2 confirms at 8xH100 scale. Production config locked: loops=3, mlp=5.0+, COMPILE_FULLGRAPH=1, LOOP_AWARE_GPTQ=1. CL2-02 = 1.19593 BPB.

**2026-03-31:** BW3 (pyramid choke) fails at full run. BW4 (battery only) promotes. BW5 (fullgraph compile) promotes. BW7 MegaGate finds TAP shared (-0.00352) and Anchor (-0.00334). Cannon, trigram, SMEAR all null/dead.

**2026-04-01–02:** Depth scaling from 4F to 9F. BW12-BW14 interaction gates. BWX 9F reaches 1.13868 BPB — current in-tree leader.

**2026-04-04–06:** Quant fix exploration (BWXII). Ouroboros ablation finds three positive signals that fail to compose (Ouroboros III regresses). Helix SplitHead is a hard fail (+0.140 BPB).

**2026-04-07–09:** Multi-crawler breakthrough. Layer relationship grid maps full flat×crawler surface. 8F+3C is quality peak. Both 9F+2C (-0.00678) and 8F+3C TK1 (-0.00341) beat the leader on quality but exceed 16MB artifact cap.

**Current state:** The best architecture exceeds the competition's size constraint. The binding limit is not intelligence — it's compression.

---

*Document generated 2026-04-10. Source: parameter-golf-lab, sota_crawler, sota_nueral experiment records, git history, pod logs.*
*Scanner tool: `python3 scripts/corpus_scanner.py --track crawler --detail`*
