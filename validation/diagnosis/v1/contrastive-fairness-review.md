# Contrastive Fairness Review

Question: Does the canonical PASS peer make the already-locked Human Gold unfair or invalid?

Do not relabel, replace cases, or edit Gold in this packet. Record human confirmation only in contrastive-fairness-review.json.

## semantic-01

- locked_gold_sha256: 5fdf6b511e063fb6f856e0751688088379f3a5348be015c46144a9fe533fb6be
- subject_evidence_sha256: d85357837152a84f6c5757d03665e23b96f7f95599cc9551c805737984c9e4ce
- blind_bundle_sha256: 303fe9b08afee30d7496344ad22681ec4dd14399714305a9de481452c0208572
- contrastive_bundle_sha256: b3bd69db4f02713969ac3c3503d2087cb5dddf659572edd42c0d1113ac156464

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "incorrect_local_logic"
- acceptable_families: ["incorrect_local_logic"]

Required evidence:

- R1: 证明 task / frozen test 要求访问必须同时满足成年与 active，active=False 时即使成年也应拒绝。
- R2: 证明 subject patch / candidate source 将条件实现为 age >= 18 or active。
- R3: 证明 official evaluation 中 allowed(20, False) 因返回 True 而失败。

Forbidden claims:

- F1: 不得将失败根因归因于 src/access.py 之外的其他模块、外部权限系统或运行时账户状态；当前 Blind evidence 未提供支持这些机制的证据。

Canonical peer identity:

- peer: semantic-01-peers[0] -> semantic-01-peer
- peer_selection_sha256: ffa11c245959f8877e6253b549de97198b96064e72c358e825d09de759bb4440
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 0361459ad359e57d88131ff9464195e160b9058f5fad3b0e1b4d2ba7dd1b5ac7
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_access (_patchbench_frozen_0.Contract.test_access) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 4fb6f7b9e1e18eb8bd9a96c6587e1a5905e9c45ce20600d00dfe82bd89928938
- source_state: None

```text
diff --git a/src/access.py b/src/access.py
index 6f96bd2..91523ab 100644
--- a/src/access.py
+++ b/src/access.py
@@ -1,2 +1,2 @@
 def allowed(age, active):
-    return age >= 18
+    return age >= 18 and active

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/access.py

- artifact_sha256: c3e55530373593d43ff9488869999d64016545bfe4fca3199b863948bbf1aa09
- source_state: candidate

```text
def allowed(age, active):
    return age >= 18 and active

```

## semantic-02

- locked_gold_sha256: db4c9f39cd49e2ff82eaada6668f3dce58e63fdf118f67adcd8ee341358f80eb
- subject_evidence_sha256: 6049bbb3e378b7fde577672a7c180b53dc9b7ee9a036c56cdfb050fa6d6a7e92
- blind_bundle_sha256: 20eb8d4d5fdd46634ba65d5f3043b3c7d0b39387785bf4b381c2ba386f9f977c
- contrastive_bundle_sha256: 8618bc020ad872a01fbf01e6922c1946957cc809d43712795272f970afca60b4

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "incorrect_local_logic"
- acceptable_families: ["incorrect_local_logic"]

Required evidence:

- R1: 证明 task / frozen test 要求的是上边界 cap 到 80，低于 80 的值应保持原样。
- R2: 证明 subject patch / candidate source 将上界逻辑误改为 max(value, 80)。
- R3: 证明 official evaluation 中 cap(20) 因返回 80 而失败。

Forbidden claims:

- F1: 不得声称失败涉及 src/limits.py 之外的其他模块、单位转换、配置加载或外部阈值来源；当前 Blind evidence 只支持单个函数中上下界逻辑写反导致失败。

Canonical peer identity:

- peer: semantic-02-peers[0] -> semantic-02-peer
- peer_selection_sha256: 1c72badb269bbf9fff9e443fcd875fe4dd391adde9387c0b4af6a656f3ffb4a8
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 635bc21e299b90db7dc275fec8fc3e24fdaee1cdf9d5378e098418bec3ad861e
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_cap (_patchbench_frozen_0.Contract.test_cap) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 33eac60a6bf8e4bfc797a99f205be02c9b604749d77fa337d70bb4383bca0c77
- source_state: None

```text
diff --git a/src/limits.py b/src/limits.py
index 41f3e39..d79094d 100644
--- a/src/limits.py
+++ b/src/limits.py
@@ -1,2 +1,2 @@
 def cap(value):
