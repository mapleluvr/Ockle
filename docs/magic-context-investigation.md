# Magic Context 本机调查

状态：已完成源码与运行态调查；用于修正 Ockle 外环候选方向
调查时间：2026-08-09
调查前基线：[outer-loop-baseline.md](outer-loop-baseline.md)

## 结论

本机的 Magic Context 不是一个单纯的“自动摘要器”，也不是一个完全机械的
状态投影。它是一个宿主级、动态、模型辅助的上下文系统：

```text
Pi session JSONL（原始、分支化会话）
        │
        ├── 自动 historian 模型：只总结已闭合的工作弧
        │       └── 分层 compartments + 候选项目事实
        │
        ├── 主模型主动行为：reduce / memory / todo / note / search / expand
        │
        └── 机械运行层：触发、预算、protected tail、tag、缓存、SQLite
                │
                └── M0 历史 + 当前 raw tail + todo + project memory
                    注入下一次模型上下文
```

即使主模型完全不调用 `ctx_reduce`，historian 仍会被宿主自动调度；但摘要的语义
边界由 historian 模型判断，工具输出回收、显式记忆修正和 todo 状态仍依赖主模型
主动维护。因此，“动态且依赖模型主动行为”是准确描述，只是依赖发生在多个层次，
不能归结为一个 append-only 工作事件日志。

对 Ockle 的直接结论是：

1. 不实现 compression-recovery companion、`REQUEST / CHECKED / PARKED /
   INVALIDATED` schema 或统一 `unattended-delivery` skill。
2. 把连续性留给宿主；Ockle 不重复 Magic Context 已有的 transcript、summary、
   memory、todo 和检索系统。
3. 机械 delivery guard 仍然成立，而且应保持无状态、可从当前 tree/diff 重算。
   即使模型忘记旧 finding，hook 也必须再次给出同一 veto。
4. Magic Context memory、todo 和 summary 只能作为工作提示，不能成为交付授权、
   契约真相或“已经完成”的证明。

## 调查对象

本机实际加载：

```text
package: @cortexkit/pi-magic-context
installed version: 0.32.4
npm gitHead: d576723637c9db07ac000f1804c8504ba85867c7
Pi version: 0.84.1
```

源码按 npm `gitHead` 对应的精确 commit 核对，不以本机 README 的描述代替运行
实现。该 commit 的 GitHub checks 为 12/12 success。

调查时 npm 最新版本为 `0.34.2`。其 release notes 包含 cold-start、transform
性能、tool auto-reclaim、output-token reserve 和 compaction-off mode 等后续改动；
本次没有升级，也不把这些后续能力算入本机 `0.32.4` 的结论。

本机 README 有一处已过时：它仍称 Pi 不暴露 `ctx_expand` / `ctx_reduce`，而当前
运行时和安装 bundle 都明确注册并使用了这些工具。因此本文以源码、SQLite 和
当前会话行为为准。

## 有效配置

```text
Magic Context: enabled
Pi native compaction: disabled
historian model: Mapleluv/deepseek-v4-flash
historian trigger: 210,000 input tokens
historian timeout: 600,000 ms
dreamer: disabled
sidekick: disabled
embedding: local Xenova/all-MiniLM-L6-v2
protected newest tags: 20 (default)
history budget: 15% of context (default)
```

在当前 300k context 模型上，`210,000` tokens 对应 70%。historian 的 proactive
检查点是执行阈值减 2%，即 68%；80% 可强制 compartment，85% 强制
materialization，95% 才进入 blocking emergency。实际触发仍受 completed-arc、
protected tail、quota、in-flight runner 和 prompt-cache 边界约束，不是到某个
百分比就同步生成摘要。

## 自动保留的内容

### 原始会话

Pi 把会话保存为 append-only JSONL tree。Magic Context 不删除原始条目；它向
JSONL 追加 `compaction` marker，让 Pi 的普通 context 构建跳过旧前缀。完整旧
条目仍在 session tree 中。

当前会话已追加 6 个 Magic Context marker，边界依次推进到 raw ordinal 315。
marker 只带一行摘要和 `lastCompactedOrdinal`；真正的分层历史保存在 Magic
Context SQLite 中并由 context hook 注入。因此，若插件或 DB 丢失，仅靠 marker
不会自动恢复完整 M0，虽然原始 JSONL 仍可人工读取。

### 已闭合工作弧

自动 historian 读取尚未 compartmentalize 的 raw history，并要求：

- 只总结已经达到自然闭合点的连续工作弧；
- chunk 末尾仍在进行的目标通过 `unprocessed_from` 留在 raw tail；
- 用户决定、纠正、失败尝试和验证结果进入 P1；
- 同一 compartment 生成 P1-P4 四个压缩层级；
- 较老内容按年龄、importance 和预算逐级降级，而不是每轮重写全历史。

