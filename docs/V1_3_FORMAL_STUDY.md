# PatchBench V1.3 Formal Study

This is the durable engineering record for PatchBench V1.3. It is the recommended
first document for a future engineer or ChatGPT session. Exact checked identities
and current status are in [PROJECT_STATUS.md](PROJECT_STATUS.md); final tables are
in the [Replication-01 report](../evidence/v1.3/formal-replication-01/FINAL_REPORT.md).

PatchBench V1.3 is **FINAL and feature-frozen after M20**.

## 1. Motivation

A coding Agent is a deployed system, not only a model name. Repository repair
depends on task state, CLI behavior, tool permissions, credentials, provider
transport, process cleanup, patch capture, and official evaluation. One successful
run cannot establish reliability, and one aggregate rate can hide which boundary
failed.

V1.3 therefore built a formal, repeated study with frozen inputs, exact runtime
admission, immutable execution evidence, typed infrastructure handling, and
preregistered metrics.

**Interpretation / limitation:** The study is bounded to 12 purpose-built tasks,
three Agent configurations, three repetitions, one host period, and the frozen
provider-facing routes. It is not a universal Agent leaderboard or a statistical
generality claim.

## 2. Methodology

### Frozen design

**Repository-verified fact:** M1 defines four primary capabilities:
`local_boundary`, `cross_file`, `state_consistency`, and
`regression_robustness`. Easy, medium, and hard are structural categories based
on symptom-to-root-cause distance, coordinated edit breadth, temporal/state
interaction, interacting contracts and edge cases, and regression/navigation
pressure. There is no numeric difficulty score.

M2 created eight additional reliability tasks; together with four existing tasks,
M3 froze a 12-task candidate manifest. Each TaskSpec pins a local repository,
base commit, prompt, evaluator command, timeout, and immutable identity.

### Frozen Agent deployments

**Repository-verified fact:** M4 froze the Agent identity and execution policy.
M5–M7 admitted and hardened toolchain adapters. Claude Code was evaluated but
excluded after a runtime environment incompatibility; Cursor CLI became the
preregistered replacement mechanism. M8 froze three final configurations:

1. `codex-gpt-5.5-relay`
2. `cursor-claude-4.6-sonnet-medium`
3. `grok-build-grok-4.5-relay`

The manifest binds requested model, route options, timeout, policy SHA, and exact
CLI version. Provider-facing route names are known; physical upstream identity is
not independently proven. M9 resolves only these checked configurations and
requires exact canonical runtime versions.

### Calibration and formal preregistration

M10A froze calibration protocol; M10B added immutable calibration execution and
evidence. M11 accepted calibration. M12 froze calibration evidence and the
original formal preregistration. The plan fixed:

```text
12 tasks × 3 Agent configurations × 3 repetitions = 108 slots
```

It also fixed execution order, Docker evaluation, retry eligibility and limit,
and three metric formulas. M13 implemented the one-slot-at-a-time harness.

## 3. Execution architecture

```text
Task/candidate freeze
        ↓
Agent manifest + exact CLI admission
        ↓
formal preregistration
        ↓
FormalExecutionContract
        ↓
one-slot state transition
        ↓
host Agent in fresh Git worktree
        ↓
Docker official evaluator
        ↓
canonical Run OR typed pre-canonical infrastructure attempt
        ↓
immutable study/slot/attempt ledger
        ↓
compact checked freeze
        ↓
preregistered analysis
```

A canonical Run owns metadata, prompt, Agent stdout/stderr, evaluator log, and
patch. The formal ledger records every attempt before continuation. Retry is not
a loop: the study stops and requires a human-authorized frozen remediation.
Maximum attempts per slot are two. A persisted canonical Run wins over any later
exception; a supported pre-canonical infrastructure failure cannot fabricate a
Run.

The Agent operates on the host because it needs its own CLI and tools. The
repository evaluator runs in Docker to stabilize test execution and cleanup.
Docker is a practical evaluator boundary, not a hostile multi-tenant security
claim.

## 4. Original M14/M15 study

**Runtime evidence:** M14 executed all 108 original slots. M15 froze the compact
evidence and preregistered analysis without replacing any observation.

Original overall metrics:

```text
End-to-End Reliability:      76/108
Completed Semantic Repair:   76/76
Operational Completion:      76/108
```

Operationally, Cursor and Grok each completed 36/36. Codex produced four
canonical completed observations and 32 canonical `COMMAND_FAILED` observations.
At the time, these were valid outputs under the old abstraction: a CLI nonzero
exit became a canonical operational result.

**Interpretation / limitation:** The original metrics remain correct descriptions
of what the original harness recorded. They are contaminated for cross-Agent
semantic interpretation by the later provider incident finding.

## 5. Incident discovery and raw evidence