-    return min(value, 100)
+    return min(value, 80)

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/limits.py

- artifact_sha256: e146511ab78dd49e1177f5d8ea61de8a601e23cfa67da4419d75df0edee68021
- source_state: candidate

```text
def cap(value):
    return min(value, 80)

```

## semantic-05

- locked_gold_sha256: 9c8b5e83830cbc91444587ec872b917f67abe6bd8229a97b2ac8e113e08a2975
- subject_evidence_sha256: ad6a0385de1b10bb91ef6316c59b0fa01b7b61bca1c7e7db49a0982722abff6a
- blind_bundle_sha256: 03ca19d38762427b9d6f232fec35379670694003f17be171ab07b84e734ce6a5
- contrastive_bundle_sha256: ed3bd6899bf270b1cb706208272036ca57c75453ed7ea2ad69f70a7e2cd6f99c

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "partial_contract_handling"
- acceptable_families: ["partial_contract_handling"]

Required evidence:

- R1: 证明 contract / frozen test 要求 explicit null timeout 使用默认值 30，同时字符串 timeout "8" 应解析为 8。
- R2: 证明 subject 将 timeout 实现为 int(data.get("timeout", 30))。
- R3: 证明 official evaluation 中 timeout({"timeout": None}) 对 None 调用 int 并抛出 TypeError。

Forbidden claims:

- F1: 不得声称失败来自配置文件、环境变量、外部默认值来源或单位换算；当前 Blind evidence 只支持 data 字典中 explicit None 未被作为默认值处理。

Canonical peer identity:

- peer: semantic-05-peers[0] -> semantic-05-peer
- peer_selection_sha256: d8a73b8c222ef34f5c2fab5e319e04cbcc9b6423c2a2e585fd7e1b334b7bffeb
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 12586061d1056f1f667b494d1d3fe0a44cf6c230456f8afc93dcd772f140bd54
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_timeout (_patchbench_frozen_0.Contract.test_timeout) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 923df95c743fd4ece501c3cb3b034816f6b6ec2efd535f1a801e69118a13f36d
- source_state: None

```text
diff --git a/src/config.py b/src/config.py
index 4f82769..7164009 100644
--- a/src/config.py
+++ b/src/config.py
@@ -1,2 +1,3 @@
 def timeout(data):
- return data.get('timeout',30)
+ value=data.get('timeout')
+ return 30 if value is None else int(value)

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/config.py

- artifact_sha256: e13083e9f0f7bcf88598ae6818bb457aa5e4b62a4df94ddf538e95388db3ea85
- source_state: candidate

```text
def timeout(data):
 value=data.get('timeout')
 return 30 if value is None else int(value)

