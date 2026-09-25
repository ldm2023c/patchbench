# PatchBench Interview Notes

PatchBench V1.3 is **FINAL and feature-frozen after M20**. Start with the
[V1.3 engineering record](V1_3_FORMAL_STUDY.md), then use the
[final evidence report](../evidence/v1.3/formal-replication-01/FINAL_REPORT.md)
and [project status](PROJECT_STATUS.md) for exact identities. V1.1 and V1.2 are
completed historical layers; [Diagnosis](DIAGNOSIS.md) remains the V1.2 subsystem
reference.

## 30-second project introduction

PatchBench is a reproducible coding-Agent reliability platform for repository
repairs. It freezes tasks, Agent configurations, exact CLI runtimes, execution
order, and Docker evaluation; runs repeated independent attempts; and preserves
raw evidence before computing metrics. V1.3 studied 12 tasks across three Agents
and three repetitions, for 108 slots. The final independent replication ended
with 107 canonical passing Runs and one unresolved infrastructure slot. Its
three metrics are 107/108 End-to-End Reliability, 107/107 Completed Semantic
Repair, and 107/108 Operational Completion. The key engineering lesson was that
provider failures must be typed before a canonical Run exists, rather than
silently counted as model repair failures.

## 90-second / 2-minute architecture explanation

A frozen TaskSpec and candidate manifest define repository state, prompt,
evaluator, capability, and difficulty. A frozen Agent manifest binds the CLI,
requested model, route options, policy, timeout, and exact runtime identity.
Formal preregistration fixes 12 tasks, three Agent configurations, three
repetitions, 108 ordered slots, retry rules, and metric formulas.

The execution harness advances one slot per command. An Agent runs on the host
in a fresh Git worktree; the official evaluator runs in Docker. A completed
attempt becomes one canonical `RunRecord`. A supported failure before canonical
persistence becomes a typed infrastructure attempt and stops at
`retry_required`. The human may authorize one frozen remediation, so the maximum
is two attempts. There are no replacement Runs and no denominator changes.

Every attempt and slot transition is immutable. M20 converts the terminal runtime
tree into a compact checked freeze that hashes every ledger, canonical Run, and
raw Run file. The preregistered analysis reads only that freeze and reports three
separate metrics. V1.2 Diagnosis remains optional evidence-grounded inference;
it is not the V1.3 judge and never changes official evaluator truth.

## Why this project exists

One successful coding-Agent run does not establish reliability. A deployment can
fail because of semantic repair quality, CLI/tool behavior, credentials, provider
transport, repository setup, or evaluation infrastructure. Combining those
conditions into one vague pass rate hides the engineering question.

PatchBench makes the unit of evidence explicit and separates Agent completion,
official semantic evaluation, and pre-canonical infrastructure handling. This
supports reproducible debugging without pretending that a small benchmark proves
universal model quality.

## V1.3 experimental design

- **12 frozen tasks**, each with a pinned repository commit and Docker evaluator.
- **4 primary capabilities:** `local_boundary`, `cross_file`,
  `state_consistency`, and `regression_robustness`.
- **3 designed difficulties:** easy, medium, and hard, defined structurally.
- **3 frozen Agents:** Codex GPT-5.5 through an Ailink relay route, Cursor CLI
  Claude 4.6 Sonnet Medium, and Grok Build Grok 4.5 through an Ailink relay route.
- **3 repetitions per Task × Agent cell**, producing **108 ordered slots**.
- Exact Agent configuration SHA, policy SHA, model, route options, timeout, and
  CLI version were frozen before production execution.
- The Agent ran on the host; Docker supplied the official deterministic evaluator.
- The order, retry policy, and three metric formulas were preregistered.

PatchBench evaluates the frozen Agent deployment as a system. The result cannot
be reduced to an abstract model name alone.

## The major production incident

The original study appeared to show:

```text
Codex: 4/36 operational completion
Cursor: 36/36 operational completion
Grok: 36/36 operational completion
```

Investigation found 32 Codex `COMMAND_FAILED` observations. All 32 immutable raw
agent logs contained the supported structured HTTP 429 event. The old abstraction
mapped a CLI nonzero exit to a canonical command-failed Run before it understood
this provider transport condition.

That means `4/36` must not be described as GPT-5.5 semantic coding ability. It
is a faithful operational record of the original harness, but the cross-Agent
semantic interpretation is infrastructure-confounded.

## The fix

M16 added strict structured event parsing for the supported Codex HTTP 429 shape
and raised `AgentProviderTransportError`. Before a canonical Run exists, the
formal harness maps it to `network_provider_transport_same_route`, persists the
attempt, and stops at `retry_required`. It never creates a canonical Run for that
attempt. If a canonical Run was already persisted, the Run remains authoritative
and a later exception cannot erase it.

