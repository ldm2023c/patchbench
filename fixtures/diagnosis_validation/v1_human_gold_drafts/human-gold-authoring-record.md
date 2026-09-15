# Human Gold Authoring Record

Authoring basis: Blind evidence only. No PASS peer, Contrastive evidence, candidate generator, candidate construction tests, intended family metadata, or other non human-facing Blind packet evidence was used for semantic decisions.

Confirmation basis: semantic-01 and semantic-02 were individually confirmed by the human author; semantic-03 and semantic-14 were explicitly re-reviewed after the Blind audit and their acceptable-family expansions were confirmed; semantic-04 through semantic-13 and semantic-15 were batch-confirmed by the human author after reviewing the Blind-only first-round results and the Blind audit. No PASS peer, Contrastive evidence, candidate generator, candidate construction tests, intended-family metadata, or other non-human-facing evidence was used for these confirmations.

| case_id | human confirmation | should_abstain | preferred_family | acceptable_families | gold_sha256 |
|---|---|---:|---|---|---|
| semantic-01 | individually confirmed | false | incorrect_local_logic | incorrect_local_logic | 5fdf6b511e063fb6f856e0751688088379f3a5348be015c46144a9fe533fb6be |
| semantic-02 | individually confirmed | false | incorrect_local_logic | incorrect_local_logic | db4c9f39cd49e2ff82eaada6668f3dce58e63fdf118f67adcd8ee341358f80eb |
| semantic-03 | audit re-reviewed and confirmed | false | incomplete_cross_file_repair | incomplete_cross_file_repair, incorrect_local_logic | c93bd139d818842e1eac7e209445b3f2f46c4a1176cc9252c62036cf662b27e6 |
| semantic-04 | batch-confirmed after Blind-only review and audit | false | state_consistency_violation | state_consistency_violation | 5e834485f1dc79ce582e4f6c069cd3670f7afc2e6cd94adcfea7002d430bd1c6 |
| semantic-05 | batch-confirmed after Blind-only review and audit | false | partial_contract_handling | partial_contract_handling | 9c8b5e83830cbc91444587ec872b917f67abe6bd8229a97b2ac8e113e08a2975 |
| semantic-06 | final update request kept first-round delegated Gold | false | partial_contract_handling | partial_contract_handling | f6091ec2c99822d9c7ef629bf9db24a597215899a9e22e7776b0be7031eb8693 |
| semantic-07 | final update request kept first-round delegated Gold | false | state_consistency_violation | state_consistency_violation | 31c84e989cd1b5acc61b295a239859ffe5c362dfbd627a5cc32aa8ff951c6297 |
| semantic-08 | final update request kept first-round delegated Gold | false | state_consistency_violation | state_consistency_violation | 50c8397f712579afe1907864431e17663734503e0e0987c21ede24f76b0dff07 |
| semantic-09 | final update request kept first-round delegated Gold | false | regression_introduced | regression_introduced | c18311528a3d959cad20c154cf45bb67d4dbc4e4b339ad991a74050c145a2edc |
| semantic-10 | final update request kept first-round delegated Gold | false | incorrect_local_logic | incorrect_local_logic | 22035dc71a1f9797974982985799fce2dbbf40ddaf225253ce97060404fb1692 |
| semantic-11 | final update request kept first-round delegated Gold | false | regression_introduced | regression_introduced | 8b3e4487dde91c8aa4f4aac9d423075406b8e8e8f6027ac7c577eceabfaeeaaa |
| semantic-12 | final update request kept first-round delegated Gold | false | regression_introduced | regression_introduced | 2d82fdc2f97cb819fd2d670c0b21c64ef400fb931687f1655c36a87dcfd4d89e |
| semantic-13 | final update request kept first-round delegated Gold | false | partial_contract_handling | partial_contract_handling | 16e1e9628b4a771b970abf2e8a14d79a982fd41ca0f37654a3a40d5710169333 |
| semantic-14 | audit-confirmed acceptable-family expansion | false | regression_introduced | regression_introduced, incorrect_local_logic | fdddf78df37574449b82b6274922b471c14f9d945cfe6cef3c8482b114494857 |
| semantic-15 | final update request kept first-round delegated Gold | false | state_consistency_violation | state_consistency_violation | d367bca71afc4f7598b7fbc25ddf6dd3842d92d087b83781467dadf958f9f69d |

