# PatchBench Interview Notes

这是一份面试前速查材料。所有表述以当前 M0–M5 实现、测试和运行证据为准，
不把未来方向写成已实现能力。

## 1. One-line positioning

**Coding Agent Reliability & Failure Analysis Platform**

PatchBench 是一个面向真实软件仓库的本地、可检查实验工具，用可复现的 Run、
重复 Experiment、可观察失败分类、描述性 PASS/FAIL 对比和历史补丁 Replay，
研究 coding agent 在同一任务与配置下是否稳定可靠。

## 2. 30-second pitch

我做 PatchBench 是因为 coding agent 成功一次，并不能说明它可靠。项目会把同一
任务放到固定 base commit 的全新 Git worktree 中，让 Agent 修改代码，再用 Git
捕获标准补丁并在 host 或 Docker 中评测。单次结果保存为 Run；同一配置可以连续
执行 N 次形成 Experiment，统计通过率、Agent 命令失败和超时。之后还能对已保存
结果做可观察失败分类、描述性 PASS/FAIL 对比，并在不重跑 Agent 的情况下 Replay
历史补丁。重点不是做排行榜，而是保留证据、区分失败边界并解释可靠性波动。

## 3. 2-minute project story

1. **问题：** 单次 PASS 不能回答同一 Agent 对同一任务是否稳定，也无法区分 Agent、Evaluation 与基础设施结果。
2. **原子 Run：** `TaskSpec` 固定仓库、base、prompt 和评测；Git worktree 隔离修改，Agent 在 host 执行，Git 捕获 canonical patch，Evaluator 在 host/Docker 运行，最后持久化 RunRecord 和证据。
3. **重复 Experiment：** 同一冻结配置串行执行 N 个独立 Run，每次使用新 Agent 和 worktree，分别聚合 Evaluation、Agent failure/timeout 与时长。
4. **M5 分析闭环：** FailureAnalysis 分类可观察条件，Comparison 比较明确的同任务 PASS/FAIL，Replay 在 caller TaskSpec base 应用历史 patch，并执行零个 Agent。
5. **关键边界：** Agent outcome != Evaluation outcome；infrastructure error 抛异常；Docker 只隔离 evaluator；Comparison 不证明因果；Replay 不还原完整历史环境。
6. **限制：** v1 没有并行、自动 pair selection、语义根因、完整环境快照、数据库、dashboard 或 benchmark leaderboard。

## 4. Architecture walkthrough

主流程可以从三个 application lifecycle 理解：

```text
TaskSpec
  → GitRepositoryManager 创建 fresh worktree
  → Agent protocol（FakeAgent / host-side CodexAdapter）
  → Git 捕获 canonical patch
  → CommandEvaluator 或 SandboxCommandEvaluator
  → RunRecord
  → FilesystemArtifactStore

RunRecord × N → ExperimentRecord + ExperimentAggregate
RunRecord + patch → FailureAnalysis / PassFailComparison
historical RunRecord + patch → ReplayRecord
```

`TaskSpec` 负责 YAML 校验和相对路径解析；`GitRepositoryManager` 校验仓库/base、管理
worktree，并以 staged binary diff 作为 patch 真相。Agent request 只有 workspace、
prompt、timeout，result 返回 status、exit code、stdout/stderr 和时长；FakeAgent 是
确定性替身，CodexAdapter 是 host-side 真实实现。Evaluator 由命令 exit code 决定
PASS/FAIL，Docker 路径通过 `SandboxCommandEvaluator`。RunRecord 与 artifact store
分离结构化完成态和文件证据；Experiment 只保存配置、聚合与 child IDs；纯 domain
FailureAnalysis/Comparison 不做 I/O；Replay 引用来源 Run，不复制 source patch。

## 5. Key design decisions and tradeoffs

### Why Run and Experiment are separate concepts

Run 是能独立执行、评测和保存证据的原子单位；Experiment 只负责冻结共同配置、
连续产生独立 Runs 并聚合。这样单次运行逻辑不会为了统计而变形，失败时已完成的
child Run 也仍是有效独立证据。

### Why every Run uses a fresh Git worktree

每次从已验证 base commit 开始，隔离前一次执行的修改与 evaluator 副作用，同时
复用本地 Git object store，比每次完整 clone 更轻。代价是必须可靠清理 worktree
注册和目录。

### Why Git patch capture is the source of truth

不依赖 Agent 自报“改了什么”。`git add -A` 后生成 cached binary diff，可覆盖已跟踪
修改、删除、新文件和二进制内容；并且在 evaluation 前捕获，避免评测副作用污染
Agent patch。代价是补丁仍可能包含 Agent 自己生成但不理想的文件。

### Why Agent outcome and Evaluation outcome are independent

Agent 命令退出非零或超时后，workspace 仍可能包含可通过评测的有效修改。因此只要
Agent execution 确实启动并返回正常 outcome，PatchBench 继续捕获 patch 和评测，
分别记录 Agent status 与 Evaluation PASS/FAIL。

### Why infrastructure errors do not become normal Run failure categories