```

## semantic-06

- locked_gold_sha256: f6091ec2c99822d9c7ef629bf9db24a597215899a9e22e7776b0be7031eb8693
- subject_evidence_sha256: 7d8fafaba6893ae28f6a6f60bc7809da7e9eaddbf9d06e447186e1b1a5ce2ac1
- blind_bundle_sha256: 4342758429936c98642c706cd7c39838e06ca77253ccebc14601fc58788616be
- contrastive_bundle_sha256: e5d50c1ac7ad142d28e111ecaf7e234014a25aecfb94034457e180951653d9f2

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "partial_contract_handling"
- acceptable_families: ["partial_contract_handling"]

Required evidence:

- R1: 证明 contract / frozen test 要求 numeric identifier 转成文本，同时 textual identifier 必须保留原文本形式。
- R2: 证明 subject 只为 int 输入新增特殊处理，非 int 仍执行 str(int(value))。
- R3: 证明 official evaluation 中 identifier("007") 返回 "7" 而不是 "007"。

Forbidden claims:

- F1: 不得声称失败来自数据库 ID、序列化层、格式化配置或外部 identifier 系统；当前 Blind evidence 只支持 identifier 函数对 textual form 的处理不完整。

Canonical peer identity:

- peer: semantic-06-peers[0] -> semantic-06-peer
- peer_selection_sha256: 1c541116436711100f81d39af0fc68e96b0368b07ed907742c0a708d5daf1d64
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 8155290fe593150b1bb02fae07ab9976d216c6855506d6eb9ccd5ddd0945c56a
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_forms (_patchbench_frozen_0.Contract.test_forms) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 059ffd818748e3e5b9a5c7f839ace4529bfc9a3675c08a520515284066d67c3f
- source_state: None

```text
diff --git a/src/identity.py b/src/identity.py
index cef97e7..6c548aa 100644
--- a/src/identity.py
+++ b/src/identity.py
@@ -1,2 +1,2 @@
 def identifier(value):
- return str(int(value))
+ return str(value)

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/identity.py

- artifact_sha256: e7a87a20426b75750da1a59fdbfc833773654bd195b845ed1d2b7fc48f8979db
- source_state: candidate

```text
def identifier(value):
 return str(value)

```

## semantic-07

- locked_gold_sha256: 31c84e989cd1b5acc61b295a239859ffe5c362dfbd627a5cc32aa8ff951c6297
- subject_evidence_sha256: 127c58a8ce1fd65a8ad5c8f60ba1f0cb1a2f02bfdcafbca5cf5992522b8fef38
- blind_bundle_sha256: 0d77196933dac3487840a0ee40bc9bf7c82f08e563dbb49f93e6d23f487383aa
- contrastive_bundle_sha256: c76864e636be0fd283d0e6bfbad2456b2a1d7bb04583287b7cdc954becc08816

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "state_consistency_violation"
- acceptable_families: ["state_consistency_violation"]

Required evidence:

- R1: 证明 task / frozen test 要求 rename 后 Store 的 data 和 names 两个 view 都反映新名称。
- R2: 证明 Store 同时维护 data 与 names 两种状态表示。
- R3: 证明 subject rename 只更新 data，未同步更新 names。
- R4: 证明 official evaluation 中 names 仍包含 old 且缺少 new。

Forbidden claims:

- F1: 不得声称失败来自持久化层、并发 rename、外部索引或隐藏 Store backend；当前 Blind evidence 只显示 Store.data 与 Store.names 未保持一致。

Canonical peer identity:

- peer: semantic-07-peers[0] -> semantic-07-peer
- peer_selection_sha256: 6e859f38e925df4f71070f4fa168e47659782423eb7abd77c4efe07aaa586aed
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 90fd95a4de07cd4bf046c760a11eb041cfacab9a5a042a47a0dcd9c113e13735
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_rename (_patchbench_frozen_0.Contract.test_rename) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 94689155a4cc210b6d7283f71df1d0fc76512fa940dc661ac7aa9562223d69ec
- source_state: None

```text
diff --git a/src/store.py b/src/store.py
index 646ad8e..a26a51c 100644
--- a/src/store.py
+++ b/src/store.py
@@ -1,3 +1,4 @@
 class Store:
  def __init__(self): self.data={'old':1}; self.names={'old'}
- def rename(self,old,new): pass
+ def rename(self,old,new):
+  self.data[new]=self.data.pop(old); self.names.remove(old); self.names.add(new)

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/store.py

- artifact_sha256: df3dfc929bdfdaa9994ea3a08e78c0c5903f8c1b579c804c575766b3f61709f1
- source_state: candidate

```text
class Store:
 def __init__(self): self.data={'old':1}; self.names={'old'}
 def rename(self,old,new):
  self.data[new]=self.data.pop(old); self.names.remove(old); self.names.add(new)

