# Gametriome Bridge: Midnight -> Leaderboard SOTA

Date: 2026-04-10
Owner lane: `neural/test_lab/PR_sidelane_8x_linked`
Trainer: `neural/experiments/Longworm/train_longworm.py`

## Goal
Bridge from the strong `Midnight 12L` no-trick baseline into the current leaderboard architecture cluster, without custom tokenizer/vocab tricks and without n-gram eval mixing.

## Why This Exists
- Midnight (seed 444, 8xH100) still anchors your best clean neural line:
  - `final_quant_roundtrip_exact val_bpb: 1.14282742`
  - `final_sliding_window_exact val_bpb: 1.10567949`
- Latest PR traffic shifted toward a repeated motif:
  - Depth recurrence style loops
  - Parallel residual style skip mixing
  - Pre-quant legal TTT

This bridge pack isolates those motifs into controlled Longworm arms so you can see which part actually moves your no-trick score.

## Bridge Mapping
- Leaderboard motif: depth recurrence
  - Bridge knob: `TRANSITION_INTEGRATOR=hybrid_k2_k4`, `TRANSITION_HYBRID_LAST_N=*`
- Leaderboard motif: parallel residuals
  - Bridge knob: `RESID_MIX_X0_INIT>0`
- Leaderboard motif: pre-quant TTT
  - Bridge knobs: `TTT_ENABLED=1`, `TTT_*`, optional adaptive gate
- Keep clean lane:
  - `NGRAM_EVAL_ORDER=0`
  - tokenizer/vocab unchanged (`SP1024`)

## Arms
See `ablation_matrix.tsv` and arm files:
- `44_v1_10_bridge_control_midnight_anchor_l11_d512_h8_kv4_non_ngram_brotli`
- `45_v1_10_bridge_recur_parallel_l10_d480_h12_kv4_non_ngram_brotli`
- `46_v1_10_bridge_prequant_ttt_l10_d480_h12_kv4_non_ngram_brotli`
- `47_v1_10_bridge_full_stack_l10_d480_h12_kv4_non_ngram_brotli`

## Run
From `.../neural`:

```bash
TOKENIZER_PATH=/home/frosty40/parameter-golf-lab/data/tokenizers/fineweb_1024_bpe.model DATA_PATH=/home/frosty40/parameter-golf-lab/data/datasets/fineweb10B_sp1024 NPROC_PER_NODE=8 bash test_lab/PR_sidelane_8x_linked/run_gametriome_bridge.sh
```

Single-arm:

```bash
ARM_ONLY=47_v1_10_bridge_full_stack_l10_d480_h12_kv4_non_ngram_brotli TOKENIZER_PATH=/home/frosty40/parameter-golf-lab/data/tokenizers/fineweb_1024_bpe.model DATA_PATH=/home/frosty40/parameter-golf-lab/data/datasets/fineweb10B_sp1024 NPROC_PER_NODE=8 bash test_lab/PR_sidelane_8x_linked/run_gametriome_bridge.sh
```