无法加载任务、创建 worktree、启动/安全管理 Agent、管理 Docker 或写 artifact 时，
系统没有可信的完整 Run 观测。伪造 RunRecord 会污染可靠性统计，所以这类错误中止并
传播；`FailureAnalysis` 只处理已经完成的 RunRecord。

### Why Docker is evaluator isolation rather than full Agent sandboxing

Codex 认证、CLI 与进程管理都在 host 上；Docker 只挂载 disposable worktree 并运行
评测命令。这让 Agent 集成和 evaluator 隔离保持独立。它提供实用隔离，但不宣称是
生产级 hostile multi-tenant 安全边界。

### Why Experiment v1 is sequential

串行优先能直接复用成熟的单 Run lifecycle，保持清理顺序和 artifact 归属清晰，
避免并发 worktree、资源争用和外部 provider 限流问题。代价是 N 次运行总耗时线性
增长；并行化属于未来优化。

### Why FailureAnalysis is observable rather than semantic

当前四类 `AGENT_COMMAND_FAILED`、`AGENT_TIMED_OUT`、`NO_PATCH`、`TEST_FAILED`
都能从 RunRecord 与 patch 直接确定，结果可重复、可测试。它不会把“上下文不足”或
“理解错误”这类推断冒充事实。

### Why PassFailComparison is descriptive rather than causal

一个 PASS 和一个 FAIL 之间的 status、patch 与时长差异只是相关证据。当前 API 要求
调用方明确提供同任务、不同 ID 的 PASS/FAIL roles，不自动选 pair，也不声称某项差异
导致失败。

### Why Replay reuses a patch and invokes zero Agents

Replay 要回答的是“保存的补丁现在应用到指定 base 后会得到什么评测结果”，而不是
“Agent 能否再次生成相同补丁”。不调用 Agent 避免把新的模型随机性混进补丁验证。

### What Replay proves and does not prove

Replay 证明 canonical patch 能否应用到调用方 TaskSpec base，并在当前选择的 host 或
Docker evaluator 下得到 PASS/FAIL，以及是否与来源 outcome 一致。它不证明完整历史
环境、依赖、provider 行为或模型状态被重建。

## 6. M4 — Repeated Experiments

M4 把“同任务/同配置 × N”变成一等领域对象：

- `ExperimentConfiguration` 冻结 agent name、requested model、Agent timeout 和
  evaluation backend；
- orchestrator 只加载一次 TaskSpec，串行调用现有单 Run lifecycle；
- Agent factory 为每个 child Run 创建新 Agent，worktree 和 run ID 也各自独立；
- `ExperimentAggregate` 直接从 child RunRecords 计算 Evaluation PASS/FAIL/pass rate、
  Agent command failure/timeout 和总计/均值/最小/最大时长；
- `requested_runs == len(run_ids) == aggregate.run_count`；
- hard setup/infrastructure failure 中止 Experiment 并传播，不保存 partial record，
  但此前已完成的 standalone child Run artifacts 可以保留。

相比手工执行 CLI N 次，它冻结并持久化共同配置、自动建立 child membership、使用
一致公式聚合独立 outcome，并保留每个 Run 的可追溯证据；它不宣称统计显著性。

## 7. M5 — Failure / Comparison / Replay

- **M5.1 FailureAnalysis：** 把 completed RunRecord 与已加载 patch 映射成有序、
  deterministic、multi-label 的直接可观察分类。
- **M5.2 PassFailComparison：** 复用 M5.1 作为唯一 taxonomy 来源，描述一个明确
  PASS 与一个明确 FAIL 的 Agent status、failure categories、patch presence/equality
  和 `FAIL duration - PASS duration`。
- **M5.3 Replay：** 从不可变来源 Run artifact 读取 metadata 和 patch，新建工作区并
  重新评测，保存独立 Replay metadata/test log，来源 artifact 保持不变。

三者形成“观察失败 → 对照证据 → 重放已有补丁”的最小分析闭环，但不升级为语义
诊断或因果推断系统。

## 8. Failure semantics cheat sheet

| 情况 | 正常 completed observation？ | 行为 |
|---|---:|---|
| Agent `COMMAND_FAILED` | 是 | 继续 patch capture 与 Evaluation；可与 PASS 共存 |
| Agent `TIMED_OUT` | 是 | 安全终止后继续 patch capture 与 Evaluation；可与 PASS/FAIL 独立组合 |
| Evaluation PASS / FAIL | 是 | 由 evaluator exit code 决定，不由 Agent status 推断 |
| setup / infrastructure failure | 否 | 中止并传播异常，不伪造 Run/Experiment/Replay completed record |
| Replay outcome mismatch | 是 | 记录 `outcome_matches=false`，不是基础设施错误 |

## 9. Reproducibility boundaries

PatchBench v1 以 caller-supplied TaskSpec 约束 repository/base、prompt 和
evaluation，每次 Run 使用 fresh worktree，并持久化结构化运行证据，包括 prompt、
canonical patch、evaluation logs 以及 Run/Experiment/Replay artifacts。它没有完全
冻结外部模型/provider、网络、host 依赖、Codex 认证状态或历史 Docker image/依赖。
因此“可复现”指受控起点、可检查 patch、明确 evaluator 与持久化证据，不是
bit-for-bit 重建所有外部条件。