```

## semantic-08

- locked_gold_sha256: 50c8397f712579afe1907864431e17663734503e0e0987c21ede24f76b0dff07
- subject_evidence_sha256: 57251368f4e18a676c8f5b11b68ed65ddd4d66516be39ea55faaed6b9d183995
- blind_bundle_sha256: 76cf9c4830301ab36a8c382e0c1d17f0ee75431c70f1b754d18c1fc020bf213a
- contrastive_bundle_sha256: 5678782f3dbc82aced05c48833b510033aebf23375db2336213222c8ef10432b

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "state_consistency_violation"
- acceptable_families: ["state_consistency_violation"]

Required evidence:

- R1: 证明 task / frozen test 要求 Queue.add 同时更新 items、count 和 version。
- R2: 证明 Queue 对象同时维护 items、count、version 三个 observable 状态。
- R3: 证明 subject add 只 append items，未更新 count 或 version。
- R4: 证明 official evaluation 中结果为 (["x"], 0, 0) 而不是 (["x"], 1, 1)。

Forbidden claims:

- F1: 不得声称失败来自外部队列服务、事务系统、并发控制或隐藏 metadata backend；当前 Blind evidence 只显示 Queue.items/count/version 未同步更新。

Canonical peer identity:

- peer: semantic-08-peers[0] -> semantic-08-peer
- peer_selection_sha256: 6b7d6799215b995cb8d700775f0bc2e3492a6f1ea820171488b818ab5f902f4a
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: b69674e651b7a011ae4a49bc2392b15c0164c0e777dab2216793f37d1c2433bc
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_add (_patchbench_frozen_0.Contract.test_add) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 4a90546e8d63189f8dd8267bb09727627002db6318697e1a74b47aba17e8e4a3
- source_state: None

```text
diff --git a/src/queue.py b/src/queue.py
index ca63e02..a338910 100644
--- a/src/queue.py
+++ b/src/queue.py
@@ -1,3 +1,3 @@
 class Queue:
  def __init__(self): self.items=[]; self.count=0; self.version=0
- def add(self,item): pass
+ def add(self,item): self.items.append(item); self.count+=1; self.version+=1

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/queue.py

- artifact_sha256: 244548e1d60499c44a12be6ca141926b901519206f936b017eedbbf2ac84ef22
- source_state: candidate

```text
class Queue:
 def __init__(self): self.items=[]; self.count=0; self.version=0
 def add(self,item): self.items.append(item); self.count+=1; self.version+=1

```

## semantic-09

- locked_gold_sha256: c18311528a3d959cad20c154cf45bb67d4dbc4e4b339ad991a74050c145a2edc
- subject_evidence_sha256: c2ff36bbb9db7de73566f8425c347785bdf46012533f6f916b622d5f75bc16a8
- blind_bundle_sha256: 7255540ce37c628e5dd8351e97e9d9bf50f04f6d997034f43e39108aa37507a4
- contrastive_bundle_sha256: 14f15e45a0d8ca54c5fb1e5bd692c7df958341d5908bb549d5472b6c1d405047

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "regression_introduced"
- acceptable_families: ["regression_introduced"]

Required evidence:

- R1: 证明 task / frozen test 要求新增 opt-in excited rendering 时保留 legacy default output。
- R2: 证明 base 默认 render(name) 返回带句号的 Hello 输出。
- R3: 证明 subject 将 excited 参数默认值设为 True，使默认调用输出感叹号。
- R4: 证明 official evaluation 中 render("Ada") 返回 Hello Ada! 而不是 Hello Ada.。

Forbidden claims:

- F1: 不得声称失败来自模板引擎、本地化、用户偏好配置或外部消息系统；当前 Blind evidence 只支持 render 默认参数改变破坏 legacy output。

Canonical peer identity:

- peer: semantic-09-peers[0] -> semantic-09-peer
- peer_selection_sha256: a2a75583543a3c93494b9614504bac2f5b50fbe679792ce54e867d26606f1a37
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 6dd04a704a150c01ae723b9e5873eb08cd993edecf6709b425a9b779dab892db
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_render (_patchbench_frozen_0.Contract.test_render) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: ac75cf0973ad03feded9ab7e8b8689aa1df5ca1636e0249c7690b2009797279b
- source_state: None

```text
diff --git a/src/message.py b/src/message.py
index 379d142..23ab416 100644
--- a/src/message.py
+++ b/src/message.py
@@ -1,2 +1,2 @@
-def render(name):
- return 'Hello '+name+'.'
+def render(name, excited=False):
+ return ('Hello '+name)+('!' if excited else '.')

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/message.py

- artifact_sha256: 15577249dbf91b2da6bc9fa7eb1e3fcc7d07ee2bfdbc099eb4ee7998fa8abadc
- source_state: candidate

```text
def render(name, excited=False):
 return ('Hello '+name)+('!' if excited else '.')

```

## semantic-11

- locked_gold_sha256: 8b3e4487dde91c8aa4f4aac9d423075406b8e8e8f6027ac7c577eceabfaeeaaa
- subject_evidence_sha256: 6572541f3b18eb9d619a902086c342cf156fce2dda266149bf8908604eda8553
- blind_bundle_sha256: 47158b050d0b2e90c87cf6e1db890e59e8a08683478d263f4c5d68166b9e87fd
- contrastive_bundle_sha256: 5dfec6a3bb211cc819cf58c643caddd48021ed3bc684fe00d86d90a11a03adc9

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "regression_introduced"
- acceptable_families: ["regression_introduced"]

Required evidence:

- R1: 证明 task / frozen test 要求 padded mixed-case input 仍输出 documented lowercase trimmed result。
- R2: 证明 base pipeline 通过 parse(v).strip() 与 emit(v).lower() 产生该 documented output。
- R3: 证明 subject 将 parse 改为 strip("!") 且 emit 改为 upper()。
- R4: 证明 official evaluation 中 process(" Mixed ") 返回 " MIXED " 而不是 "mixed"。

Forbidden claims:

- F1: 不得声称失败来自未出现的 pipeline stage、外部 parser/emitter、编码问题或运行时环境；当前 Blind evidence 只支持 src/pipeline.py 中 parse/emit 行为被改坏。

Canonical peer identity:

- peer: semantic-11-peers[0] -> semantic-11-peer
- peer_selection_sha256: 3c661c92f51e215ca9596c2a2be42e129b9124e2f48b5573980e9b8e97819c76
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: b68e54b19c69ab463d992849a6c754575ea78cf9ff92d0f64c4901b39b2d112e
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_process (_patchbench_frozen_0.Contract.test_process) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: None

```text

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/pipeline.py

- artifact_sha256: 68a7e31967fc19511dfda33573c023cc1f652d0da1fd8515fd51031e45a9078b
- source_state: candidate

```text
def parse(v): return v.strip()
def emit(v): return v.lower()
def process(v): return emit(parse(v))

```

## semantic-16

- locked_gold_sha256: 255656e11e8ceb6da5c3cc36f715872cf741cc237e1d478735b793cca0132a12
- subject_evidence_sha256: 7066db000de8293e623ba11edd4607ee0d18ec1e593240d26f898180845dca9f
- blind_bundle_sha256: 6fa04c460902b85440d75a68893fddc617f7c7f7dd0b49e28cfc76f69b9fedaa
- contrastive_bundle_sha256: 5649e0c229b7eaaea7feea9b7f445be2bc3590da6ee0c8b8c91975ad6aa30281

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "incomplete_cross_file_repair"
- acceptable_families: ["incomplete_cross_file_repair"]

Required evidence:

- R1: Prove the public command interface must support the archive action.
- R2: Prove the subject changed engine.archive() output but left the public command routing table without an archive handler.
- R3: Prove official evaluation fails because execute('archive', ...) cannot find an archive handler.

Forbidden claims:

