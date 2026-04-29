# Router Cost Analysis (§13.6)


| Run | Total $ | $/walk | LLM calls | Prompt / Completion tok | Median latency (s) | Median turns | Verified | Walks rendered | Median citations | Median walk dist (m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **router-bench-paid-kimi** | 0.3038 | 0.0304 | 53 | 136,596 / 55,118 | 118.97 | 6.0 | 70% | 70% | 2.0 | 2684.5 |
| **router-bench-free-gptoss** | 0.0000 | 0.0000 | 38 | 60,879 / 6,205 | 29.81 | 3 | 80% | 80% | 3.0 | 946.9 |

## Per-run details

### router-bench-paid-kimi

- File: `docs/eval/results/router-bench-paid-kimi-2026-04-29T00-36-11Z.jsonl`
- Started: 2026-04-29T00-36-11Z → 2026-04-29T01-00-08Z
- Total LLM cost: **$0.3038**
- LLM calls: 53
- Tokens: 136,596 prompt + 55,118 completion
- Stats: {"n": 10, "verified_rate": 0.7, "walk_rate": 0.7, "citation_rate": 0.7, "median_latency_s": 118.97, "median_server_duration_s": 118.96, "median_turns": 6.0, "median_citations_per_walk": 2.0, "median_walk_distance_m": 2684.5}
- Models: ['moonshotai/kimi-k2.6-20260420']

Per-question outcomes:

  1. *Tell me about the Cathedral of Saint John the Divine.* — ✅ verified, 5 citations, 5 stops, latency 162.146s
  2. *What is Grant's Tomb and why is it in this neighborhood?* — ✅ verified, 1 citations, 1 stops, latency 116.29s — `response does not contain a JSON object`
  3. *Plan a walking tour of three Columbia University landmarks.* — ✅ verified, 3 citations, 3 stops, latency 334.077s — `response does not contain a JSON object`
  4. *Describe the architecture of Riverside Church.* — ✅ verified, 1 citations, 1 stops, latency 93.419s
  5. *What can I see if I walk from Low Plaza to Morningside Park?* — ✅ verified, 5 citations, 5 stops, latency 91.73s — `citation #0: doc_id 'osm:way:1449668147' was not retrieved on or before turn 1`
  6. *Show me art-history landmarks in Morningside Heights.* — ✅ verified, 7 citations, 7 stops, latency 170.978s — `response does not contain a JSON object`
  7. *What's the history of the Apollo Theater? (note: out of v1 scope)* — ⚠️ unverified, 0 citations, 0 stops, latency 121.643s — `citation verification failed: response does not contain a JSON object`
  8. *Plan a 45-minute walk that hits a park, a church, and a university building.* — ⚠️ unverified, 0 citations, 0 stops, latency 133.734s — `citation verification failed: response does not contain a JSON object`
  9. *What are some lesser-known places in the Upper West Side worth a visit?* — ✅ verified, 3 citations, 3 stops, latency 49.095s
  10. *Tell me about the buildings around 116th and Broadway.* — ⚠️ unverified, 0 citations, 0 stops, latency 101.031s — `citation verification failed: response does not contain a JSON object`

### router-bench-free-gptoss

- File: `docs/eval/results/router-bench-free-gptoss-2026-04-29T01-00-52Z.jsonl`
- Started: 2026-04-29T01-00-52Z → 2026-04-29T01-06-18Z
- Total LLM cost: **$0.0000**
- LLM calls: 38
- Tokens: 60,879 prompt + 6,205 completion
- Stats: {"n": 10, "verified_rate": 0.8, "walk_rate": 0.8, "citation_rate": 0.8, "median_latency_s": 29.81, "median_server_duration_s": 31.48, "median_turns": 3, "median_citations_per_walk": 3.0, "median_walk_distance_m": 946.9}
- Models: ['openai/gpt-oss-120b:free']

Per-question outcomes:

  1. *Tell me about the Cathedral of Saint John the Divine.* — ❌ no terminal, 0 citations, 0 stops, latency 28.142s — `response does not contain a JSON object`
  2. *What is Grant's Tomb and why is it in this neighborhood?* — ✅ verified, 3 citations, 3 stops, latency 24.21s
  3. *Plan a walking tour of three Columbia University landmarks.* — ✅ verified, 3 citations, 3 stops, latency 54.307s — `response does not contain a JSON object`
  4. *Describe the architecture of Riverside Church.* — ✅ verified, 1 citations, 1 stops, latency 31.488s
  5. *What can I see if I walk from Low Plaza to Morningside Park?* — ✅ verified, 4 citations, 4 stops, latency 32.886s
  6. *Show me art-history landmarks in Morningside Heights.* — ✅ verified, 4 citations, 4 stops, latency 38.675s
  7. *What's the history of the Apollo Theater? (note: out of v1 scope)* — ⚠️ unverified, 0 citations, 0 stops, latency 9.057s — `citation verification failed: response does not contain a JSON object`
  8. *Plan a 45-minute walk that hits a park, a church, and a university building.* — ✅ verified, 3 citations, 3 stops, latency 25.331s
  9. *What are some lesser-known places in the Upper West Side worth a visit?* — ✅ verified, 5 citations, 5 stops, latency 21.793s
  10. *Tell me about the buildings around 116th and Broadway.* — ✅ verified, 5 citations, 5 stops, latency 37.046s