## Case Details

### semantic-01

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: incorrect_local_logic
- acceptable_families: incorrect_local_logic
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求访问必须同时满足成年与 active，active=False 时即使成年也应拒绝。
  - R2: 证明 subject patch / candidate source 将条件实现为 age >= 18 or active。
  - R3: 证明 official evaluation 中 allowed(20, False) 因返回 True 而失败。
- forbidden_claims:
  - F1: 不得将失败根因归因于 src/access.py 之外的其他模块、外部权限系统或运行时账户状态；当前 Blind evidence 未提供支持这些机制的证据。
- gold_sha256: 5fdf6b511e063fb6f856e0751688088379f3a5348be015c46144a9fe533fb6be

### semantic-02

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: incorrect_local_logic
- acceptable_families: incorrect_local_logic
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求的是上边界 cap 到 80，低于 80 的值应保持原样。
  - R2: 证明 subject patch / candidate source 将上界逻辑误改为 max(value, 80)。
  - R3: 证明 official evaluation 中 cap(20) 因返回 80 而失败。
- forbidden_claims:
  - F1: 不得声称失败涉及 src/limits.py 之外的其他模块、单位转换、配置加载或外部阈值来源；当前 Blind evidence 只支持单个函数中上下界逻辑写反导致失败。
- gold_sha256: db4c9f39cd49e2ff82eaada6668f3dce58e63fdf118f67adcd8ee341358f80eb

### semantic-03

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: incomplete_cross_file_repair
- acceptable_families: incomplete_cross_file_repair, incorrect_local_logic
- requirement_descriptions:
  - R1: 证明 public submit API 的 contract / frozen test 要求对混合大小写输入返回 lowercase normalized value。
  - R2: 证明 subject 在 parser.normalize 中实现了 lowercase normalization。
  - R3: 证明 subject 同时在 public API submit 中对 normalize(value) 的结果追加 upper 转换。
  - R4: 证明 official evaluation 中 submit("MiXeD") 实际返回 MIXED 而不是 mixed。
- forbidden_claims:
  - F1: 不得将失败根因归因于 src/api.py 和 src/parser.py 之外的模块、外部 normalization 服务或开发者意图；当前 Blind evidence 只支持 public API 与 parser 转换组合导致的结果。
- gold_sha256: c93bd139d818842e1eac7e209445b3f2f46c4a1176cc9252c62036cf662b27e6

### semantic-04

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: state_consistency_violation
- acceptable_families: state_consistency_violation
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 registry lookup 支持 png 并返回 image。
  - R2: 证明 lookup 同时依赖 SUPPORTED 与 HANDLERS 两个 registry 状态。
  - R3: 证明 subject 只向 HANDLERS 添加 png:image，未将 png 加入 SUPPORTED。
  - R4: 证明 official evaluation 中 lookup("png") 返回 None 而不是 image。
- forbidden_claims:
  - F1: 不得声称失败来自外部 registry、插件发现、配置加载或隐藏 handler 机制；当前 Blind evidence 只显示 src/registry.py 内 SUPPORTED 与 HANDLERS 不一致。
- gold_sha256: 5e834485f1dc79ce582e4f6c069cd3670f7afc2e6cd94adcfea7002d430bd1c6

### semantic-05

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: partial_contract_handling
- acceptable_families: partial_contract_handling
- requirement_descriptions:
  - R1: 证明 contract / frozen test 要求 explicit null timeout 使用默认值 30，同时字符串 timeout "8" 应解析为 8。
  - R2: 证明 subject 将 timeout 实现为 int(data.get("timeout", 30))。
  - R3: 证明 official evaluation 中 timeout({"timeout": None}) 对 None 调用 int 并抛出 TypeError。
- forbidden_claims:
  - F1: 不得声称失败来自配置文件、环境变量、外部默认值来源或单位换算；当前 Blind evidence 只支持 data 字典中 explicit None 未被作为默认值处理。