- F1: Do not claim the failure is caused by engine.archive() returning the wrong archive string; Blind evidence shows the observed failure is missing public command routing for 'archive'.

Canonical peer identity:

- peer: semantic-16-peers[0] -> semantic-16-peer
- peer_selection_sha256: 956bd168df0fd13648b47bb090a72a9f13b93fd37daa0c5db6d5fad9d0200a2f
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: fb79fdcde3f6df3feca56295153a298c82f30340ddcce00362c40b16da92e465
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_archive (_patchbench_frozen_0.Contract.test_archive) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: e0bbd6a3081aa271accdd5be639e8f525d381b9550f01f51ca916efc3c0c30a8
- source_state: None

```text
diff --git a/src/commands.py b/src/commands.py
index 413acf3..fc468fb 100644
--- a/src/commands.py
+++ b/src/commands.py
@@ -1,3 +1,3 @@
 from .engine import archive
-HANDLERS={'store':archive}
+HANDLERS={'store':archive,'archive':archive}
 def execute(action,name): return HANDLERS[action](name)
diff --git a/src/engine.py b/src/engine.py
index 0f3872a..f27ff75 100644
--- a/src/engine.py
+++ b/src/engine.py
@@ -1,2 +1,2 @@
 def archive(name):
- return 'stored:'+name
+ return 'archived:'+name

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/commands.py

- artifact_sha256: f7a7b50a2659a1b6bee19c77d3fe19330073a3de7ac6313160dc2f72785032e0
- source_state: candidate

```text
from .engine import archive
HANDLERS={'store':archive,'archive':archive}
def execute(action,name): return HANDLERS[action](name)

```

### P005 peer_source src/engine.py

- artifact_sha256: c7e997ced4e89763d6225269afb279751c4f66d019eb1809a650de549b1aae48
- source_state: candidate

```text
def archive(name):
 return 'archived:'+name

```

## semantic-17

- locked_gold_sha256: c9c5721f3c8d6b32eb491cc3bd97c462b72ba2c9e0d31853bbe61d58ef07a874
- subject_evidence_sha256: b53ef7150bd8cc42dc1fa08e8f0264625afdd19ef2a9cdb40df335763b19fb47
- blind_bundle_sha256: 985c01d5006213573ec59a854773072f6d091d842afa32e7dd5711be77ddc9bf
- contrastive_bundle_sha256: 6dfe20fc1a29f33077742388f2e1c11d9cea9282da375f7d21ac36de17857c56

Locked Human Gold summary:

- should_abstain: False
- preferred_family: "incomplete_cross_file_repair"
- acceptable_families: ["incomplete_cross_file_repair"]

Required evidence:

- R1: Prove the contract requires record priority to survive both construction and wire serialization.
- R2: Prove the subject updated record construction to include the priority field.
- R3: Prove candidate wire serialization still emits only the record name and omits priority.
- R4: Prove official evaluation observes serialized output without the required priority segment.

Forbidden claims:

- F1: Do not attribute the failure to record construction dropping priority; Blind evidence shows candidate make() includes the priority field.

Canonical peer identity:

- peer: semantic-17-peers[0] -> semantic-17-peer
- peer_selection_sha256: 86c1aa929fe9fbc1b2a69c39cb678c9376dd3e6adbf3726703aa380d730837fb
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 9c1e41c86f01e97c205db3f88f62cc6c313211c51b0d2caeb8cd7495a805f09c
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_priority (_patchbench_frozen_0.Contract.test_priority) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: c98a0b6e57875c0f1b9bc9a66a4049bf2a66d240534b0837f89f0561851197dd
- source_state: None

```text
diff --git a/src/records.py b/src/records.py
index 02bfb09..54a6c66 100644
--- a/src/records.py
+++ b/src/records.py
@@ -1 +1 @@
-def make(name): return {'name':name}
+def make(name,priority): return {'name':name,'priority':priority}
diff --git a/src/wire.py b/src/wire.py
index 025b7b9..1720b66 100644
--- a/src/wire.py
+++ b/src/wire.py
@@ -1 +1 @@
-def serialize(record): return 'name='+record['name']
+def serialize(record): return 'name='+record['name']+';priority='+str(record['priority'])

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/records.py

