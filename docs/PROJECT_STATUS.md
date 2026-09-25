# PatchBench Project Status

Canonical current handoff. Source, tests, checked artifacts, runtime evidence,
and Git state outrank this summary if they disagree.

## V1.3 FINAL

PatchBench V1.3 is **FINAL and feature-frozen after M20**. Replication-01 is the
primary V1.3 formal result. No M21 or other V1.3 milestone remains.

```text
Study: patchbench-v1.3-formal-replication-01
Planned / terminal: 108 / 108
Canonical observations: 107
Unresolved infrastructure: 1
Blocked: 0
Remaining: 0
```

The study covers 12 frozen repository tasks, four primary capabilities, three
structural difficulty levels, three frozen Agent configurations, and three
repetitions. Agents run on the host under exact CLI admission; official
repository evaluation runs in Docker.

## Final accepted identities

| Contract or artifact | Identity |
|---|---|
| M1 design | `dc48fdac627abe9fcd95303d3042b5f0c822abbb0bb53a4dfba17dcc2f99f931` |
| M3 candidate | `a51000e6afccfea67ae198e3fa024a36cea02d49a22945aafc763c3d9302d043` |
| M4 execution policy | `c17f5e7ff825e8fbc455c3a649b1288083aea4580bcdccd1c78c8a707c50eb00` |
| M8 Agent manifest | `6902dcac0c86c514405107fb2752c3b011e5bf119a3c35ee1164bd90ff0cb965` |
| M12 original preregistration | `192291d7d4f86f704dfd3200bea321fa5bb9ad04ce354e1724bcdb0ac837f807` |
| M15 original freeze | `c41b52f10d50075ac30bfc0ff1d2f5f498ff5960ec36f4b7aa9958495d1264bd` |
| M15 original analysis | `57d591b880e4e40e668488bee3e0886ea36425df7f973b3d0d7a0a8ad69cc25a` |
| M17 incident freeze | `a970d4af2c1a25a9c02a1a68b3e5aeee608c48e5d8937321b9837bfa2c8acefb` |
| M17 replication preregistration | `169ce60cf8727234f0ce258235f12ccd7cfbb00e10509aa13fb54493707b49ba` |
| M18B execution admission | `2dd1b8578a4f37163c4a142ba494399a0e49c362deef503670a15a3fedc70b96` |
| M20 replication freeze | `e5389dec6b316263bb5c2582b19ea64ba4fb8be1e34d906cf9009436301be395` |
| M20 replication analysis | `85059fe78f7cf533d27efe13ba02a1081e362fdecf1611d9473afea8e8b0a6f9` |

M20 byte identities:

```text
replication freeze:   84d1504b689634809d8e1d6e4ea3db22366c4bb1a1af6dd5469e3b1921ee77f2
replication analysis: 18d0ee7a5bf7b78a0e7b47e01935a25b4608fbb05c7b588b84ea805d40d35bf2
```

## Final preregistered metric summary

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| Overall | 107/108 (99.07%) | 107/107 (100%) | 107/108 (99.07%) |
| Codex | 35/36 (97.22%) | 35/35 (100%) | 35/36 (97.22%) |
| Cursor | 36/36 (100%) | 36/36 (100%) | 36/36 (100%) |
| Grok Build | 36/36 (100%) | 36/36 (100%) | 36/36 (100%) |

End-to-End Reliability counts `COMPLETED + evaluator PASS` over every planned
slot. Completed Semantic Repair conditions on completed Agent execution.
Operational Completion counts Agent `COMPLETED` over every planned slot. The
single unresolved infrastructure slot stays in the first and third denominators.
Full capability, difficulty, and task tables are in the
[final report](../evidence/v1.3/formal-replication-01/FINAL_REPORT.md).

## Original incident and replication decision

The original study faithfully preserved 108 terminal observations. Its reported
metrics remain `76/108`, `76/76`, and `76/108` for the three metric families.
Codex had four canonical completed observations and 32 `COMMAND_FAILED`
observations. Later raw-evidence adjudication established that all 32 contained
the supported structured HTTP 429 evidence, so the original cross-Agent semantic
comparison is infrastructure-confounded.

M16 introduced strict structured parsing and `AgentProviderTransportError` for
this supported pre-canonical condition. The state machine now classifies it as
`network_provider_transport_same_route`, stops at an explicit retry boundary,
and forbids a canonical Run for that failed attempt. A canonical Run already
persisted remains authoritative.