- gold_sha256: 9c8b5e83830cbc91444587ec872b917f67abe6bd8229a97b2ac8e113e08a2975

### semantic-06

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: partial_contract_handling
- acceptable_families: partial_contract_handling
- requirement_descriptions:
  - R1: 证明 contract / frozen test 要求 numeric identifier 转成文本，同时 textual identifier 必须保留原文本形式。
  - R2: 证明 subject 只为 int 输入新增特殊处理，非 int 仍执行 str(int(value))。
  - R3: 证明 official evaluation 中 identifier("007") 返回 "7" 而不是 "007"。
- forbidden_claims:
  - F1: 不得声称失败来自数据库 ID、序列化层、格式化配置或外部 identifier 系统；当前 Blind evidence 只支持 identifier 函数对 textual form 的处理不完整。
- gold_sha256: f6091ec2c99822d9c7ef629bf9db24a597215899a9e22e7776b0be7031eb8693

### semantic-07

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: state_consistency_violation
- acceptable_families: state_consistency_violation
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 rename 后 Store 的 data 和 names 两个 view 都反映新名称。
  - R2: 证明 Store 同时维护 data 与 names 两种状态表示。
  - R3: 证明 subject rename 只更新 data，未同步更新 names。
  - R4: 证明 official evaluation 中 names 仍包含 old 且缺少 new。
- forbidden_claims:
  - F1: 不得声称失败来自持久化层、并发 rename、外部索引或隐藏 Store backend；当前 Blind evidence 只显示 Store.data 与 Store.names 未保持一致。
- gold_sha256: 31c84e989cd1b5acc61b295a239859ffe5c362dfbd627a5cc32aa8ff951c6297

### semantic-08

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: state_consistency_violation
- acceptable_families: state_consistency_violation
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 Queue.add 同时更新 items、count 和 version。
  - R2: 证明 Queue 对象同时维护 items、count、version 三个 observable 状态。
  - R3: 证明 subject add 只 append items，未更新 count 或 version。
  - R4: 证明 official evaluation 中结果为 (["x"], 0, 0) 而不是 (["x"], 1, 1)。
- forbidden_claims:
  - F1: 不得声称失败来自外部队列服务、事务系统、并发控制或隐藏 metadata backend；当前 Blind evidence 只显示 Queue.items/count/version 未同步更新。
- gold_sha256: 50c8397f712579afe1907864431e17663734503e0e0987c21ede24f76b0dff07

### semantic-09

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: regression_introduced
- acceptable_families: regression_introduced
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求新增 opt-in excited rendering 时保留 legacy default output。
  - R2: 证明 base 默认 render(name) 返回带句号的 Hello 输出。
  - R3: 证明 subject 将 excited 参数默认值设为 True，使默认调用输出感叹号。
  - R4: 证明 official evaluation 中 render("Ada") 返回 Hello Ada! 而不是 Hello Ada.。
- forbidden_claims:
  - F1: 不得声称失败来自模板引擎、本地化、用户偏好配置或外部消息系统；当前 Blind evidence 只支持 render 默认参数改变破坏 legacy output。
- gold_sha256: c18311528a3d959cad20c154cf45bb67d4dbc4e4b339ad991a74050c145a2edc

### semantic-10

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: incorrect_local_logic
- acceptable_families: incorrect_local_logic
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求接受 0 但拒绝负数。
  - R2: 证明 subject 将边界条件实现为 value >= -1。
  - R3: 证明 official evaluation 中 accepted(-1) 错误返回 True。
- forbidden_claims:
  - F1: 不得声称失败来自外部阈值配置、数值单位转换或调用方预处理；当前 Blind evidence 只支持 accepted 函数中的边界条件错误。
- gold_sha256: 22035dc71a1f9797974982985799fce2dbbf40ddaf225253ce97060404fb1692

### semantic-11

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: regression_introduced
- acceptable_families: regression_introduced
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 padded mixed-case input 仍输出 documented lowercase trimmed result。
  - R2: 证明 base pipeline 通过 parse(v).strip() 与 emit(v).lower() 产生该 documented output。
  - R3: 证明 subject 将 parse 改为 strip("!") 且 emit 改为 upper()。
  - R4: 证明 official evaluation 中 process(" Mixed ") 返回 " MIXED " 而不是 "mixed"。