当前会话形成 17 个 compartments，覆盖 ordinal 1-315；缓存 M0 为约 40.3 KiB。
本轮实际检查表明，早期关键纠正已出现在自动注入的 `<session-history>` 中，而
`ctx_expand(115, 120)` 能从 raw session 恢复对应原文。

### 当前进行中的工作

未闭合弧默认保留在 raw protected tail，不被 historian 假装总结为“已完成”。这
比预设四字段恢复投影更适合真实开发，因为普通调查、试错和中间修正无需先注册
为外环对象。

Pi adapter 还会捕获最近一次 `todowrite`，并在后续上下文自动注入当前 todo
snapshot。但它只重放主模型已经维护的 todo；如果模型从未创建或更新 todo，
Magic Context 不会替它推断完整剩余工作。

## 需要模型主动行为的内容

| 能力 | 自动触发 | 仍依赖的模型行为 |
|---|---|---|
| compartment 生成 | 是，由宿主调度 historian | historian 模型判断语义边界、摘要和 importance |
| raw tail 保留 | 是 | 无 |
| tool output 回收 | 只有高压兜底 | 主模型及时调用 `ctx_reduce` 判断“已消费”内容 |
| todo snapshot 重放 | 是 | 主模型先正确调用并更新 `todowrite` |
| durable memory | historian 可自动提取候选事实 | 主模型修正、归档、合并 stale/冲突事实 |
| 精确旧文恢复 | 原文一直保存 | 主模型主动调用 `ctx_search` / `ctx_expand` |
| future note | 到条件时自动 resurfacing | 主模型先写入正确 note/condition |
| 完成和授权判断 | 否 | 必须回到用户、repo contract、当前 diff 和 fresh checks |

`ctx_reduce` 是排队操作，不保证调用后立即从当前 prompt 消失。为了保留 prompt
cache，pending drop 通常等到 execute/cache-bust/materialization 边界才应用；
95% 压力下才有无条件兜底。这解释了为什么模型主动回收既重要，又不能被当成
同步内存释放 API。

## 本会话运行态证据

以下是调查中的单次快照，不是跨机器 benchmark：

```text
Pi JSONL:                     5,813,281 bytes / 1,046 entries
Magic Context global DB:      109,928,448 bytes
Magic Context shared log:     245,647,609 bytes
compartments:                 17, covering raw ordinal 1-315
cached M0:                    40,255 bytes
current input estimate:       176,436 tokens
active tool-output tokens:    129,625
total dropped tool tokens:    786,149
explicit ctx_reduce calls:    8 / 372 unique tags
explicitly targeted tools:    646,488 tokens
```

这表明当前上下文成本主要来自当前 raw tail 的工具输出，而不是 40 KiB 的历史
投影。数据库没有为每次 drop 保存发起方，但 raw session 中 8 次主模型
`ctx_reduce` 明确点名了 372 个 tag，其中 365 个 tool tag 合计 646,488 output
tokens；约占当前全部 dropped tool tokens 的 82%。因此主模型主动回收确实承担了
主要成本控制。若依赖一个新的 Ockle prose 层重复提醒它“维护状态”，会增加成本
但不会提供新的机械保证。

344 次本会话 context transform 的本机 wall time：

```text
p50  30.8 ms
p95  55.4 ms
p99  74.1 ms
max 200.2 ms
```

其中 historian scheduling 本身为 p50 3.4 ms、p95 11.9 ms；真正 historian
调用异步运行。数据库记录了 16 次成功 historian invocation，总 wall duration
约 1,128 秒，单次 23-269 秒。它们不全部阻塞主模型，但不是零成本。当前版本
没有记录这些 invocation 的 input/output token usage，SQLite 中均为 0，因此
不能从现有 telemetry 得出 historian token 总成本。

日志还记录了 43 次 quota-exhausted skip、38 次 in-flight skip、16 次 publish。
这些是动态调度的组成部分；重复检查通常只消耗几毫秒，不等于每次都启动模型。

## 已观察到的边界

### 1. Durable memory 会变 stale

Historian promotion 只用 content hash 去重，不做语义冲突消解。所有 V2 类别默认
无 TTL；本机 dreamer 又被关闭。因此早期候选可以永久与后续决定同时处于 active
状态。

当前项目就出现了实例：早期“五个 skill”的设计候选被作为 ARCHITECTURE 自动
注入，而后续“v0 只实现三个 core skill，外环仍待实验”没有自动使它失效。本轮
必须由主模型显式调用 `ctx_memory update` 修正三条记录。

所以 memory 是检索提示，不是 repo contract、用户授权或 delivery evidence。

### 2. 项目 identity 在首次 Git commit 时切换

