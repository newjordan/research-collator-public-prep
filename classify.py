#!/usr/bin/env python3
"""Classify every artifact into exactly one of {experimental, neural, daily_grind}.

Deterministic, path + keyword + source-default rules. No LLM.

Schema additions:
    camp                TEXT NOT NULL DEFAULT ''   -- 'experimental' | 'neural' | 'daily_grind'
    classification_rule TEXT NOT NULL DEFAULT ''   -- which rule fired
    camp_override       TEXT                       -- user-supplied override (NULL = use camp)

Order of precedence (first match wins):
  0. user override (camp_override) — never auto-rewrites these
  1. source codex_rollouts → daily_grind          (these are session narrative; not tests)
  2. path: /legs/ → neural                        (SOTA_FINAL, sota_rascal racing legs)
  3. path: /crawler/, /concepts/, /ablations?/ → experimental
  4. path: submission.json or /submissions/ → neural
  5. title/summary keyword: experimental list
  6. title/summary keyword: neural list
  7. source-label default

Run:
    python3 classify.py
"""

from __future__ import annotations

import sqlite3
import sys

DB = "/home/frosty40/research_collator/index.sqlite"

# STRONG experimental keywords — always pull experimental, even in competitive sources.
# These are concrete experimental architecture/method names per user's rule:
# "if it's crawler/megakernel etc it is experimental".
STRONG_EXP_KW = (
    "crawler", "megakernel", "megahelix", "ouroboros", "helix", "clowncar",
    "jepa", "text diffusion",
)
# WEAK experimental keywords — pull experimental EXCEPT when the source is a
# known competitive lane (SOTA_FINAL / sota_rascal), where these words mean
# "competitive hypothesis-driven research" rather than "exploration".
WEAK_EXP_KW = (
    "crawl ", " crawl,", "ablation", "concept:", "concept ", "cross-repo",
    "cross-pr", "autoresearch", "research audit", "hypothesis —", "hypothesis -",
    "hypothesis:", "exploration", "shroud", "ttt_ablation", "ttt-ablation",
    "test-time training", "state-space", "rascal ii research-driven",
    "agent brief", "field report", "research focus",
    "scientific plan", "research-driven",
)
# Sources where the team-identity beats weak experimental keywords.
COMPETITIVE_SOURCES = {
    "SOTA_FINAL", "sota_rascal", "pg_whale", "rascal-private",
    "sota_rascal_pod_saves", "git:SOTA_FINAL", "git:sota_rascal",
    "git:pg_whale", "git:rascal-private",
}
# Backwards-compat alias used by old reports.
EXP_KW = STRONG_EXP_KW + WEAK_EXP_KW
NEURAL_KW = (
    "test card", "results —", "results -", "record:", "final results",
    "submission", "approvals", "winner", "champion", "leaderboard",
    "test card 01", "test card 02", "test card 03",
    "live decision", "quarantine manifest", "budget spend",
    "midnight_iii_clean", "loop2_step1500", "lqer", "qmr", "dq128", "dkdv",
    "sft", "lora", "rl ", "rlhf", " rl-", "ppo", "dpo",
)

# Source-label defaults for ambiguous artifacts that fired no other rule.
SOURCE_DEFAULT = {
    "ml-lab": "experimental",
    "srv_agents": "experimental",
    "srv_studio": "experimental",
    "srv_forge": "experimental",
    "srv_models": "experimental",
    "dotagents_mono": "experimental",
    "rig_desktop_config": "experimental",
    "local_qwen_agent": "experimental",
    "dgx_nim_upgrade": "experimental",
    "qwen_agent": "experimental",
    "augment_checkpoints": "experimental",
    "parameter-golf-lab": "experimental",
    "parameter-golf-cross-repo": "experimental",
    "sota_crawler": "experimental",
    "sota_nueral": "neural",
    "sota_nueral_archive": "neural",
    "SOTA_FINAL": "neural",
    "sota_rascal": "neural",
    "pg_whale": "neural",
    "rascal-private": "neural",
    "sota_rascal_pod_saves": "neural",
    "git:ml-lab": "experimental",
    "git:dotagents_mono": "experimental",
    "git:qwen_agent": "experimental",
    "git:parameter-golf-lab": "experimental",
    "git:sota_crawler": "experimental",
    "git:sota_nueral": "neural",
    "git:SOTA_FINAL": "neural",
    "git:sota_rascal": "neural",
    "git:pg_whale": "neural",
    "git:rascal-private": "neural",
    # codex_rollouts handled at top of classify(); never reaches default lookup.
}