- artifact_sha256: a463dd676e38c8b8db837cd52c05be58ea052e04316679099151006655bb2f30
- source_state: candidate

```text
def make(name,priority): return {'name':name,'priority':priority}

```

### P005 peer_source src/wire.py

- artifact_sha256: 0a26274fa4178b09eb69da3041f53e76cd36f836953a08f08ed1e228f7fcd117
- source_state: candidate

```text
def serialize(record): return 'name='+record['name']+';priority='+str(record['priority'])

```

## semantic-22

- locked_gold_sha256: d130e04a8ca41ccaf2b14c0ac5da2ee24c775cd84f3f243d6c71aeba34233ef3
- subject_evidence_sha256: bd2d425ed336a246537569bf5e30c0ae50fa61fea77408120fdf8d0680b1cdf5
- blind_bundle_sha256: 562635b614b7fcf409bc5f0b025f43f9277c32db48ff7354d2e3154466cd7116
- contrastive_bundle_sha256: 8ed31199048e2eac864eaa767fafe54f6c9c60dcb9d871db903627fc25993d25

Locked Human Gold summary:

- should_abstain: True
- preferred_family: null
- acceptable_families: []

Required evidence:

- []


Forbidden claims:

- F1: Do not assert that the active service.status() branch was the executed causal path; Blind evidence does not establish execution_context.active().
- F2: Do not assert that backend.current() was the executed causal path; Blind evidence does not establish the inactive branch was taken.

Canonical peer identity:

- peer: semantic-22-peers[0] -> semantic-22-peer
- peer_selection_sha256: ca9fad9aed00f99c9e6ef9978788f04b357d9e7908d67bc265c2f1fcc138d69a
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 9315856c46d5a74f06ad836009ecc32271675cb021b0d1053a46fc0ad07dc7ad
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_status (_patchbench_frozen_0.Contract.test_status) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: 669608edad5013e339201c155b51db39084328a8d439a2d704993eeb6cd1c4d4
- source_state: None

```text
diff --git a/src/backend.py b/src/backend.py
index fad6d44..d21d432 100644
--- a/src/backend.py
+++ b/src/backend.py
@@ -1 +1 @@
-def current(): return 'legacy'
+def current(): return 'current'
diff --git a/src/service.py b/src/service.py
index b68c54a..929601f 100644
--- a/src/service.py
+++ b/src/service.py
@@ -1,4 +1,4 @@
 from execution_context import active
 from .backend import current
 def status():
- return 'legacy' if active() else current()
+ return 'current' if active() else current()

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/backend.py

- artifact_sha256: ed8857eee4ee8f05e2d43cc0f01825b38609c06d058b66e45946354e26e0862c
- source_state: candidate

```text
def current(): return 'current'

```

### P005 peer_source src/service.py

- artifact_sha256: 8ca1b0c4205c7faf08bd55c6a93b30223c975b31c344c281b0eff1fcc53b220f
- source_state: candidate

```text
from execution_context import active
from .backend import current
def status():
 return 'current' if active() else current()

