# PatchBench Interview Notes

Current reference: [Project Status](PROJECT_STATUS.md) and
[Diagnosis contracts](DIAGNOSIS.md). Historical ADRs are retained below.

## 1. 30-second pitch

PatchBench measures coding-agent reliability through repeated independent Runs,
fixed official evaluation, persisted evidence, and patch Replay. V1.1 froze a
32-Run evidence release: 30 PASS and two external Codex quota failures; all 30
normally completed executions passed. V1.2 adds reviewed evidence-grounded
Diagnosis infrastructure: complete bounded evidence, Blind and same-cell PASS
Contrastive hypotheses, a structural citation Auditor, and immutable artifacts.
Human-Gold scoring, aggregate metrics, a frozen 15-case validation suite, real
provider acquisition, semantic score finalization, and the final Validation V1
result are implemented. On the frozen 13 semantic cases, Blind reached 9/10
preferred Top-1 over non-abstention cases while Contrastive reached 8/10; both
modes had 0/3 abstention recall. I describe these as bounded suite results, not
general Diagnosis accuracy.

## 2. 2-minute story

A single PASS demonstrates one successful attempt, not reliability. I separated
a Run, the atomic execution with its own workspace and evidence, from an
Experiment, the frozen configuration and ordered repeated Runs with aggregates.
Agent completion and official evaluation are independent: a completed Agent can
produce a failing patch, while operational quota failures need separate reporting.

V1.1 tightened the evidence boundary. Git captures the patch, historical
provenance records the actual base, and frozen evaluation restores baseline tests
in a separate evaluation worktree. Agent edits to tests remain visible evidence
but cannot replace benchmark test truth. Replay re-applies a historical patch
without another Agent call. The final release measured 32 Runs over four bounded
tasks: 30 PASS, two quota failures, no replacement Runs. That is a bounded result,
not a universal model-reliability claim.

V1.2 addresses a different question: what hypotheses can be grounded in a
completed semantic failure's evidence? D1–D6 route eligible Runs, compile exact
bounded source/tests/patch/log evidence, make optional provider inference, audit
citations deterministically, persist the attempt, and score it against Human Gold. Blind Diagnosis is the
headline mode. Contrastive adds one verified same-cell PASS as secondary comparison
evidence, never a reference fix. The provider cannot change official PASS/FAIL.
The important limitation is that structural correctness is not semantic accuracy:
the final real-provider Validation V1 result is a small frozen-suite measurement,
not proof of production diagnosis quality or broad model reliability.

## 3. 5-minute architecture walkthrough

1. **Run / Experiment / Replay.** A Run starts at a known base in a fresh detached
   Git worktree. Agent execution, patch capture, and official evaluation have
   distinct responsibilities. Experiment repeats independent Runs sequentially;
   Analyze reads persisted evidence; Replay uses the stored patch with zero Agents.
2. **Official truth and routing.** Official PASS/FAIL remains fixed. FAIL with an
   operational Agent failure routes to operational analysis. FAIL with a completed
   Agent is eligible for semantic Diagnosis, subject to evidence readiness.
3. **Verified evidence.** D2 checks raw TaskSpec/patch/log identities and historical
   provenance, reconstructs base and candidate, and includes complete bounded
   production source plus frozen tests. Unchanged files matter for cross-file
   hypotheses. Unsupported included sources fail closed; no LLM retrieval or
   truncation fallback can silently change context.
4. **Inference boundary.** A separate DiagnosisProvider receives text/schema,
   not repository or shell handles. Permission defaults closed and byte limits
   apply before inference. Versioned prompts preserve exact evidence as untrusted
   data. The built-in OpenAI adapter is tool-less, store-false, and retry-free.
5. **Typed hypotheses and auditing.** The provider emits only semantic fields.
   PatchBench injects identity and linkage. Output is strictly validated, with
   first-class abstention. D3 checks hashes, reference membership, and exact
   artifact-relative ranges; it does not decide semantic truth.
6. **Contrastive and persistence.** D5 selects the canonical first eligible
   same-cell PASS in one persisted Experiment, preserves Blind E evidence, appends
   P evidence, and re-verifies selection before inference. Completed attempts,
   including Audit FAIL, use immutable four-file persistence with integrity checks.
7. **Validation layer.** D6.1 scores route and semantic Diagnosis against typed
   Human Gold; D6.2 aggregates exact metrics and paired Blind/Contrastive deltas;
   D6.3 freezes a 15-case suite; D6-R1/R2 acquire real-provider results with
   immutable full-run or sharded ledgers; D6-R3/R4/R5 collect successful shards,
   finalize human-reviewed semantic scores, and publish the final result artifact.

## 4. Questions and defensible answers

