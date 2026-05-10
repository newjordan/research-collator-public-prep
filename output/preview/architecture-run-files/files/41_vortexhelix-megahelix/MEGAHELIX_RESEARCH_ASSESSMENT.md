# Megahelix Research Assessment

Last consolidated: 2026-04-24

This document organizes the Megahelix campaign for assessment and deep study. It separates proven evidence from interpretation, and it records the next questions that need controlled experiments rather than more broad pod churn.

## Scope And Rules

Megahelix is the Vortex-Helix megakernel line. The operating principle remains:

- if it can be fused, it should be fused

The practical research rules currently in force are:

- single seed by default: `SEEDS=16180`, `ALLOW_MULTI_SEED=0`
- fused-only research lane unless explicitly overridden
- promote only "good good": `val_bpb` must improve and `step_avg` must not regress
- use rapid screens to cut bad signal quickly, but do not trust over-aggressive early cuts
- keep legality separate from quality: a strong `val_bpb` is not a submission if it exceeds the byte cap

## Evidence Sources

Local files used for this consolidation:

- `recovery/megahelix/README.md`
- `recovery/megahelix/plan.md`
- `recovery/megahelix/preflights.md`
- `recovery/megahelix/reconciliation.md`
- `recovery/megahelix/test_ladder.md`
- `recovery/megahelix/AUTORESEARCH_HANDOFF.md`
- `recovery/megahelix/handoff_next_agent.sh`
- `recovery/megahelix/run_kernel_tail_ab.sh`
- `recovery/megahelix/run_8x_legal_submission_best.sh`
- `evidence/megahelix_logs_20260424T_pull/README.md`
- `evidence/megahelix_logs_20260424T_pull/pod_a/logs/...`
- `evidence/megahelix_logs_20260424T_pull/pod_b/logs/...`
- `evidence/megahelix_logs_20260424T_pull/pod_c/logs/...`

Remote read-only handoff checks supplied current result summaries from pods A, B, and C. Those pod logs have now been pulled locally under `evidence/megahelix_logs_20260424T_pull/`: 733 text log files, 5.7 MB total, no checkpoints or model blobs.

The reported `evidence/pod_pulls/35372056_2026-04-24_all_after_megahelix/RESULTS.md` bundle is still not present locally in this checkout, so that specific 8x artifact-size result remains recorded as user-supplied evidence until the bundle is pulled.

## Current Anchors

Best current legal lab anchor:

- run: `logs/megahelix_lab_rnorm_s3_16180`
- `val_bpb=1.3959`
- `step_avg=283.67ms`
- selected by the good-good rule for the current 8x legal runner

Historical long-run fused-tail quality floor:

- run: `logs/megahelix_kernel_tail_fused40m_16180`
- `val_bpb=1.3225`
- `step_avg=293.93ms`
- important quality reference, but not the current rapid legal anchor

User-supplied 8x Megahelix pull:

- path reported: `evidence/pod_pulls/35372056_2026-04-24_all_after_megahelix/RESULTS.md`
- pod idle at pull time: all 8 GPUs at `0 MiB / 0%`
- `val_bpb=1.3104`
- exact int8 roundtrip `1.31477542`
- total submission bytes `26,469,415`
- assessment: strong quality signal, not legal under the `16,000,000` byte cap

Current 8x legal submission runner:

- script: `recovery/megahelix/run_8x_legal_submission_best.sh`
- variant: fused tail, `VORTEX_RNORM_EPILOGUE_NUM_STAGES=3`, `VORTEX_RNORM_EPILOGUE_NUM_WARPS=8`
- seed: `16180`
- GPUs: default `0,1,2,3,4,5,6,7`
- final validation and int8+zlib artifact enabled
- rejects if `final_model.int8.ptz + test_vortex_2k.py` exceeds `16,000,000` bytes

## Research Phases So Far

### Baseline Reconciliation

The campaign started by reconciling root versus `pod_current/`, aligning CSR semantics, and defining a staged ladder before GPU work. The canonical CSR convention is now centralized through `kernels/csr.py`, with training, parity, and bench intended to share the same block-causal meaning.

Key early baseline facts:

- recovered `ATTN_SCALE_INIT=0.20`, `QK_GAIN_INIT=0.35`, `MATRIX_LR=0.045-0.050` neighborhood
- recovered fused-only Tier 3 smoke: `val_bpb=2.1217`, `step_avg=282.27ms`, `tok_per_sec=232,175`
- Tier 2 fused microbench: `fwd_p50=0.2468ms`, `bwd_p50=1.1765ms` for the recorded small shape

### Semantic Lane

The best semantic lane before the recent fused-tail work is:

- `VORTEX_MIXER_MODE=chaos`
- `ADD_MLP=1`
- `VORTEX_ENABLE_PERTURB=0`
- `VORTEX_CHAOS_DEPTH=2`
- `QK_GAIN_INIT=0.30`
- `ATTN_SCALE_INIT=0.18`
- `MATRIX_LR=0.050`
- `SCALAR_LR=0.020`
- `MUON_BACKEND_STEPS=7`
- `MUON_MOMENTUM=0.95`
- `GRAD_CLIP_NORM=1.0`

### Fusion Progression

The proven fusion winner is the fused residual plus MLP norm tail:

- env: `VORTEX_FUSE_RESIDUAL_MLP_NORM_EPILOGUE=1`
- main mode: `TAIL_MODE=fused`
- role: fuses the post-core tail boundary and materially improves training quality over earlier mixed/chaos-only lines

Native GQA inside fused kernels was a real improvement:

- removed Python-side `repeat_interleave` for K/V expansion
- maps `q_head -> kv_head` in fused forward/backward
- runs `dk/dv` accumulation over native kv heads
- improved the 900s fused-tail lane versus prior same-seed runs

### Front-Side Fusion

Front-side fusion has been explored and is currently closed for spend.

Implemented or tested:

- fused front prep: `VORTEX_FUSE_RESID_MIX_ATTN_NORM=1`
- fused Q/K prep: `VORTEX_FUSE_QK_PREP=1`
- packed QKV projection: `VORTEX_FUSE_QKV_PROJ=1`
- combined block entry: `VORTEX_FUSE_BLOCK_ENTRY=1`
- cuBLAS packed-QKV block-entry fallback: `VORTEX_BLOCK_ENTRY_CUBLAS_QKV=1`

Evidence:

- standalone front prep and Q/K prep are valid but worse than fused tail
- packed QKV loses even when Muon is disabled, so Muon orthogonalization is not the reason packed QKV loses
- full Triton block-entry matmul is unusable as implemented: about `212x` slower than cuBLAS due to tiny per-program tiling
- cuBLAS block-entry path also lost in training signal

Assessment:

- keep large matmuls in cuBLAS
- do not spend more GPU budget on the existing front-side QKV/QK-prep branches unless the implementation changes materially

### Tail Kernel And RNorm Sweeps

The current lab is focused on rnorm epilogue staging and warp shape around the fused-tail winner.

Current anchor to beat:

- `rnorm_s3`: `val_bpb=1.3959`, `step_avg=283.67ms`

Important near miss:

- `rnorm_s7_w32_confirm`: `val_bpb=1.3964`, `step_avg=275.05ms`
- faster than anchor, but quality is slightly worse; by good-good, reject as default legal submission

Important speed/quality tradeoff:

- `rnorm_s7_w16_confirm`: `val_bpb=1.3987`, `step_avg=273.95ms`
- significantly faster, but quality misses anchor

Interpretation:

- rnorm staging has real speed potential
- quality is sensitive enough that speed-only wins should not displace `s3` without a quality recovery lever

### Rapid-Screen Instrumentation

Rapid logging was expanded in `test_vortex_2k.py`:

- logs `tok_per_sec`
- quick validation every `RAPID_VAL_EVERY_REPORTS`
- quick validation cap via `RAPID_VAL_MAX_SEQS`
- rapid reject by step time and tokens/sec
- early bad-signal cutoff via `RAPID_REJECT_QUICK_VAL_MIN_STEPS` and `RAPID_REJECT_QUICK_VAL_BPB`

Important calibration lesson:

- rejecting at step `100` by speed was too aggressive for normal runs
- step `500+` is more defensible for speed screens
- quick-bpb step `100` is useful for pathological plateau detection, especially on pod C

### Pod C Reliability

Pod C repeatedly produced a bad learning plateau:

- train loss around `9.01`
- quick val bpb around `2.389`
- final short-run val bpb around `2.4027`
- happened across warps, stages, DKV brackets, and default health checks

Assessment:

- C results should be treated as health diagnostics, not model evidence, until a baseline sanity run learns normally
- the failure pattern is too stable to interpret as a normal hyperparameter loss
- likely causes to prove or eliminate: data mount mismatch, environment/build mismatch, seed/data ordering mismatch, broken artifact path, GPU/process affinity mistake, stale code, or a kernel-specific correctness issue exposed on that host

### Utilization Concern

Observed Megahelix utilization:

- roughly `80%` GPU utilization during a meaningful run
- low memory usage, around `4-6GB` allocated/reserved in observed logs
- high CPU load on the Python worker, often about one saturated CPU
- H100 power and clocks did not suggest thermal throttling

Assessment:

- this looks underpowered by host-side overhead, launch overhead, too-small kernels, optimizer overhead, or gaps between kernels
- it does not currently look like a memory-capacity limit
- the next serious optimization pass should use tracing before more wide sweeps

## Legality State

The best quality result currently known to this consolidation is not legal:

- `val_bpb=1.3104`
- exact int8 roundtrip `1.31477542`
- total bytes `26,469,415`
- over cap by `10,469,415` bytes

The best legal runner defaults to the proven `rnorm_s3` lab anchor because the faster `s7` branches failed the quality half of good-good.

Deep-study question:

- can the `1.31` quality lane be legalized, or is it inherently too large under the current artifact format?

Candidate legality levers to assess:

- artifact accounting: verify exact required files and byte-count rule
- stronger compression or code-byte trimming
- mixed precision or lower-bit quantization for low-sensitivity tensors
- structured pruning or shape reduction that preserves most of the 1.31 quality
- tokenizer/vocab/model-shape tradeoffs
- removing redundant checkpoint payload and metadata

## Current Conclusions

1. The fused tail is the only proven fusion win.
2. Existing front-side fusion branches should stay closed.
3. RNorm epilogue tuning has real speed upside but has not produced a good-good replacement for `s3`.
4. The `1.3104` 8x signal is important, but it is not a legal submission until the byte problem is solved.
5. Pod C is not trustworthy for learning conclusions until a controlled sanity baseline passes.
6. The utilization problem is now a first-class research target; profiling should precede another broad sweep.

## Deep Study Agenda

### 1. Legalize The Strong 8x Signal

Goal:

- determine whether the `1.3104` lane can be brought under `16,000,000` bytes without destroying quality

Required artifacts:

- pull the missing `evidence/pod_pulls/35372056_2026-04-24_all_after_megahelix/RESULTS.md` locally
- capture exact artifact file list and byte accounting
- record tensor-level size contribution if possible

Decision gate:

- if legalization requires too much model-capacity reduction, keep `rnorm_s3` as the legal lane and treat `1.3104` as a quality ceiling reference

### 2. Profile The 80% Utilization Gap

Goal:

- identify whether the bottleneck is CPU/data, launch overhead, kernel occupancy, optimizer, or synchronization

Controlled run:

- one pod, one GPU, `TAIL_MODE=fused`, `rnorm_s3`
- warm up, then trace a small fixed window
- compare with `rnorm_s7_w32` because it is faster and near-anchor

Metrics to capture:

- CPU time per training step
- CUDA kernel count per step
- top kernel durations
- GPU idle gaps
- optimizer step cost
- validation/logging overhead outside the measured train window

Preferred tools:

- `torch.profiler` for Python/CUDA attribution
- `nsys` if available for timeline gaps and launch overhead
- `nvidia-smi dmon` or equivalent only as coarse corroboration

### 3. Repair Or Quarantine Pod C

Goal:

- prove whether C can run a known-good baseline

Minimum sanity:

- run exact `rnorm_s3` baseline with checksummed code/data/tokenizer
- compare first 100 losses against pod A/B
- compare env vars, git diff, package versions, and CUDA/Triton cache state

Decision gate:

- if C still hits `train_loss~9.01`, remove it from research evidence and use it only for infrastructure diagnostics

### 4. Revisit RNorm Speed Wins With Quality Recovery

Goal:

- keep the speed gains from `s7_w16` or `s7_w32` while recovering the small quality loss versus `s3`

Candidate controlled variables:

- `ATTN_SCALE_INIT`
- `QK_GAIN_INIT`
- `MATRIX_LR`
- `SCALAR_LR`
- warmup/warmdown
- rapid validation cadence

Guardrail:

- do not promote speed-only variants unless `val_bpb <= 1.3959` and `step_avg <= 283.67ms`

### 5. Do Not Reopen Front-Side Fusion Blindly

Only reopen if one of these changes is true:

- packed QKV implementation changes materially
- block-entry matmul is delegated to cuBLAS while only elementwise ops are fused
- a profiler proves front-side overhead is the dominant utilization gap
- a correctness issue is found in the tested front-side branches

## Assessment Checklist For Tomorrow

Before running more pods:

- pull and store the missing evidence bundle locally
- read `MEGAHELIX_RESULT_LEDGER.md`
- decide whether tomorrow is a legalization day or a profiler day
- if profiling, run exactly one controlled trace before any broad sweep
- if legalization, generate a tensor byte ledger before changing training

Recommended first action:

- profile `rnorm_s3` versus `rnorm_s7_w32` on one known-good pod, because that directly targets the user-observed 80% utilization and the closest speed/quality tradeoff.
