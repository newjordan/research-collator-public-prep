# Internal Architecture/Test Family Recovery Sheet

This is an internal recovery index. It intentionally keeps local search labels so evidence can be found again, but those labels are not reviewer-facing language and should not be included in the final report.

Public-facing sanitized sheet: `ARCHITECTURE_TEST_SURFACE_PUBLIC.md`.

Current public-safe count: 30+ architecture/test families.

Current raw row count in this sheet: 43 named family or lane rows.

Counting rule:

- Count a row when there is a named family/lane plus a local evidence path.
- Do not count every seed, PR, knob sweep, log, or one-off launch as its own family.
- Keep wrappers, kernels, and validation/test families visible, but label them as such.
- Prefer conservative public wording: "30+ named architecture/test families catalogued."

| # | Family or lane | Type | Aliases / variants | Evidence anchor | Notes |
|---:|---|---|---|---|---|
| 1 | A-Wing | n-gram / mixer family | AWING, A-WING RED/GREEN/PURPLE | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-03-26_AWING_RED_G_gpu_monster_mixer_8xH100/README.md` | Legal n-gram/frontier stack and GPU mixer branches. |
| 2 | AR Self-Gen GPTQ | compression/eval family | ValCalib GPTQ | `/home/frosty40/sota_crawler/records/track_10min_16mb/2026-03-25_ValCalib_GPTQ_XSA_BigramHash3072/submission.json` | Autoregressive self-generated calibration for GPTQ/XSA/BigramHash. |
| 3 | B-Wing | n-gram family | BWING, B-WING FullPort | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-03-26_BWING_FullPort_entropy_shift_fixedmults_8xH100/submission.json` | X-Wing-derived per-order entropy shift and fixed multiplier line. |
| 4 | Bandit | crawler + n-gram family | Bandit ClownCar X CubricNgram9 | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-03-29_Bandit_ClownCar_X_CubricNgram9_8xH100/README.md` | ClownCar crawler mixed with X-Wing n-gram oracle. |
| 5 | Bandit Wagon | crawler family | BW, BWX, BW5, BW9, BWX 9F | `/home/frosty40/sota_nueral/CORPUS_CRAWLER.md` | Flat+crawler production line with many depth/width/tap-off variants. |
| 6 | Binary / Ternary U-Net | quantized model family | Binary Asymmetric U-Net, Ternary U-Net | `/home/frosty40/parameter-golf-lab/records/track_non_record_16mb/2026-03-24_106M_Binary_Asymmetric_UNet_1bit_8xH100/submission_binary.json` | Quantized U-Net transformer variants, including binary and ternary branches. |
| 7 | ClownCar | crawler family | ClownCar Crawler | `data/architecture_recipes.json` | Existing curated recipe row; Frugendorff-descended crawler body. |
| 8 | Cobra | ablation/test family | Cobra A/B, Cobra base quality | `/home/frosty40/parameter-golf-lab/junkyard/experiments/Cobra/README.md` | Dedicated A/B harness and candidate set. |
| 9 | DeltaNet Crawler | mechanism family | FLA DeltaNet, GDN, FX-Wing Delta DN | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-03-27_Medusa_FLA_DeltaNet_NaiveInt6_8xH100/submission.json` | Gated Delta Rule / DeltaNet memory branch used inside crawler experiments. |
| 10 | Donnie | neural body family | Donnie, Donnie_TTT, Donnie_12L | `/home/frosty40/sota_rascal/RESEARCH_REPORT_2026-04-27.md` | Loop+TTT body derived from Raphe/Mikey repair work. |
| 11 | F-Wing | crawler family | F_Wing Green/Purple/Red | `/home/frosty40/parameter-golf-lab/junkyard/experiments/F_Wing/Red/run.sh` | CrawlerGPT/Frugendorff crawler family before FX-Wing instruction work. |
| 12 | FA-Wing | hybrid crawler/n-gram family | FA-Wing Green, FA-Wing GreenDN | `/home/frosty40/parameter-golf-lab/junkyard/experiments/FA_Wing_Green_1/run.sh` | Flow-instruction variants on A-Wing/Frugendorff bases. |
| 13 | Frugendorff | recursive transformer family | The Frugendorff, H-FRUG, Frugendorff Squared | `/home/frosty40/sota_nueral/CORPUS_CRAWLER.md` | Original recursive weight-sharing transformer line; later crawler ancestor. |
| 14 | FX-Wing | instructed recurrence family | FX_Wing, FX_Wing_Delta, FX_Wing_Sigma | `/home/frosty40/parameter-golf-lab/junkyard/experiments/archive/deprecated/FX_Wing/HYPOTHESIS.md` | Content/flow instructions for shared crawler loop recurrence. |
| 15 | Gametriome | bridge model family | Gametriome Bridge | `/home/frosty40/parameter-golf-lab/neural/experiments/2026-04-10_Gametriome_Bridge/README.md` | Long-context/bridge lane tied to Midnight and later leaderboard motifs. |
| 16 | GreenRod | hybrid model family | GreenRod_X_1 | `/home/frosty40/parameter-golf-lab/junkyard/experiments/GreenRod_X_1/run.sh` | Hybrid GatedDeltaNet plus standard attention body with Rat Rod/X-Wing stack. |
| 17 | Helix | crawler/model family | Helix SplitHead, Helix_ab_3 | `/home/frosty40/sota_nueral/CORPUS_CRAWLER.md` | Split-head concept and scale gate family. |
| 18 | Junkyard Rat | model/kernel family | JR-01, JR-02, Junkyard_Rat_MLP | `/home/frosty40/parameter-golf-lab/junkyard/experiments/Junkyard_Rat_MLP/JR-01_racer/HYPOTHESIS.md` | Rat Rod base plus Triton/loader garage line. |
| 19 | Longworm | long-context family | Longworm RK, Longworm v1.5/v1.9 | `/home/frosty40/parameter-golf-lab/neural/test_lab/PR_sidelane_8x_linked/LONGWORM_V1_5_CONTEXT_MECH_WRITEUP.md` | Multi-scale causal taps, RK-style transition work, adaptive TTT experiments. |
| 20 | Lucky | neural body family | Lucky II, Lucky III, Lucky IV, Lucky V | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-04-02_Lucky_8xH100/README.md` | Named neural experiment family with multiple local variants. |
| 21 | Medusa | neural/crawler family | Medusa FLA DeltaNet | `data/architecture_recipes.json` | Existing curated recipe row; overlaps with DeltaNet evidence but kept as named family. |
| 22 | Mikey | neural body family | Mikey, Mikey II, Mikey III, Mikey v5, SP10240 Mikey | `/home/frosty40/sota_rascal/ACTIVE_DECISION_2026-04-29.md` | Clean loop-tokenizer family and later 10k-vocab SP10240 lane. |
| 23 | Midnight | neural body family | Midnight III, Midnight 12L, Midnight Rider/Special/Magnum/Express | `data/architecture_recipes.json` | Existing curated recipe row; later anchor and compression lanes. |
| 24 | Mockingbird | neural body/submission family | SP10240 CaseOps, Mockingbird 8xH100 | `data/architecture_recipes.json` | Existing curated recipe row; 10k-vocab CaseOps family, not the whole campaign capstone. |
| 25 | Moonshot | recurrence model family | RWKV Moonshot, TON-E Moonshot | `/home/frosty40/SOTA_FINAL/scripts/run_moonshot_8k.sh` | Crawler variant replacing attention in crawler blocks with RWKV-style recurrence. |
| 26 | Nightcrawler | crawler family | Shroud Nightcrawler, Nightcrawler base | `data/architecture_recipes.json` | Existing curated recipe row; crawler body with later descendants. |
| 27 | Nightcrawler Cubed | crawler descendant | NC3, Nightcrawler-Cubed sink/fused | `/home/frosty40/parameter-golf-lab/nightcrawler_cubed/README.md` | 7F+3C topology with staged crawler ramp and fused/sink variants. |
| 28 | Ouroboros | recurrence/crawler family | Ouroboros III, ouroboros_4k | `data/architecture_recipes.json` | Existing curated recipe row; recurrence line with later 4k references. |
| 29 | Podracer | eval/compression family | Podracing, Podracing II, Podracer III Cubric Lite | `/home/frosty40/sota_rascal/RESEARCH_REPORT_2026-04-27.md` | Podracing introduced n-gram blending and activation/eval changes. |
| 30 | Raphe | neural body family | Raphe, Raphe 1.1, Raphe_TTT | `/home/frosty40/sota_rascal/AUDIT_Mikey_Raphe_2026-04-27.md` | Clean neural body line tied to Mikey/Donnie audit and repair work. |
| 31 | Rascal | neural body family | Rascal II, Rascal III, Rascal IV | `data/architecture_recipes.json` | Existing curated recipe row; Junkyard Rat/Rascal body line. |
| 32 | Rascal SLOT | neural ablation family | SLOT, Rascal III SLOT | `/home/frosty40/sota_rascal/RESEARCH_REPORT_2026-04-27.md` | Signal-positive but byte-budget-failing branch. |
| 33 | Rat Rod | neural body family | Rat Rod Green v1-v7, Purple, Synapse, Siphon | `/home/frosty40/parameter-golf-lab/junkyard/experiments/Rat_Rod/PROGRESS.md` | Strong 11L/512d Parallel Muon/XSA/BigramHash body family. |
| 34 | Shroud | trace/visualization wrapper | Shroud Nightcrawler, Shroud Midnight 12L, LoopViz | `/home/frosty40/parameter-golf-lab/experiments/shroud_nightcrawler/run_spark.sh` | Trace/flow-capture lane preserving Nightcrawler/Midnight semantics. |
| 35 | Smokestack | crawler family | Smokestack | `/home/frosty40/parameter-golf-lab/crawler/smokestack/hypothesis.md` | Named crawler lane with run/gate/ablation files. |
| 36 | SOTA Crawler | crawler family | SOTA_CRAWLER_SAFE | `data/architecture_recipes.json` | Existing curated recipe row; safe crawler production/test lane. |
| 37 | SOTA v2 TTT | TTT/test family | Exp-D TTT8, FarnsworthEngine v1/v2 | `/home/frosty40/parameter-golf-lab/junkyard/experiments/archive/pod_configs/main_pod/logs/` | TTT-only and TTT8 stride32 test family. |
| 38 | Staged Hybrid Bench | kernel/performance family | staged primary/fallback, hybridA/hybridB | `data/architecture_recipes.json` | Existing curated recipe row for staged kernel benchmark variants. |
| 39 | Tornado | teacher/student family | Tornado grid, EMA teacher/student | `/home/frosty40/parameter-golf-lab/junkyard/experiments/tornado/run.sh` | EMA teacher/student and legal n-gram integration test lane. |
| 40 | Trapper Keeper | crawler family | Nightcrawler Cubed, TK1, 7F+3C/8F+3C | `/home/frosty40/parameter-golf-lab/crawler/2026-04-09_Trapper_Keeper_1/hypothesis.md` | Multi-crawler Nightcrawler descendant with size-trim and loop-aware GPTQ work. |
| 41 | VortexHelix / Megahelix | kernel/model family | Vortex, Megahelix megakernel | `/home/frosty40/sota_crawler/recovery/megahelix/MEGAHELIX_RESEARCH_ASSESSMENT.md` | Fused Triton megakernel line and recovered Megahelix campaign. |
| 42 | Whale | neural body/kernel family | Whale donor, Whale kernel | `data/architecture_recipes.json` | Existing curated recipe row for model body plus custom attention-kernel shape. |
| 43 | X-Wing | n-gram/cubric family | XWING, X-WING Yellow II/III, Cubric3D | `/home/frosty40/parameter-golf-lab/records/track_10min_16mb/2026-03-26_XWING_Cubric3D_complementary_8xH100/README.md` | Shared n-gram tables, 3D Cubric adaptive multipliers, complementary training. |

Do not copy this table into public-facing prose. Use the sanitized technical groupings instead.