M16 investigation inspected the immutable Codex raw logs behind the 32 command
failures.

**Runtime evidence:** Every affected log contained the supported structured HTTP
429 event. The checked incident freeze binds all affected Run identities and raw
evidence to the original M15 freeze and analysis.

The taxonomy gap was precise: the adapter returned an ordinary command-failed
result for a structured provider transport response, and the formal harness then
canonicalized it. As a result, a provider availability condition occupied the
same canonical outcome channel as a completed but operationally failed CLI.

**Interpretation / limitation:** The evidence proves structured HTTP 429 responses
on the frozen provider-facing route. It does not prove whether the response
originated in the relay implementation, physical upstream, OpenAI, a shared
account, or IP limiting.

## 6. M16 remediation

M16 added strict parsing of the supported structured Codex event. A match raises
`AgentProviderTransportError`. The formal harness catches that error only before
canonical persistence and records:

```text
network_provider_transport_same_route
```

The slot becomes `retry_required`, stopping subsequent execution. The correction
is narrow and prospective. It does not classify arbitrary text as provider
failure, change frozen routes, rewrite historical Runs, or override an already
persisted canonical Run.

## 7. M17 adjudication and replication decision

M17 froze the original incident and preregistered a fresh independent full
replication. It explicitly forbids using original outcomes to change tasks,
Agents, models, timeout, route, order, repetitions, retry policy, labels,
evaluators, or metrics.

A Codex-only replacement was rejected because it would alter the balanced design
after observing results. A full 108-slot study preserves the same Task × Agent ×
repetition structure. Original and replication observations are neither pooled
nor averaged; comparison is descriptive sensitivity analysis.

## 8. M18 execution admission

M18A implemented the replication facade around the shared formal state machine.
M18B froze the reviewed execution source hashes, replication preregistration,
M16 remediation commit, Agent manifest, Docker backend, result namespace, and
execution harness commit.

The original and replication namespaces cannot alias:

```text
results/v1.3-formal
results/v1.3-formal-replication-01
```

This admission boundary prevents a later implementation or environment from
silently claiming to be the reviewed production harness.

## 9. Runtime drift caught before M19

Before production initialization, runtime admission detected that the host PATH
selected a newer VS Code Codex binary, while Cursor and Grok were absent from
PATH and credentials were unavailable. M19 correctly stopped before creating the
replication namespace.

Read-only investigation found all three exact frozen binaries already installed.
An empty `~/.bash_profile` prevented the existing `~/.profile` and `~/.bashrc`
PATH configuration from loading. Restoring that existing login chain selected:

```text
codex-cli 0.153.4
Cursor CLI 2026.09.18-9a7762b
grok 1.0.34 (3736acbc8658)
```

No frozen identity was changed to fit the host. Credentials remained an
operator-controlled prerequisite and were never printed or committed.

**Repository-verified fact:** The runtime manifest and admission artifacts stayed
unchanged.

**Interpretation / limitation:** This event demonstrates why exact runtime
admission must precede provider calls; source reproducibility alone is
insufficient.

## 10. M19 Replication-01 execution

**Runtime evidence:** M19 terminalized all 108 planned slots:

```text
terminal=108/108
canonical=107
unresolved infrastructure=1
blocked=0
remaining=0
```

The exact retry history is:

1. `rep01-r01-env_config-codex-gpt-5.5-relay`
   - attempt 1: `retryable_infrastructure_failure`,
     `network_provider_transport_same_route`
   - attempt 2: frozen same-route remediation,
     `unresolved_infrastructure`, same category
2. `rep01-r01-request_signing-codex-gpt-5.5-relay`
   - attempt 1: `retryable_infrastructure_failure`, same category
   - attempt 2: frozen same-route remediation, canonical completed passing Run

No attempt 3 exists. The unresolved slot stays in the fixed denominator.

**Operator-reported provider-side fact:** During Replication-01, the operator
inspected the relay service, confirmed that its quota had been exhausted, and
reset it. Execution then continued under the same frozen route.

**Runtime evidence:** The client artifacts independently establish structured
HTTP 429 and the typed same-route transport category. They do not contain the
provider-side quota dashboard state.

The corrected classification answered the central incident question: repeated
supported 429s were no longer silently canonicalized as command failures and did
not automatically consume later slots. The state machine stopped for an explicit
retry decision.

## 11. M20 final freeze and analysis

M20 reads the completed runtime tree and emits:

```text
evidence/v1.3/formal-replication-01/formal-study-freeze.json
evidence/v1.3/formal-replication-01/formal-study-analysis.json
evidence/v1.3/formal-replication-01/FINAL_REPORT.md
```

The compact freeze validates the M17 preregistration through the
Replication-01 execution contract and binds:

- study, design, candidate, Agent manifest, harness, and admission identities;
- source `study.json` semantic and byte hashes;
- all 108 ordered slots and terminal states;
- every attempt ledger semantic and byte hash;
- remediation and failure category;
- canonical attempt and Run linkage;
- every canonical Run semantic hash and identity binding;
- metadata, prompt, stdout, stderr, test log, and patch byte hashes.

Final checked identities:

```text
Replication freeze semantic SHA:
  e5389dec6b316263bb5c2582b19ea64ba4fb8be1e34d906cf9009436301be395
Replication freeze byte SHA:
  84d1504b689634809d8e1d6e4ea3db22366c4bb1a1af6dd5469e3b1921ee77f2
Replication analysis semantic SHA:
  85059fe78f7cf533d27efe13ba02a1081e362fdecf1611d9473afea8e8b0a6f9
Replication analysis byte SHA:
  18d0ee7a5bf7b78a0e7b47e01935a25b4608fbb05c7b588b84ea805d40d35bf2
```

## 12. Final preregistered metrics

The analysis computes only the M17/M12 formulas.

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| Overall | 107/108 | 107/107 | 107/108 |
| Codex | 35/36 | 35/35 | 35/36 |
| Cursor | 36/36 | 36/36 | 36/36 |
| Grok Build | 36/36 | 36/36 | 36/36 |

The one unresolved slot is `env_config`, which places the only reduced capability
and difficulty strata at:

```text
local_boundary: 26/27 E2E, 26/26 semantic, 26/27 operational
easy:           35/36 E2E, 35/35 semantic, 35/36 operational
env_config:       8/9 E2E,     8/8 semantic,   8/9 operational
```

Every other capability is 27/27 across all three families, every other difficulty
is 36/36, and every other task is 9/9. See the checked analysis for exact decimal
representations.

## 13. Metric interpretation

### End-to-End Reliability

```text
COMPLETED + evaluator PASS / all planned slots
```

This measures delivery through the whole frozen deployment path. Infrastructure
therefore stays in the denominator.

### Completed Semantic Repair

```text
COMPLETED + evaluator PASS / Agent status COMPLETED slots
```

This measures evaluator success conditional on a completed Agent execution. An
unresolved infrastructure slot has no completed patch and does not enter this
denominator.

### Operational Completion

```text
Agent status COMPLETED / all planned slots
```

This measures whether the deployed Agent completed. It is distinct from whether
a completed patch passed.

There is no composite score, adjusted rate, quota-excluded official metric, or
combined original-plus-replication leaderboard.

## 14. Limitations

**Interpretation / limitation:**

- Twelve tasks and 108 slots do not establish statistical generality.
- The tasks are purpose-built and bounded to one repository-fixture suite.
- Each result describes a full Agent deployment, not isolated model ability.
- Provider-facing routes are recorded; physical upstream identity is not proven.
- Exact CLI admission controls known runtime identity but cannot freeze remote
  model weights or provider implementation.
- Docker improves evaluator reproducibility but is not a complete security
  boundary for arbitrary hostile code.
- All canonical Replication-01 Runs passed, so V1.3 does not estimate a rich
  semantic-failure distribution for these deployments.
- Operator-confirmed quota state is useful incident context but is not frozen
  client evidence.

## 15. Future boundary

V1.3 needs no M21, new Agent, new task, rerun, metric, RAG/context engine,
dashboard, or significance study. Any such work requires a separately scoped
future version with its own design and preregistration.

The first unresolved slot could later receive a clearly labeled supplemental
recovery check. Such a check must not replace Replication-01, alter its denominator,
or revise formal metrics. V1.3 completion does not require it.

## 16. Source map

- `tasks/reliability/v1.3-design.json`: capability and difficulty methodology.
- `tasks/reliability/v1.3-candidate.json`: exact 12-task candidate.
- `tasks/reliability/v1.3-agent-configurations.json`: final Agent identities.
- `src/patchbench/application/v13_agent_execution.py`: frozen resolution.
- `src/patchbench/application/v13_formal_execution.py`: shared state machine.
- `src/patchbench/agents/codex.py`: Codex runtime and provider error boundary.
- `src/patchbench/agents/structured_provider_failure.py`: strict 429 parsing.
- `src/patchbench/domain/formal_replication.py`: M17 replication contract.
- `src/patchbench/application/v13_formal_replication_execution.py`: M18 facade.
- `scripts/v13_formal_replication_evidence.py`: M20 freeze builder/verifier.
- `scripts/v13_formal_replication_analysis.py`: M20 analysis builder/verifier.
- `evidence/v1.3/formal/codex-429-incident-freeze.json`: original incident.
- `evidence/v1.3/formal-replication-01/`: execution admission and final artifacts.