This correction changes taxonomy and prospective handling. It does not rewrite
old Run evidence, infer arbitrary network errors, or identify the physical source
of a 429.

## Why the first experiment was preserved

Deleting or selectively rerunning the original would permit outcome-based
replacement. PatchBench instead:

1. preserved the immutable original runtime and checked M15 artifacts;
2. froze a deterministic M17 incident adjudication;
3. preregistered an independent full 108-slot replication;
4. froze the reviewed replication harness and runtime identities before execution;
5. kept original and replication namespaces separate;
6. reported the two studies descriptively without pooling them.

A full replication was necessary because a Codex-only replacement would change
the design after observing results and would not reproduce the original balanced
Task × Agent × repetition matrix.

## Replication story

M19 completed Replication-01 with:

```text
terminal=108/108
canonical=107
unresolved infrastructure=1
blocked=0
remaining=0
```

Two Codex slots encountered `network_provider_transport_same_route` on attempt 1.
The `env_config` slot exhausted the single retry and remains unresolved. The
`request_signing` slot produced a canonical passing Run on attempt 2. No attempt
3 or replacement Run exists.

PatchBench evidence establishes a structured HTTP 429 on the frozen Codex route.
The operator separately inspected the relay service, confirmed exhausted relay
quota, and reset it. That provider-side fact is operator-reported; it is not
proved by the checked client artifacts. The artifacts cannot establish whether
the 429 originated in the relay implementation, physical upstream, OpenAI,
shared account, or IP limiting.

Final Replication-01 metrics:

| Stratum | End-to-End Reliability | Completed Semantic Repair | Operational Completion |
|---|---:|---:|---:|
| Overall | 107/108 | 107/107 | 107/108 |
| Codex | 35/36 | 35/35 | 35/36 |
| Cursor | 36/36 | 36/36 | 36/36 |
| Grok Build | 36/36 | 36/36 | 36/36 |

All 107 completed Agent executions passed their frozen evaluator. This is a
bounded result over 12 tasks, not a universal ranking.

## Three metrics and why all three exist

### End-to-End Reliability

```text
COMPLETED + evaluator PASS / all planned slots
```

Interview language: “Did the frozen deployment deliver a verified repair when a
slot was requested?” Infrastructure remains in the denominator because users
experience the whole deployment path.

### Completed Semantic Repair

```text
COMPLETED + evaluator PASS / Agent status COMPLETED slots
```

Interview language: “Conditional on the Agent completing, did its patch pass the
frozen evaluator?” An infrastructure-unresolved slot is excluded because no
completed repair exists to judge.

### Operational Completion

```text
Agent status COMPLETED / all planned slots
```

Interview language: “Could the deployment complete the coding attempt?” This
separates availability from conditional repair quality.

None of these is a composite winner score. The unresolved slot remains in the
fixed E2E and operational denominators.

## Key engineering decisions

- **Git worktree isolation:** every Run starts from the pinned commit outside the
  source working tree.
- **Docker evaluation:** evaluator runtime and baseline tests are controlled;
  Agent execution remains host-side.
- **TaskSpec and candidate freeze:** task content and selection cannot drift after
  outcomes are observed.
- **Agent manifest freeze:** CLI, model, route options, policy, and timeout form
  one semantic deployment identity.
- **Exact CLI admission:** padded, mismatched, or unavailable runtime versions
  fail before provider calls.
- **RunRecord and raw evidence:** metadata, prompt, stdout, stderr, test log, and
  patch remain inspectable and hash-bound.
- **No LLM primary judge:** deterministic repository tests define official truth.
- **Replay:** a historical patch can be re-evaluated without another Agent call.
- **Diagnosis boundary:** V1.2 hypotheses are optional and cannot revise truth.
- **Formal attempt state machine:** one command advances one slot; evidence is
  persisted before continuation.
- **Retry policy:** one human-authorized same-route remediation, maximum two
  attempts, no automatic retry.
- **Evidence freeze:** compact checked artifacts bind the raw runtime tree without
  committing the entire tree.

## Hard questions and good answers

### Why not just compare pass rates?

A single rate can mix semantic failures, timeouts, provider failures, and setup
failures. The three preregistered metrics expose deployment reliability,
conditional repair quality, and operational completion separately.

### Why is infrastructure failure in the E2E denominator?

E2E asks whether a requested slot delivered a verified repair. A user-facing
deployment failure is still an unsuccessful delivery. Removing it post hoc would
change the preregistered estimand and denominator.

### Why exclude it from Completed Semantic Repair?