- forbidden_claims:
  - F1: 不得声称失败来自未出现的 pipeline stage、外部 parser/emitter、编码问题或运行时环境；当前 Blind evidence 只支持 src/pipeline.py 中 parse/emit 行为被改坏。
- gold_sha256: 8b3e4487dde91c8aa4f4aac9d423075406b8e8e8f6027ac7c577eceabfaeeaaa

### semantic-12

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: regression_introduced
- acceptable_families: regression_introduced
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 execute() 保持 configured safe mode 输出 safe。
  - R2: 证明 base policy MODE 为 safe，runner.execute 返回 mode()。
  - R3: 证明 subject 将 MODE 改为 fast，并让 execute 返回 mode()+"-cached"。
  - R4: 证明 official evaluation 中 execute() 返回 fast-cached 而不是 safe。
- forbidden_claims:
  - F1: 不得声称失败来自外部 policy 服务、真实缓存层、部署模式或环境变量；当前 Blind evidence 只支持 src/policy.py 与 src/runner.py 中的 source-level 行为改变。
- gold_sha256: 2d82fdc2f97cb819fd2d670c0b21c64ef400fb931687f1655c36a87dcfd4d89e

### semantic-13

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: partial_contract_handling
- acceptable_families: partial_contract_handling
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求选择 nonempty normalized values，输入 " a " 应输出 "a" 且空白值应被过滤。
  - R2: 证明 base normalization 使用 strip()，keep 对 normalized value 判空。
  - R3: 证明 subject 将 normalize 改为 rstrip()，只去除右侧空白。
  - R4: 证明 official evaluation 中 select([" a ", " ", "bc"]) 返回 [" a", "bc"] 而不是 ["a", "bc"]。
- forbidden_claims:
  - F1: 不得声称失败来自外部 whitespace 规则、输入读取层、排序逻辑或隐藏 filtering backend；当前 Blind evidence 只支持 normalize/keep/select 中对 normalized value 的处理不完整。
- gold_sha256: 16e1e9628b4a771b970abf2e8a14d79a982fd41ca0f37654a3a40d5710169333

### semantic-14

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: regression_introduced
- acceptable_families: regression_introduced, incorrect_local_logic
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 adapter unchanged 暴露 registered code values，adapt("a") 为 1 且 adapt("b") 为 2。
  - R2: 证明 base adapter 直接返回 code(v)，base registered code a 的值为 1。
  - R3: 证明 subject 添加 registered code b:2，但 adapter 将 code(v) 加 1 后返回。
  - R4: 证明 official evaluation 中 adapt("a"), adapt("b") 返回 (2, 3) 而不是 (1, 2)。
- forbidden_claims:
  - F1: 不得声称失败来自外部 code registry、adapter framework、序列化层或隐藏映射来源；当前 Blind evidence 只支持 src/adapter.py 对 registered code values 的局部变换破坏输出。
- gold_sha256: fdddf78df37574449b82b6274922b471c14f9d945cfe6cef3c8482b114494857

### semantic-15

- authoring_basis: Blind evidence only
- should_abstain: false
- preferred_family: state_consistency_violation
- acceptable_families: state_consistency_violation
- requirement_descriptions:
  - R1: 证明 task / frozen test 要求 cache-backed interface 在 put 后通过 get 返回 latest stored value。
  - R2: 证明 cache module 同时维护 DATA 与 CACHE，get 优先读 CACHE 再读 DATA。
  - R3: 证明 subject 预填 CACHE={"x":1}，但 put 仍只更新 DATA。
  - R4: 证明 official evaluation 中 put("x", 2) 后 get("x") 返回 1 而不是 2。
- forbidden_claims:
  - F1: 不得声称失败来自外部缓存服务、并发写入、持久化层或隐藏失效机制；当前 Blind evidence 只支持 DATA 与 CACHE 两个 module-level 状态未保持 latest-value 一致。
- gold_sha256: d367bca71afc4f7598b7fbc25ddf6dd3842d92d087b83781467dadf958f9f69d
