# AECV-Bench object counting: frontier models vs PlanSight

Exact-match accuracy. Split A (60 plans) tuned PlanSight's counting rules; **split B (60 plans) was never tuned on**. Frontier answers and costs are the published AECV-Bench results.

**Leakage audit** (`scripts/aecv_leakage.py`, dHash): 33 of 120 AECV plans are CubiCasa5K images, and 20 of them are in our detector's training split. The *clean* tables drop those plans for every system; they are the honest numbers for PlanSight.

## Split B clean (51 plans)

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| gemini_35_flash | 45% | 43% | 88% | 96% | 68% | $0.03140 |
| gemini_3_pro_preview | 47% | 35% | 92% | 94% | 67% | n/a |
| claude_fable_5 | 43% | 37% | 90% | 96% | 67% | $0.07686 |
| claude_opus_48 | 20% | 24% | 82% | 96% | 55% | $0.01943 |
| openai_gpt_55 | 37% | 35% | 86% | 94% | 63% | $0.22398 |
| qwen_37_plus | 14% | 16% | 90% | 92% | 53% | $0.00102 |
| gemma_4_31b_it | 20% | 16% | 84% | 88% | 52% | $0.00014 |
| nvidia_nemotron_3_nano_omni_30b | 2% | 2% | 4% | 6% | 3% | $0.00000 |
| nemotron_3.5_super_vl (v0-1536, self-hosted) | 16% | 8% | 61% | 86% | 43% | $0.00019 |
| PlanSight detector only (zero-shot) | 39% | 33% | 57% | n/a | 43% | $0.00006 |
| **PlanSight hybrid** | 39% | 41% | 80% | 88% | 62% | $0.00050 |

## Split B (60 plans)

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| gemini_35_flash | 43% | 38% | 85% | 93% | 65% | $0.03140 |
| gemini_3_pro_preview | 47% | 32% | 90% | 92% | 65% | n/a |
| claude_fable_5 | 42% | 33% | 87% | 93% | 64% | $0.07686 |
| claude_opus_48 | 18% | 22% | 77% | 90% | 52% | $0.01943 |
| openai_gpt_55 | 35% | 32% | 78% | 92% | 59% | $0.22398 |
| qwen_37_plus | 12% | 15% | 82% | 87% | 49% | $0.00102 |
| gemma_4_31b_it | 17% | 15% | 78% | 82% | 48% | $0.00014 |
| nvidia_nemotron_3_nano_omni_30b | 2% | 2% | 3% | 7% | 3% | $0.00000 |
| nemotron_3.5_super_vl (v0-1536, self-hosted) | 13% | 7% | 55% | 82% | 39% | $0.00019 |
| PlanSight detector only (zero-shot) | 43% | 33% | 62% | n/a | 46% | $0.00006 |
| **PlanSight hybrid** | 43% | 38% | 80% | 85% | 62% | $0.00050 |

## Split A (60 plans)

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| gemini_35_flash | 43% | 40% | 78% | 93% | 64% | $0.03140 |
| gemini_3_pro_preview | 33% | 37% | 77% | 88% | 59% | n/a |
| claude_fable_5 | 30% | 25% | 78% | 93% | 57% | $0.07686 |
| claude_opus_48 | 12% | 8% | 77% | 87% | 46% | $0.01943 |
| openai_gpt_55 | 25% | 25% | 75% | 93% | 55% | $0.22398 |
| qwen_37_plus | 20% | 13% | 87% | 92% | 53% | $0.00102 |
| gemma_4_31b_it | 27% | 12% | 77% | 78% | 48% | $0.00014 |
| nvidia_nemotron_3_nano_omni_30b | 0% | 0% | 5% | 7% | 3% | $0.00000 |
| nemotron_3.5_super_vl (v0-1536, self-hosted) | 10% | 10% | 57% | 82% | 40% | $0.00019 |
| PlanSight detector only (zero-shot) | 33% | 32% | 72% | n/a | 46% | $0.00006 |
| **PlanSight hybrid** | 33% | 38% | 87% | 90% | 62% | $0.00050 |

## Split all clean (100 plans)

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| gemini_35_flash | 46% | 43% | 89% | 94% | 68% | $0.03140 |
| gemini_3_pro_preview | 41% | 37% | 90% | 92% | 65% | n/a |
| claude_fable_5 | 38% | 33% | 89% | 94% | 64% | $0.07686 |
| claude_opus_48 | 16% | 16% | 84% | 94% | 52% | $0.01943 |
| openai_gpt_55 | 33% | 30% | 87% | 93% | 61% | $0.22398 |
| qwen_37_plus | 18% | 14% | 91% | 93% | 54% | $0.00102 |
| gemma_4_31b_it | 24% | 14% | 85% | 89% | 53% | $0.00014 |
| nvidia_nemotron_3_nano_omni_30b | 1% | 1% | 5% | 7% | 4% | $0.00000 |
| nemotron_3.5_super_vl (v0-1536, self-hosted) | 13% | 10% | 61% | 89% | 43% | $0.00019 |
| PlanSight detector only (zero-shot) | 31% | 31% | 61% | n/a | 41% | $0.00006 |
| **PlanSight hybrid** | 31% | 41% | 84% | 91% | 62% | $0.00050 |

## Split all (120 plans)

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| gemini_35_flash | 43% | 39% | 82% | 93% | 64% | $0.03140 |
| gemini_3_pro_preview | 40% | 34% | 83% | 90% | 62% | n/a |
| claude_fable_5 | 36% | 29% | 82% | 93% | 60% | $0.07686 |
| claude_opus_48 | 15% | 15% | 77% | 88% | 49% | $0.01943 |
| openai_gpt_55 | 30% | 28% | 77% | 92% | 57% | $0.22398 |
| qwen_37_plus | 16% | 14% | 84% | 89% | 51% | $0.00102 |
| gemma_4_31b_it | 22% | 13% | 78% | 80% | 48% | $0.00014 |
| nvidia_nemotron_3_nano_omni_30b | 1% | 1% | 4% | 7% | 3% | $0.00000 |
| nemotron_3.5_super_vl (v0-1536, self-hosted) | 12% | 8% | 56% | 82% | 39% | $0.00019 |
| PlanSight detector only (zero-shot) | 38% | 32% | 67% | n/a | 46% | $0.00006 |
| **PlanSight hybrid** | 38% | 38% | 83% | 88% | 62% | $0.00050 |
