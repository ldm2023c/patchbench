# PatchBench V1.3 Replication-01 Final Evidence Report

PatchBench V1.3 is **FINAL and feature-frozen after M20**. This report is derived from the checked Replication-01 freeze and preregistered analysis. Replication-01 is the primary V1.3 result; the original study remains an immutable historical execution.

## Study and protocol identities

- Study: `patchbench-v1.3-formal-replication-01`
- Replication preregistration SHA: `169ce60cf8727234f0ce258235f12ccd7cfbb00e10509aa13fb54493707b49ba`
- Execution admission SHA: `2dd1b8578a4f37163c4a142ba494399a0e49c362deef503670a15a3fedc70b96`
- Replication freeze SHA: `e5389dec6b316263bb5c2582b19ea64ba4fb8be1e34d906cf9009436301be395`
- Original incident freeze SHA: `a970d4af2c1a25a9c02a1a68b3e5aeee608c48e5d8937321b9837bfa2c8acefb`
- Original formal freeze SHA: `c41b52f10d50075ac30bfc0ff1d2f5f498ff5960ec36f4b7aa9958495d1264bd`
- Original formal analysis SHA: `57d591b880e4e40e668488bee3e0886ea36425df7f973b3d0d7a0a8ad69cc25a`

## Execution completion

- Planned and terminal: **108/108**
- Canonical observations: **107**
- Unresolved infrastructure: **1**
- Blocked: **0**
- Remaining slots: **0**

## Preregistered metrics

End-to-End Reliability is `COMPLETED + evaluator PASS / all planned slots`. Completed Semantic Repair uses completed Agent executions as its denominator. Operational Completion is `Agent COMPLETED / all planned slots`. The unresolved infrastructure slot remains in the first and third denominators.


### Overall

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| `overall` | 107/108 (0.990741) | 107/107 (1.000000) | 107/108 (0.990741) |

### By Agent configuration

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| `codex-gpt-5.5-relay` | 35/36 (0.972222) | 35/35 (1.000000) | 35/36 (0.972222) |
| `cursor-claude-4.6-sonnet-medium` | 36/36 (1.000000) | 36/36 (1.000000) | 36/36 (1.000000) |
| `grok-build-grok-4.5-relay` | 36/36 (1.000000) | 36/36 (1.000000) | 36/36 (1.000000) |

### By primary capability

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| `local_boundary` | 26/27 (0.962963) | 26/26 (1.000000) | 26/27 (0.962963) |
| `cross_file` | 27/27 (1.000000) | 27/27 (1.000000) | 27/27 (1.000000) |
| `state_consistency` | 27/27 (1.000000) | 27/27 (1.000000) | 27/27 (1.000000) |
| `regression_robustness` | 27/27 (1.000000) | 27/27 (1.000000) | 27/27 (1.000000) |

### By designed difficulty

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| `easy` | 35/36 (0.972222) | 35/35 (1.000000) | 35/36 (0.972222) |
| `medium` | 36/36 (1.000000) | 36/36 (1.000000) | 36/36 (1.000000) |
| `hard` | 36/36 (1.000000) | 36/36 (1.000000) | 36/36 (1.000000) |

### By task

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| `env_config` | 8/9 (0.888889) | 8/8 (1.000000) | 8/9 (0.888889) |
| `request_signing` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `byte_ranges` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `config_resolution` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `message_codec` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `schema_upgrade` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `resource_lifecycle` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `streaming_events` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `atomic_batch` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `format_fallback` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `atomic_writer` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |
| `cache_revalidation` | 9/9 (1.000000) | 9/9 (1.000000) | 9/9 (1.000000) |

## Retry and infrastructure history

Two slots required the single preregistered retry, both after `network_provider_transport_same_route`:

1. `rep01-r01-env_config-codex-gpt-5.5-relay`: attempt 1 was `retryable_infrastructure_failure`; attempt 2 used `network/provider transport availability without changing provider route` and ended `unresolved_infrastructure`.
2. `rep01-r01-request_signing-codex-gpt-5.5-relay`: attempt 1 was `retryable_infrastructure_failure`; attempt 2 used the same frozen remediation and produced the canonical observation.

No attempt 3 or replacement Run exists. The unresolved slot remains in the fixed denominator of 108. A future supplemental recovery check could examine it, but cannot replace Replication-01 or change official metrics.

## Original study versus Replication-01

The original study terminalized all 108 preregistered slots. It recorded 76/108 End-to-End Reliability, 76/76 Completed Semantic Repair, and 76/108 Operational Completion. Codex had 4 canonical completed observations; 32 Codex `COMMAND_FAILED` observations were later shown by immutable raw evidence to contain structured HTTP 429 responses. Cursor and Grok each completed 36/36.

M16 added typed detection for the supported structured Codex HTTP 429 condition. M17 preregistered a fresh, full 108-slot replication rather than rewriting or selectively replacing the first study. In Replication-01, provider-aware classification prevented the two observed same-route 429 incidents from being silently canonicalized as command failures and from automatically consuming later slots: the state machine stopped for an explicit retry decision. One retry resolved; one exhausted the two-attempt limit and remains unresolved.

PatchBench evidence establishes a structured HTTP 429 on the frozen Codex provider route. During Replication-01, the operator separately confirmed that the relay quota had been exhausted and reset it; that provider-side observation is not derivable from the frozen client artifacts themselves. The evidence does not identify whether the HTTP 429 originated in the relay implementation, a physical upstream, OpenAI, a shared account, or IP limiting.

The studies are reported separately. Their observations are not pooled, averaged, cherry-picked, or used to construct a combined leaderboard.

## Limitations and reproducibility boundaries

- This is a bounded study of 12 frozen repository tasks, three Agent configurations, and three repetitions. It does not establish broad statistical generality or universal Agent superiority.
- PatchBench evaluates each frozen Agent deployment as a system: CLI, model request, provider route, tool behavior, repository interaction, and Docker evaluator.
- Infrastructure-unresolved observations lower End-to-End Reliability and Operational Completion because those metrics include the deployment path. They do not enter Completed Semantic Repair because no Agent execution completed.
- Provider-facing route identities are frozen; physical upstream identity is not independently proven.
- Docker provides evaluator reproducibility and isolation boundaries, not a claim that arbitrary code is perfectly secure.
- Raw runtime evidence remains outside this compact checked artifact; the freeze binds every ledger, attempt, canonical Run, and raw Run file by SHA256.
- No LLM judge supplies the primary outcome. The official evaluator is the frozen Docker test contract.

Further Agents, tasks, reruns, metrics, dashboards, context systems, or significance studies require a separately scoped future version. No M21 is required for V1.3 completion.