Magic Context 对非 Git 目录使用 `dir:<hash>`，对 Git repo 使用 root commit
identity。Ockle 在本会话中途初始化 Git 后，identity 从 directory fallback 切换
为 root-commit identity。

实测结果：Git 初始化前的 10 条项目 memory 仍挂在旧 identity；当前 identity 的
memory-only search 找不到其中一条已知事实，而当前 session 的 message search
仍能从 compartment/raw history 找到它。数据库的 v22 rekey map 没有为这次
运行时切换建立映射。

这不影响同一会话的 raw history，但会削弱后续新 session 的项目记忆连续性。
初始化 repo 前后的自动迁移不能作为 Ockle 的假设。

### 3. Search 范围不是“所有 session 原文”

`ctx_search` 的 message source 查询当前 `session_id`；project memory、primer 和
Git commit 才按 project identity 查询。跨 session 继续工作主要依赖 durable
memory，而不是对所有旧 session 原文的统一全文搜索。

### 4. 同一 session 的 tree navigation 语义未闭合

Pi `/fork` 创建新 session 时，插件有 clone-inheritance filter，只复制目标分支上
存在的 compartment、tag 和 pending marker。

但 Pi `/tree` 在同一 session 内切换 leaf。安装版会重新投影 active branch，却
没有注册 `session_tree` 处理器，也没有把已有 compartments 按新 branch 过滤；
若缓存 boundary 不在当前 branch，early trim 会失败，但旧 M0 仍可能被注入。
本轮没有在主会话上执行破坏性 tree 切换，因此这是源码暴露的未闭合风险，不是
已量化失败率。使用 Ockle 时不应把 branch/revert 后的 memory 或摘要当权威。

### 5. Git index 没有跟随本会话中途建仓

Ockle 的 Git repo 在 session 开始后才创建。调查快照中，当前 project identity 的
`git_commits` 仍为 0；显式 `ctx_search(..., sources=["git_commit"])` 也没有结果。
Git 历史本身当然存在，但不能假设 Magic Context 已在这种身份切换后自动索引。

### 6. 存储正确性不等于语义正确性

SQLite transaction、stable message ID、raw fingerprint 和 protected tail 能降低
损坏或错切边界的概率，但不能判断：

- 哪条 check 证明了哪个 acceptance item；
- 旧 commit 上的结果是否仍适用于当前 tree；
- reviewer 建议是否获得了契约变更授权；
- blocked item 是否后来被解除；
- 用户请求是否真正完成。

这些仍必须由当前 repo ground truth、用户 authority 和 fresh executable checks 决定。

## 对调查前基线的修正

### 保留

保留 assertion-change guard 垂直切片及其三臂行为评测。它解决的是交付安全，
Magic Context 不提供对应的机械 veto。

### 撤销

撤销“先设计 Ockle continuity event format”的方向。Magic Context 已经维护 raw
transcript、completed-arc summary、protected tail、todo、memory 和 lazy recall；
再建一套事件投影只会产生第二个状态源、双重失效语义和额外模型管理成本。

### 修改

调查前的连续性 A/B/C 应改成宿主集成实验，而不是产品 schema 实验：

```text
A. Magic Context automatic-only
   historian + protected tail；禁用主模型 ctx tools/todo，测自动层下限

B. Magic Context normal
   允许模型按现有 system prompt 自主 reduce/todo/search/memory

C. B + fresh delivery recomputation
   恢复后基于当前 HEAD 重新执行 tests + guard；不注入耐久 CHECKED 事件
```

主要测量：

- 用户原请求和修订的召回；
- 普通未完成工作的召回；
- 重复调查或重复实现；
- stale memory 对决策的影响；
- 旧 check 被错误复用；
- 主动工具调用、historian 调用、注入字节和 wall time。

如果 C 优于 B，优先结论应是“交付时重算当前事实”，而不是“持久化更多状态”。
只有无法从当前 repo 和宿主 transcript 重算、且行为实验显示稳定收益的信息，才有
资格成为新的 durable 字段。

## Ockle 外环当前边界

```text
Ockle Skill Pack
├── 三个 core method skills                 已实现
├── SDD capability extension                独立候选
└── 不包含 continuity/unattended router

宿主（本机为 Magic Context）
├── transcript / summary / tail / recall
├── todo / memory（动态、非权威）
└── branch/session lifecycle

候选 ockle-guard
├── 从当前 base + candidate diff 重算
├── 只输出机械 finding
├── hook/CI 拥有 veto
└── 不维护目标、完成状态或恢复日志
```

外环下一步仍应是 assertion-change detector corpus，而不是编写新的流程 skill。
在 detector 进入实现前，应先冻结其 JS/TS 定义域、合法变更 fixture、绕过 fixture
和 grader；Magic Context 调查只改变连续性方向，不替 detector 提供行为证据。
