# Architecture/Test Surface Index

This is the public-facing index. Internal project nicknames are intentionally omitted here; they are local search labels, not reviewer-facing evidence.

Public-safe count: 30+ architecture/test families.

Internal recovery count: 43 local family or lane rows, grouped below by technical surface.

| # | Public technical surface | Evidence class | What this proves |
|---:|---|---|---|
| 1 | Recursive weight-sharing transformer compression | model architecture | Shared blocks were tested as a way to trade stored parameters for effective depth and wider MLP capacity. |
| 2 | Shared-block crawler stacks | model architecture | Recurrent crawler blocks, flat+crawler hybrids, and loop scheduling were tested as distinct model-body families. |
| 3 | Cubric n-gram mixing | compression / eval mechanism | N-gram tables, adaptive multipliers, entropy bins, and complementary model/ngram training were explored as a separate compression/eval line. |
| 4 | Legal n-gram frontier mixing | compression / eval mechanism | Frontier-style n-gram integration was tested separately from pure neural model-body changes. |
| 5 | Entropy-shifted n-gram order weighting | compression / eval mechanism | Per-order entropy shifts and fixed order multipliers were isolated as their own family of scoring mechanisms. |
| 6 | Binary and ternary quantized U-Net transformers | quantized model architecture | Extreme low-bit model-body variants were tested, not just post-hoc packaging. |
| 7 | 11-layer GQA U-Net bodies | neural model architecture | A compact GQA/U-Net transformer base was developed across attention, MLP, skip, RoPE, and value-embedding choices. |
| 8 | 12-layer GQA mixed-bit towers | neural model architecture | Larger GQA towers were tested with mixed-bit compression and benchmarked under the 16 MB cap. |
| 9 | Looped tokenizer-body variants | neural model architecture | Loop placement, loop count, tokenizer size, and late-loop enable timing were varied as a family of neural bodies. |
| 10 | 10k-vocabulary CaseOps loop bodies | neural model architecture | A lossless-caps 10k tokenizer and looped GQA body were brought into the final campaign window and tested on 8xH100. |
| 11 | Loop + TTT score-first packaging | training / evaluation method | Test-time training was treated as a systematic packaging/eval family, not a one-off metric trick. |
| 12 | Instructed recurrence for crawler loops | model architecture | Content-derived and flow-derived loop instructions were tested to make repeated shared blocks behave differently across iterations. |
| 13 | Gated DeltaNet memory hybrids | state-space / recurrence mechanism | Gated delta memory was tested both as a crawler component and as a hybrid attention/state-space body. |
| 14 | Long-context causal tap mechanisms | long-context model architecture | Multi-scale causal taps, RK-style transition integrators, and adaptive long-context TTT variants were tested. |
| 15 | Bridge models between long-context and leaderboard bodies | model architecture | Long-context mechanisms were connected back to practical leaderboard-style body constraints. |
| 16 | Split-head crawler scale gates | ablation family | Split-head crawler ideas were scaled and rejected or retained based on measured gates. |
| 17 | Hybrid attention plus state-space bodies | model architecture | Bodies combining standard attention layers with state-space/GatedDelta layers were tested directly. |
| 18 | Crawler-only export bodies | model architecture / export path | CPU-heavy paths, phrase caches, and regime trackers were removed to test lean crawler export variants. |
| 19 | Crawler-safe train/eval surfaces | validation family | Safe crawler training and eval rows were tracked separately from invalid or reference-only readings. |
| 20 | Multi-crawler descendants | model architecture | Multi-crawler topologies, loop-aware GPTQ, and size-trim variants were tested as a separate branch. |
| 21 | Trace and flow-capture wrappers | instrumentation | Trace wrappers preserved model semantics while exposing flow/state information for inspection. |
| 22 | Teacher/student EMA integration | training method | EMA teacher/student loops and legal n-gram integration were isolated as a training-family test. |
| 23 | A/B quality harnesses | validation family | Dedicated harnesses compared candidate bodies and quality-preserving variants under controlled settings. |
| 24 | Triton/model co-design lanes | kernel/model co-design | Triton activation, loader, and model-body changes were tested as coupled engineering work. |
| 25 | Autoregressive self-generated GPTQ calibration | quantization method | Calibration data generation and GPTQ behavior were tested as their own compression family. |
| 26 | Mixed-int artifact packaging | quantization method | Mixed int5/int6/int7/int8 policies were tested across embeddings, matrices, MLP banks, QKV, and attention projections. |
| 27 | Brotli and byte-shuffle artifact packaging | compression method | Artifact-level compression choices were benchmarked as part of the submission surface. |
| 28 | Sliding-window and roundtrip eval checks | validation family | Metric validity was separated between full precision, decompressed artifacts, sliding windows, and roundtrip checks. |
| 29 | Custom attention-kernel bodies | kernel/model co-design | Model shapes were paired with custom FA3-comparable attention-kernel benchmarking. |
| 30 | Staged attention-kernel tile sweeps | kernel-performance family | Primary/fallback kernels, tile shapes, register limits, and GPU lane splits were measured directly. |
| 31 | Fused recurrence megakernel work | kernel-performance family | Triton fused recurrence kernels, packed projection experiments, and recovery ledgers were tracked as a separate performance campaign. |
| 32 | Final submission packaging lane | submission engineering | A final candidate was packaged and evaluated under the cap without treating that label as the campaign's main achievement. |

The point of this sheet is the breadth of technical surfaces, not the internal names attached to them during development.