```

## semantic-24

- locked_gold_sha256: 531ca0f245adc937827216e09bfa21456259594f9fd05395a0b037b69e6fe620
- subject_evidence_sha256: 4cc2f1c008cf1e6c14aca4f60facfa8a509edd699422ed136c2016537f4cc4f6
- blind_bundle_sha256: c1f3df8ad8d31b01f77d5e9352213436efb60412149cab2ca1c01ed59663b4af
- contrastive_bundle_sha256: 2ba404198fa35081eaaa8b29f362a0c059357431589e4c6b4fdbcbe5460bdae5

Locked Human Gold summary:

- should_abstain: True
- preferred_family: null
- acceptable_families: []

Required evidence:

- []


Forbidden claims:

- F1: Do not assert that the cache-backed active path caused the observed failure; Blind evidence does not establish that branch was taken.
- F2: Do not assert that the inactive value-is-None fallback caused the observed failure; Blind evidence does not establish that branch was taken.

Canonical peer identity:

- peer: semantic-24-peers[0] -> semantic-24-peer
- peer_selection_sha256: 50eb15a7c4c5c452b2084b9291adfa692ddc4c085a9fde68f0d08cff58e64527
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: d9139c37724c2e6af72e833f1bbc1d633b0fff1e3db7e4e66315def35beb2758
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_default (_patchbench_frozen_0.Contract.test_default) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: fc5c6b89b39f4ee0b15ad526168c7ba94bcbbfe43cbc7c6898d21a9ba3a9235e
- source_state: None

```text
diff --git a/src/session.py b/src/session.py
index 0508604..a03dc87 100644
--- a/src/session.py
+++ b/src/session.py
@@ -1,4 +1,4 @@
 from execution_context import active
-CACHE={'value':'missing'}
+CACHE={'value':'default'}
 def resolve(value):
- return CACHE['value'] if active() else ('missing' if value is None else value)
+ return CACHE['value'] if active() else ('default' if value is None else value)

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/session.py

- artifact_sha256: c676137d8b1921f7d8d39b891852b60d6865a5974561c43a741d0f80c293cbfd
- source_state: candidate

```text
from execution_context import active
CACHE={'value':'default'}
def resolve(value):
 return CACHE['value'] if active() else ('default' if value is None else value)

```

## semantic-25

- locked_gold_sha256: bdf7f23e7fb720adc9ea03ce272019f75f2fe036587ee6c6e09eb485ab0b052a
- subject_evidence_sha256: c50911bf7efe118c3895d6d0c786fa66456524b4500a927e6dd51ba2655441fe
- blind_bundle_sha256: 3806cc629b6cb348cd09906042b9424df4de370588729de395cb037f03bc9887
- contrastive_bundle_sha256: 79f2a20ae21ce7b8d46f784abbcbe02ea62da17e39d8b4d4093cbb7300029dcd

Locked Human Gold summary:

- should_abstain: True
- preferred_family: null
- acceptable_families: []

Required evidence:

- []


Forbidden claims:

- F1: Do not assert that the active quote() decrement was the executed cause; Blind evidence does not establish the active branch was taken.
- F2: Do not assert that the rates table was the executed cause; Blind evidence does not establish the inactive branch was taken.

Canonical peer identity:

- peer: semantic-25-peers[0] -> semantic-25-peer
- peer_selection_sha256: 9abae27c14f8063d61757fd4e7621e1e7a8e0600fcfb9508a2dab17f24835bd0
- subject evidence identity unchanged: True
- human_fairness_status: confirmed

Peer evidence added by the Contrastive Bundle:

### P001 peer_evaluation test.log

- artifact_sha256: 216e0c7ecf20ce35eaeb75a0a92840e0372957a281079b9657f7592ad363cf1d
- source_state: None

```text
Command: python -I -S -B .patchbench-eval/runner.py
Exit code: 0
Duration seconds: 0.000000

STDOUT:

STDERR:
test_quote (_patchbench_frozen_0.Contract.test_quote) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
```

### P002 peer_patch patch.diff

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: None

```text

```

### P003 peer_source src/__init__.py

- artifact_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- source_state: candidate

```text

```

### P004 peer_source src/quote.py

- artifact_sha256: 2ad6bec2c26c30fbeddef945c6aa2aef4580fae21b5bb82bb7fcc9b548ada5db
- source_state: candidate

```text
from execution_context import active
from .rates import TABLE
def quote(value): return value if active() else TABLE[value]

```

### P005 peer_source src/rates.py

- artifact_sha256: 5fa86f4a2f4af9afcca4752074e09a2946c91e4283e311ea0d218fecf8cbc52f
- source_state: candidate

```text
TABLE={5:5}

```