## 10. Hardest engineering problems / what was learned

1. **可靠性 outcome 与基础设施失败：** 不能把不完整观测写成普通 FAIL，否则会
   污染 pass rate 和失败统计。
2. **超时清理：** CodexAdapter 终止/reap host process group，Docker timeout 销毁
   container，外层仍清理 worktree。
3. **完整 patch：** 从会漏 untracked files 的 `git diff HEAD` 改为 `git add -A` 加
   cached binary diff，并锁定修改、删除、新文件和二进制能力。
4. **Experiment 不破坏 Run 原子性：** 纯聚合复用单 Run lifecycle，并明确 hard
   failure 后 child artifact 的保留边界。
5. **安全历史读取与 Replay：** 限制 Run ID 为 results 的直接子目录，重新校验
   metadata/ID；把“生成补丁”和“验证补丁”拆开，Replay 不引入新 Agent 随机性。

## 11. Likely interviewer questions

1. **为什么不手工跑 Codex N 次再算通过率？** 手工方式难以保证相同起点和配置，也缺少统一 child IDs、artifact ownership、失败语义与可重复聚合公式。
2. **为什么分开 Run 与 Experiment？** Run 是独立证据和清理单位；Experiment 是冻结配置、有序 membership 与聚合，不应吞掉单次执行语义。
3. **为什么 `COMMAND_FAILED` 还能评测？** 命令非零不代表 workspace 没有有效修改；评测真实代码状态比从 Agent exit code 猜测更可靠。
4. **为什么 infrastructure failure 不是另一个 failure category？** 因为没有可信完整 RunRecord；纳入 completed-run taxonomy 会让可靠性分母失真。
5. **为什么 worktree 而不是每次 clone？** worktree 复用 object store，同时提供指定 commit 的独立目录；代价是必须严格清理 Git registration。
6. **为什么 Git 是 patch 真相源？** Git 观察实际文件状态，不依赖 Agent 自述，并能表示修改、删除、新增和二进制差异。
7. **为什么 Agent 在 host、evaluation 可在 Docker？** Codex 需要 host CLI/认证，评测只需窄 command boundary，可独立隔离。
8. **为什么不把 Agent 也放进 Docker？** 当前范围不含认证注入、网络策略、依赖 provisioning 和更复杂安全模型；不能假装已经解决。
9. **为什么 Experiment 是串行？** 先验证 independence、cleanup、aggregation 和 evidence ownership；并发会引入资源争用与 provider 限流。
10. **FailureAnalysis 告诉我什么？** 它稳定回答哪些直接可观察条件出现，不回答深层语义根因。
11. **为什么 Comparison 不是 root-cause analysis？** 两个样本的差异不能证明因果，当前只描述 status、categories、patch 与 duration 差异。
12. **Replay 到底验证什么？** 验证保存 patch 在 caller TaskSpec base 和当前 evaluator 下的结果，并记录它是否匹配来源 outcome。
13. **为什么 Replay 不重跑 Agent？** 为隔离补丁可重现性，避免新的 Agent 随机性。
14. **如何保证 Replay 不修改来源 artifact？** 只读加载来源 metadata/patch，在新 worktree 评测，并把新证据写到独立 replay directory。
15. **如果有更多时间下一步做什么？** 优先补 environment fingerprint/provenance，再考虑自动 pair selection；并行化要在证据完备后做。
16. **最难的部分是什么？** 设计不混淆 Agent、Evaluation 与 infrastructure 的生命周期，让 timeout、patch、artifact cleanup 都服从该边界。

## 12. Resume-ready bullets

- 设计面向真实 Git 仓库的 coding-agent 可复现实验流水线：以 detached worktree 隔离 Run，在 host 执行 Agent，用 Git 捕获 binary patch，支持 host/Docker 评测并持久化证据。
- 实现同任务同配置的 N 次独立重复实验，聚合通过率、Agent 失败/超时与耗时指标，并保留每次运行的独立证据，用于分析 coding-agent 结果波动。
- 实现基于运行证据的确定性失败归类、成功/失败运行对比与历史补丁重放；Replay 不重新调用 Agent，可独立验证历史 patch 的评测结果与 outcome match。

以上 bullet 没有使用准确率提升、仓库规模、生产部署、分布式执行或 benchmark 成绩
等缺乏证据的量化/能力声明。

## 13. What I would improve next

优先级一是增加 environment fingerprint 和更强 provenance，例如记录 evaluator image
digest、关键工具版本与依赖摘要，让 Replay 边界更可见。优先级二是基于 Experiment
做自动 PASS/FAIL pair selection 和更丰富但仍可验证的分析。之后才考虑并行执行，
因为它会引入资源隔离、调度和 provider 限流问题。RepoLens/RAG 属于 Optional V2，
必须用下游可靠性收益验证，不能只做展示。

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
