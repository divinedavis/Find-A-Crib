# Find A Crib: which model reads flyers and writes Help me apply (2026-11-12)

14 live flyers from findacrib.com/featured.json with a text layer. Answer key for flyers: Claude Opus 5.5 reading the same text (14 usable). Every model through Vercel AI Gateway, same prompt as production. Total spend $3.21.

## Flyer reader (text)

| Model | Unit rows (F1) | After grounding filter | Deadline | First-come | Answered | Cost / 1,000 | p50 s |
|---|---|---|---|---|---|---|---|
| anthropic/claude-haiku-4.5 | 18% | 18% | 100% | 100% | 14/14 | $4.65 | 2.6 |
| anthropic/claude-haiku-5.5 | 88% | 88% | 100% | 100% | 14/14 | $0.95 | 4.6 |
| thinkingmachines/inkling-2-small (open) | 92% | 92% | 100% | 100% | 14/14 | $3.56 | 7.9 |
| moonshotai/kimi-k3.1-pro (open) | 100% | 100% | 100% | 100% | 14/14 | $22.11 | 6.1 |
| deepseek/deepseek-v4.1-flash (open) | 90% | 90% | 100% | 100% | 14/14 | $4.31 | 5.4 |
| zai/glm-5.3-flash (open) | 73% | 73% | 100% | 100% | 14/14 | $0.94 | 20.4 |
| alibaba/qwen3.8-flash (open) | 69% | 69% | 100% | 79% | 12/14 | $2.38 | 50.9 |
| openai/gpt-oss-120b (open) | 69% | 69% | 100% | 100% | 14/14 | $0.83 | 6.2 |

## Scanned flyer (page images only)

| Model | Unit rows (F1) | Deadline | First-come | Answered | Cost / 1,000 | p50 s |
|---|---|---|---|---|---|---|
| anthropic/claude-haiku-4.5 | 33% | 93% | 100% | 14/14 | $5.37 | 3.8 |
| anthropic/claude-haiku-5.5 | 93% | 100% | 100% | 14/14 | $0.96 | 4.4 |
| thinkingmachines/inkling-2-small (open) | 93% | 100% | 93% | 13/14 | $3.52 | 4.5 |
| moonshotai/kimi-k3.1-pro (open) | 95% | 100% | 100% | 14/14 | $25.31 | 7.0 |
| deepseek/deepseek-v4.1-flash (open) | 69% | 93% | 100% | 14/14 | $3.59 | 3.5 |
| zai/glm-5.3-flash (open) | 89% | 100% | 100% | 14/14 | $1.36 | 9.4 |
| mistral/mistral-small (open) | 63% | 100% | 100% | 14/14 | $0.90 | 3.6 |
| minimax/minimax-m3.1-flash (open) | 14% | 100% | 64% | 9/14 | $3.96 | 10.4 |
| google/gemini-3-flash | 93% | 100% | 93% | 13/14 | $14.38 | 11.3 |

## Help me apply

| Model | Opus grade (1-10) | Refused by app | Answered | Cost / 1,000 | p50 s |
|---|---|---|---|---|---|
| anthropic/claude-haiku-4.5 | 5.4 | 0 | 14/14 | $4.55 | 4.4 |
| anthropic/claude-haiku-5.5 | 8.6 | 0 | 14/14 | $1.13 | 7.7 |
| thinkingmachines/inkling-2-small (open) | 2.8 | 0 | 12/14 | $3.73 | 12.1 |
| moonshotai/kimi-k3.1-pro (open) | 8.8 | 0 | 14/14 | $40.84 | 20.6 |
| deepseek/deepseek-v4.1-flash (open) | 8.0 | 0 | 14/14 | $4.37 | 7.1 |
| zai/glm-5.3-flash (open) | 7.3 | 0 | 14/14 | $0.95 | 12.3 |
| alibaba/qwen3.8-flash (open) | 7.5 | 0 | 14/14 | $2.73 | 81.1 |
| openai/gpt-oss-120b (open) | 4.7 | 0 | 14/14 | $0.76 | 5.1 |

Failures: minimax/minimax-m3.1-flash: empty reply ×5; alibaba/qwen3.8-flash:  ×2; thinkingmachines/inkling-2-small:  ×2; thinkingmachines/inkling-2-small: empty reply ×1; google/gemini-3-flash:  ×1