| Question | Answer |
| --- | --- |
| Why single PASS != reliability? | Repeated independent attempts expose operational failures and outcome variation; one sample cannot establish a stable rate. |
| Why Run vs Experiment? | Run owns execution/evidence; Experiment owns frozen repetition configuration, ordered child IDs, and aggregates. |
| Why separate Agent status and official evaluation? | Completion describes the process, while PASS/FAIL describes the configured test outcome. Neither substitutes for the other. |
| Why freeze baseline tests? | Candidate test edits must remain visible but cannot redefine the benchmark's official truth. |
| Why deterministic evidence before inference? | It makes the exact context inspectable and hashable and prevents hidden selection from changing the question. |
| Why Blind as headline? | It measures hypotheses from subject evidence without extra PASS comparison information. |
| Why Contrastive as secondary ablation? | It changes available evidence; it should be evaluated separately rather than silently improving the headline context. |
| How is the peer selected? | First eligible completed same-cell PASS in persisted Experiment run order, excluding the subject; match task/Agent/evaluator/historical provenance and verify Experiment configuration. |
| What if the selected peer's raw artifacts fail verification? | Fail closed; do not fall back to another peer. |
| Why isn't PASS a reference fix? | Tests passing does not identify a uniquely correct implementation or prove which difference caused the subject failure. |
| Why complete bounded source? | Untouched cross-file behavior may matter. Explicit bounds keep context deterministic; over-budget or unsupported input fails instead of invoking retrieval. |
| Can the provider change truth? | No. It emits hypotheses/abstention only; PatchBench owns official outcomes and identity/linkage. |
| Does Audit PASS establish correctness? | No. Even an absurd claim can pass structural and citation checks. Semantic validation needs human gold. |
| Why abstention? | Missing evidence should be represented explicitly, not forced into an unsupported family. Certainty is qualitative low/medium/high. |
| Why exact line refs? | A reviewer can locate the cited artifact span. LF-only, artifact-relative coordinates and paired-null empty citations prevent ambiguous offsets. |
| Why separate immutable artifacts? | Each inference attempt stays linked to its frozen Bundle and provider response identity without overwriting Run evidence or other attempts. |
| Why opt-in external LLM use? | Repository evidence is transmitted externally; the caller must explicitly authorize it. PatchBench does not classify private-repository safety. |
| What about prompt injection? | Evidence is framed as untrusted data and preserved exactly. The built-in adapter has no tools; this is not proof of adversarial prompt-injection security. |
| Is the provider sandboxed? | The request has no workspace handles, but arbitrary third-party provider code is not sandboxed by the protocol. OpenAI necessarily uses network access. |
| Is model output reproducible? | We record observed requested/returned models and SDK/request provenance; we do not freeze provider weights or promise identical external output. |
| What does Replay prove? | It checks the stored patch under the reconstructed evaluator boundary without re-running an Agent; it does not reproduce every historical host dependency. |

## 5. Current limitations — say this explicitly

Diagnosis validation infrastructure is implemented through Human-Gold scoring,
aggregate/paired metrics, a frozen 15-case suite, real-provider acquisition,
semantic score finalization and the final Validation V1 result. On the frozen
13 semantic cases, Blind scored 9/10 preferred Top-1 over non-abstention cases
and Contrastive scored 8/10; both modes had 0/3 abstention recall. The paired
comparison showed no family improvement from Contrastive and one family/audit
regression at `semantic-09`. These are bounded suite results, not statistical
significance, production readiness, or a claim that Contrastive is generally
worse.

V1.1 is the only current empirical coding-agent reliability release. Its 30/32
end-to-end PASS rate is 93.75%; 30/30 normally completed executions passed.
The two quota failures were retained, not replaced. Four purpose-built tasks in
one environment do not establish general reliability or Diagnosis quality.
Production patch signatures were 8/8/4/1 across streaming_events, request_signing,
atomic_batch, and cache_revalidation; these are exact signatures, not counts of
semantically distinct algorithms. Whole-patch diversity can be inflated by test edits.
See the [frozen final report](../evidence/v1.1/FINAL_REPORT.md).

## 6. Next work and resume wording

Next: human review/publication or a separately authorized future milestone.
Optional V2 context/service expansion is deferred. Current Diagnosis is
programmatic; there is no `patchbench diagnose` CLI.

Defensible resume wording: “Built a local coding-agent reliability harness with
frozen evaluation, historical patch Replay, and a 32-Run evidence release; added
reviewed evidence-grounded Diagnosis infrastructure with strict provider
contracts, deterministic citation auditing, Human-Gold validation contracts,
paired Blind/Contrastive metrics, immutable execution provenance, and a bounded
15-case Validation V1 result.” If giving numbers, specify the denominator and
suite: “On the frozen 13 semantic cases, Blind scored 9/10 preferred Top-1 over
non-abstention cases; Contrastive scored 8/10; both had 0/3 abstention recall.”
Do not call the gateway result an official OpenAI validation result or a broad
Diagnosis accuracy claim.

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