def classify(rec: dict) -> tuple[str, str]:
    """Return (camp, rule_id)."""
    path = (rec.get("abs_path") or "").lower()
    title = (rec.get("title") or "").lower()
    summary = (rec.get("summary") or "").lower()
    label = rec.get("source_label") or ""

    # 1. Daily grind — codex session rollups are narrative, not tests.
    #    Source-level priority overrides any keyword rule.
    if label == "codex_rollouts":
        return ("daily_grind", "source_codex_rollouts")

    # 2. Path strong signals
    if "/legs/" in path:
        return ("neural", "path_legs")
    if "/crawler/" in path or "/crawlers/" in path:
        return ("experimental", "path_crawler")
    if "/concepts/" in path or "/concept/" in path:
        return ("experimental", "path_concepts")
    if "/ablations/" in path or "/ablation/" in path:
        return ("experimental", "path_ablations")
    if "/submissions/" in path or path.endswith("/submission.json"):
        return ("neural", "path_submission")
    if "/baseline/" in path or "/baselines/" in path:
        return ("neural", "path_baseline")
    if "/experiments/" in path or "/exploration/" in path:
        return ("experimental", "path_experiments")

    # 2. Strong experimental keywords — always pull experimental.
    text = f"{title} {summary}"
    for kw in STRONG_EXP_KW:
        if kw in text:
            return ("experimental", f"kw_strong_exp:{kw.strip()}")

    # 3. Competitive-source identity — for SOTA_FINAL / sota_rascal, source wins
    #    over weak experimental keywords ("hypothesis"/"ablation" inside competitive
    #    framing means competitive research, not exploration).
    if label in COMPETITIVE_SOURCES:
        return ("neural", f"competitive_source:{label}")

    # 4. Weak experimental keywords (lose to competitive-source identity above)
    for kw in WEAK_EXP_KW:
        if kw in text:
            return ("experimental", f"kw_weak_exp:{kw.strip()}")

    # 5. Neural keywords
    for kw in NEURAL_KW:
        if kw in text:
            return ("neural", f"kw_neu:{kw.strip()}")

    # 6. Source-label default
    default = SOURCE_DEFAULT.get(label, "experimental")
    return (default, f"default_source:{label}")


def ensure_columns(conn: sqlite3.Connection):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    if "camp" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN camp TEXT NOT NULL DEFAULT ''")
    if "classification_rule" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN classification_rule TEXT NOT NULL DEFAULT ''")
    if "camp_override" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN camp_override TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_camp ON artifacts(camp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rule ON artifacts(classification_rule)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_camp_kind ON artifacts(camp, file_kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_camp_mtime ON artifacts(camp, mtime_iso)")
    conn.commit()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    rows = list(conn.execute(
        "SELECT id, abs_path, title, summary, source_label, camp_override FROM artifacts"
    ))
    print(f"classifying {len(rows)} artifacts")

    counters = {"experimental": 0, "neural": 0, "daily_grind": 0}
    rule_counts: dict[str, int] = {}
    overrides_kept = 0

    with conn:
        for r in rows:
            if r["camp_override"]:
                final = r["camp_override"]
                rule = "manual_override"
                overrides_kept += 1
            else:
                final, rule = classify(dict(r))
            counters[final] = counters.get(final, 0) + 1
            rule_counts[rule] = rule_counts.get(rule, 0) + 1
            conn.execute(
                "UPDATE artifacts SET camp=?, classification_rule=? WHERE id=?",
                (final, rule, r["id"]),
            )

    print()
    print("=== camp counts ===")
    for k, n in sorted(counters.items()):
        print(f"  {k:14s}  {n:6d}")
    print(f"  manual_overrides kept: {overrides_kept}")
    print()
    print("=== rule frequency (top 20) ===")
    for rule, n in sorted(rule_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {n:5d}  {rule}")


if __name__ == "__main__":
    main()