That metric is conditional on a completed Agent execution. With no completed
patch, there is no semantic repair outcome to evaluate.

### Why not rerun the unresolved slot?

The preregistered limit is two attempts. A third official attempt would violate
the frozen policy and permit result-dependent continuation. A later supplemental
check may be labeled separately, but cannot replace the slot or change metrics.

### Why use Docker?

Docker gives the evaluator a controlled image, command, mount, and cleanup
boundary across Runs. It improves reproducibility; it does not make arbitrary
code perfectly secure.

### Why freeze exact CLI versions?

The CLI controls prompts, tools, permissions, configuration discovery, output
schema, and process behavior. Model equality alone does not make two Agent
deployments equivalent.

### How do you know the 32 original failures were 429?

The incident verifier reads immutable raw agent logs for all 32 affected Runs and
requires the supported structured HTTP 429 shape, then binds the adjudication to
the original freeze and analysis identities.

### Can you prove Ailink or OpenAI caused the 429?

No. The artifacts establish the frozen provider-facing route and structured HTTP
429 response. They do not prove the physical upstream origin. Relay quota
exhaustion during replication is a separate operator-confirmed observation.

### Why a full 108-run replication instead of Codex-only 36?

A full replication preserves the preregistered balanced design and avoids
selecting only the affected Agent after seeing outcomes. It also tests the
corrected state machine under the same complete protocol.

### Why not use an LLM judge?

The tasks have deterministic repository tests. An LLM judge would add another
nondeterministic model and unclear calibration to the primary outcome. V1.2
Diagnosis is explicitly secondary and evidence-grounded.

### What would you improve in V2?

Use a separately preregistered broader task sample, more environments, and
power-aware statistical design. Improve controlled credential/runtime admission
and provider observability without changing the meaning of historical studies.

### What is the biggest limitation?

Twelve purpose-built tasks and one host/provider period are too small for broad
generality. Provider routes are observed at the client boundary, not
cryptographically traced to physical upstreams.

### What was your contribution and hardest engineering decision?

The central contribution was designing auditable boundaries across task freeze,
Agent identity, runtime admission, execution state, raw evidence, incident
taxonomy, and analysis. The hardest decision was preserving an apparently bad
first result, correcting the abstraction prospectively, and preregistering a
full replication instead of rewriting history.

## Source-reading map

| File | What it demonstrates |
|---|---|
| `src/patchbench/application/v13_formal_execution.py` | One-slot state machine, retry boundary, canonical Run precedence |
| `src/patchbench/application/v13_agent_execution.py` | Frozen Agent resolution and identity binding |
| `src/patchbench/agents/codex.py` | Exact Codex admission and typed provider failure propagation |
| `src/patchbench/agents/structured_provider_failure.py` | Strict supported HTTP 429 parsing |
| `src/patchbench/domain/formal_replication.py` | Full independent replication preregistration |
| `src/patchbench/application/v13_formal_replication_execution.py` | M18 admission-gated execution facade and namespace separation |
| `scripts/v13_formal_replication_evidence.py` | Replication runtime verification and compact freeze |
| `scripts/v13_formal_replication_analysis.py` | Preregistered metric derivation from checked evidence |
| `tasks/reliability/v1.3-design.json` | Task design, capability, and structural difficulty freeze |
| `tasks/reliability/v1.3-candidate.json` | Exact 12-task candidate identity |
| `tasks/reliability/v1.3-agent-configurations.json` | Three deployment identities and CLI versions |
| `tasks/reliability/v1.3-replication-01-preregistration.json` | Fixed replication order, retry policy, and metrics |
| `evidence/v1.3/formal/codex-429-incident-freeze.json` | Original incident adjudication |
| `evidence/v1.3/formal-replication-01/formal-study-freeze.json` | Final compact execution evidence |
| `evidence/v1.3/formal-replication-01/formal-study-analysis.json` | Final machine-readable metrics |

## Claims not to make

Do not say:

- “GPT-5.5 only had 11.1% coding ability.”
- “Cursor or Grok is universally better.”
- “OpenAI definitely caused the 429.”
- “The unresolved replication slot was a model failure.”
- “The 108 slots establish statistical generality.”
- “Docker makes arbitrary code secure.”
- “Diagnosis is the official judge.”
- “The operator quota observation is proved by frozen client artifacts.”
- “A future supplemental recovery run can replace Replication-01.”

## Final boundary

PatchBench V1.3 is complete. No M21, new Agent, new task, rerun, score, RAG
system, dashboard, or significance study remains required. Each would need a
separately scoped future version.

## Appendix: Historical decision snapshots

以下 ADR 保留其作出时的里程碑语境。它们记录了演进过程，不替代上面的当前架构
说明；涉及 “before / future / temporarily” 的措辞应按历史陈述理解。

