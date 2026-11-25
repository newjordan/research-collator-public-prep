"""Classifier precedence and commit-message metric parsing."""

from __future__ import annotations

import classify
import enrich
import stripper


def test_strong_experimental_keyword_beats_legs_path() -> None:
    camp, rule = classify.classify({
        "abs_path": "/data/SOTA_FINAL/legs/ouroboros/train.log",
        "title": "train",
        "summary": "",
        "source_label": "SOTA_FINAL",
    })
    assert camp == "experimental"
    assert rule.startswith("kw_strong_exp:")


def test_legs_path_is_neural_without_experimental_family() -> None:
    camp, rule = classify.classify({
        "abs_path": "/data/SOTA_FINAL/legs/2026-04-15_probe/run.log",
        "title": "probe",
        "summary": "training log",
        "source_label": "SOTA_FINAL",
    })
    assert (camp, rule) == ("neural", "path_legs")


def test_competitive_source_beats_weak_hypothesis_keyword() -> None:
    camp, rule = classify.classify({
        "abs_path": "/data/SOTA_FINAL/notes/plan.md",
        "title": "Hypothesis: try a wider mlp",
        "summary": "ablation idea",
        "source_label": "SOTA_FINAL",
    })
    assert camp == "neural"
    assert rule == "competitive_source:SOTA_FINAL"


def test_codex_rollouts_stay_daily_grind() -> None:
    camp, rule = classify.classify({
        "abs_path": "/memories/rollout.md",
        "title": "ouroboros session",
        "summary": "crawler work",
        "source_label": "codex_rollouts",
    })
    assert (camp, rule) == ("daily_grind", "source_codex_rollouts")


def test_submission_path_is_neural() -> None:
    camp, rule = classify.classify({
        "abs_path": "/lab/submissions/track_a/submission.json",
        "title": "submission",
        "summary": "",
        "source_label": "parameter-golf-lab",
    })
    assert (camp, rule) == ("neural", "path_submission")


def test_commit_message_prefers_explicit_val_bpb_and_drops_noise() -> None:
    metrics = enrich.metrics_from_commit_message(
        "val_bpb=1.1020\nalso saw 1.3000 BPB\nnoise 0.0100 BPB\nval_loss: 2.5000"
    )
    assert metrics["val_bpb"] == 1.1020
    assert metrics["val_bpb_source"] == "commit_message"
    assert "val_bpb_delta" not in metrics
    assert metrics["val_loss"] == 2.5


def test_commit_message_delta_context_is_not_the_absolute_score() -> None:
    metrics = enrich.metrics_from_commit_message(
        "regression costing 0.1400 BPB after the kernel change"
    )
    assert "val_bpb" not in metrics
    assert metrics["val_bpb_delta"] == 0.14


def test_commit_message_keeps_unqualified_absolute_bpb() -> None:
    metrics = enrich.metrics_from_commit_message("measured 1.2345 BPB on the held-out set")
    assert metrics["val_bpb"] == 1.2345
    assert metrics["val_bpb_source"] == "commit_message"


def test_gpu_inference_rules() -> None:
    assert stripper._infer_gpu_type("runpod", None) == "H100"
    assert stripper._infer_gpu_type("local", None) == "GB10"
    assert stripper._infer_gpu_type(None, 1) == "GB10"
    assert stripper._infer_gpu_type(None, 4) == "H100"
    assert stripper._infer_gpu_type(None, None) is None