M17 preserved the original study and preregistered an independent full 108-slot
replication. M18B froze the exact reviewed execution sources and runtime
identities before provider calls. M19 completed Replication-01 with two retry
histories:

- `rep01-r01-env_config-codex-gpt-5.5-relay`: attempts 1 and 2 both recorded
  `network_provider_transport_same_route`; the slot remains unresolved.
- `rep01-r01-request_signing-codex-gpt-5.5-relay`: attempt 1 recorded the same
  category; attempt 2 produced the canonical passing Run after the frozen
  remediation.

PatchBench artifacts prove structured HTTP 429 responses on the frozen Codex
provider route. The operator separately confirmed exhausted relay quota and
reset it during M19. That provider-side observation is not derivable from client
artifacts, which do not identify the relay implementation, physical upstream,
OpenAI, shared account, or IP limiting as the origin.

## Milestone history

| Milestone | Result |
|---|---|
| M1 | Benchmark design, capabilities, structural difficulty rubric, and manifest frozen |
| M2.1–M2.2 | Eight new reliability tasks implemented and validity-reviewed |
| M3 | Twelve-task candidate manifest and integrity checks frozen |
| M4 | Multi-Agent identity and execution policy frozen |
| M5 | Claude Code adapter admitted statically; later excluded after runtime incompatibility |
| M6 | Grok Build adapter and deterministic relay configuration admitted |
| M7R | Explicit Ailink relay-provider support |
| M7A | Claude runtime admission tested; environment incompatibility recorded |
| M7C | Cursor CLI fallback adapter and runtime admission completed |
| M8 | Final three-Agent semantic configuration manifest frozen |
| M9 | Frozen Agent resolution and exact CLI execution admission implemented |
| M10A | Calibration protocol frozen |
| M10B | Calibration execution and immutable evidence harness implemented |
| M11 | Calibration accepted |
| M12 | Calibration evidence frozen and original formal study preregistered |
| M13 | One-slot formal execution harness implemented |
| M14 | Original 108-slot formal study executed |
| M15 | Original evidence and preregistered analysis frozen |
| M16 | Codex structured provider-failure classification remediated |
| M17 | Original incident adjudicated; full Replication-01 preregistered |
| M18A | Replication execution harness implemented |
| M18B | Exact replication execution sources and runtime admission frozen |
| M19 | Replication-01 executed: 108 terminal, 107 canonical, one unresolved |
| M20 | Replication evidence, analysis, comparison, and documentation finalized |

## M20 checked artifacts

```text
evidence/v1.3/formal-replication-01/formal-study-freeze.json
evidence/v1.3/formal-replication-01/formal-study-analysis.json
evidence/v1.3/formal-replication-01/FINAL_REPORT.md
```

The compact freeze binds the study ledger, all 108 slots, all attempts, every
canonical Run, identity bindings, and raw Run files by SHA256. The analysis is
rebuilt deterministically from that checked freeze. Raw runtime namespaces remain
immutable and separate:

```text
results/v1.3-formal
results/v1.3-formal-replication-01
```

## Historical V1.1 and V1.2 layers

V1.1 remains the accepted 32-Run evidence release: 30 PASS and two operational
Codex quota failures, with all 30 completed Agent executions passing. See the
[V1.1 report](../evidence/v1.1/FINAL_REPORT.md) and
[archived handoff](history/V1_1_STATUS.md).

V1.2 Evidence-Grounded Diagnosis remains complete through D6-R5. It provides
bounded evidence compilation, Blind and Contrastive Diagnosis, deterministic
citation auditing, typed Human Gold, immutable acquisition, and a frozen
15-case Validation V1 result. Blind scored 9/10 preferred Top-1 over applicable
non-abstention cases; Contrastive scored 8/10; both had 0/3 abstention recall.
These are bounded suite results. Diagnosis never changes official evaluator
truth. See [Diagnosis](DIAGNOSIS.md).

## Final boundary

No provider call is required after M20. No unresolved V1.3 implementation work
remains. A new Agent, task, rerun, scoring metric, RAG/context engine, dashboard,
or statistical-significance study requires a separately scoped future version.
An optional supplemental recovery check for the unresolved slot may be designed
later, but it cannot replace Replication-01, change the denominator, or change
formal V1.3 metrics.

For a durable engineering narrative, start with
[V1.3 Formal Study](V1_3_FORMAL_STUDY.md). For interview preparation, use
[Interview Notes](interview_notes.md).