---

## ADR-001: Why CLI-first?

### Decision

Start PatchBench as a local CLI tool instead of building a web application.

### Reason

The core value of PatchBench is reproducible coding-agent experimentation and failure analysis, not frontend presentation.

CLI-first reduces unrelated engineering work and lets the project validate its core experiment loop earlier.

### Trade-off

The project is initially less visually impressive, but a dashboard can be added after the experiment engine becomes stable.

---

## ADR-002: Why FakeAgent before CodexAdapter?

### Decision

Validate the complete experiment pipeline using a deterministic fake agent before integrating Codex.

### Reason

This isolates PatchBench orchestration bugs from:

- Codex authentication;
- external network behavior;
- model nondeterminism;
- sandbox problems;
- agent-specific failures.

The FakeAgent allows the system to verify:

```text
Task
 ↓
Workspace
 ↓
Agent
 ↓
Patch
 ↓
Evaluator
 ↓
Artifact persistence
```

without relying on an external AI system.

### Trade-off

It adds a small amount of temporary implementation, but substantially improves debuggability and makes failures easier to attribute.

---

## ADR-003: Why detached Git worktrees for local Runs?

### Decision

Create a separate detached Git worktree at the configured base commit for every local Run.

### Reason

A detached worktree gives the Run an independent filesystem while preserving an exact, Git-verified starting commit. Agent edits and evaluator byproducts remain outside the source repository, and Git can capture the resulting patch directly.

### Trade-off

The source must be an existing local Git repository, and worktree registration must be cleaned up even when execution fails. Milestone 1 handles this with a context-managed lifecycle and does not clone remote repositories.

---

## ADR-004: Why use the Docker CLI before adding an SDK?

### Decision

Use explicit Docker CLI subprocess calls for the initial sandbox lifecycle.

### Reason

Milestone 2.1 needs only container creation and destruction. The installed Docker CLI already exposes those operations, keeps the dependency set small, and makes the exact lifecycle commands inspectable.

### Trade-off

CLI failures require explicit return-code and stderr handling. If later sandbox behavior becomes substantially more complex, the implementation choice can be reevaluated using evidence from those requirements.

---

## ADR-005: Why one fixed workspace mount and argv-style commands?

### Decision

Milestone 2.2 accepts at most one host workspace, mounts it read-write at `/workspace`, and represents container commands as explicit argument sequences.

### Reason

A single fixed mount makes host exposure easy to inspect and avoids introducing a general volume policy before it is needed. Argument sequences preserve command boundaries without shell parsing or `shell=True`.

### Trade-off

The container path and working directory are intentionally fixed, and ownership of files created through the bind mount follows Docker's host/container UID behavior. Broader mount and identity policies are deferred.

---

## ADR-006: Why implementation-independent limits and whole-sandbox timeout cleanup?

### Decision

Represent CPU and memory limits as validated numeric values in the Sandbox contract, then translate them into Docker arguments in DockerSandbox. If a host-side `docker exec` call times out, force-remove the entire disposable container and invalidate its handle.

### Reason

Numeric resource concepts do not couple callers to Docker CLI syntax. Destroying the container on timeout guarantees that killing the host Docker client does not leave an unobserved task process running inside the sandbox.

### Trade-off

A timed-out sandbox cannot be reused, and cleanup is coarser than terminating only the task process. This favors deterministic cleanup over in-container process discovery or signal orchestration.

---

## ADR-007: Why move evaluation into the Sandbox before agent execution?

### Decision

Add a Sandbox-backed evaluator as an independently testable component while keeping FakeAgent, LocalRun, and the CLI host-side until the next integration slice.

### Reason

Task evaluation already has a narrow command/result boundary, so it can validate real sandbox execution without coupling Docker lifecycle changes to Run orchestration or the future Codex execution design.

### Trade-off

The host and Sandbox evaluators temporarily coexist, and merely adding the Sandbox evaluator does not make existing Runs Dockerized.

---

## ADR-008: Why keep FakeAgent host-side and use unittest for the Docker example?

### Decision

FakeAgent remains a host-side orchestration test double, while task evaluation may run in Docker against its isolated worktree. Patch capture occurs before evaluation, and the controlled example uses `python -B -m unittest -q`.

### Reason

Agent execution is a separate Milestone 3 boundary. Capturing first excludes evaluator caches and temporary files from the agent patch. Standard-library unittest runs identically on the host and in the minimal Python image, while `-B` avoids bytecode caches in the bind mount.

### Trade-off

The example proves Docker-backed Run orchestration without proving dependency provisioning for arbitrary repositories. Real project runtime and dependency preparation remain future work.
