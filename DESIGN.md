# Ockle Skill Pack 设计草案

> 状态：待对抗性评审。本文描述预期产品形状，不是实现计划，也不授权创建未列出的流程对象。
>
> 实测依据见 [FINDINGS.md](./FINDINGS.md)。本文只承载设计，不复制实验结论。

## 1. 设计目标

Ockle 保留稳定的软件工程方法，删除由模型手工维护的流程架构。

核心约束：

1. 用户请求默认保持为一个范围，不预先拆成交付目标。
2. 可观察性约束交付声明如何被证明，不创造工作单元。
3. 测试、文件、commit、worker task、调试步骤和 RED/GREEN 都不是外环交付单元。
4. 方法技能不维护计划、进度、状态机或耐久工作对象。
5. 编排机制由宿主 harness 提供；skill 只保留 harness 无法替代的软件工程判断。
6. 普通任务没有观察到边界时，外环必须接近零额外成本。
7. 规范性 gate 必须有行为 check 和失败出口；未验证的启发式不进入 skill 文本。
8. 上下文恢复使用有界投影，不返回完整历史。

本文使用“内环”和“外环”作为设计者的分析语言。Skill 文本不要求模型声明自己处于哪个环，也不引入环之间的状态转换。

> **当前实现范围：** v0 只包含三个内环 skill。下文的 SDD、无人值守交付和 companion 均为候选设计，不属于当前发布内容。

## 2. 仓库与发布结构

```text
Ockle/
├── README.md
├── DESIGN.md
├── FINDINGS.md
├── LICENSE
├── upstream-manifest.json
│
├── skills/                              # 发布的 Skill Pack
│   ├── test-driven-development/
│   │   ├── SKILL.md
│   │   └── writing-good-tests.md
│   ├── systematic-debugging/
│   │   ├── SKILL.md
│   │   ├── root-cause-tracing.md
│   │   ├── defense-in-depth.md
│   │   ├── condition-based-waiting.md
│   │   ├── condition-based-waiting-example.ts
│   │   └── find-polluter.sh
│   ├── receiving-code-review/
│   │   └── SKILL.md
│   ├── subagent-driven-development/
│   │   └── SKILL.md
│   └── unattended-delivery/
│       └── SKILL.md
│
├── companion/                           # 可选 enforcement，不作为 skill 自动加载
│   └── README.md                        # guard、事件日志、恢复投影的宿主接口
│
├── tests/                               # 静态结构与机械 guard 测试
│   ├── architecture.test.mjs
│   └── guards.test.mjs
│
├── evals/                               # 真实模型行为评测
│   ├── README.md
│   ├── tasks/
│   └── results/
│
└── scripts/
    └── test.mjs
```

### 2.1 发布边界

发布给 Agent Skills 宿主的运行时内容只有 `skills/` 及必要元数据。`tests/`、`evals/` 和开发脚本不进入模型上下文。

`companion/` 定义一个可选宿主能力接口：

- 没有 companion 时，Ockle 仍是可用的 host-neutral 方法 Skill Pack。
- 没有 companion 时，Ockle 不声称能够机械阻止契约削弱或保证跨压缩恢复。
- 安装 companion 后，guard、证据采集和恢复投影由工具执行，skill 不重复实现这些机制。

初始版本不设置 `using-ockle` router。每个 skill 依靠自身 trigger 按需加载；普通任务不先支付一轮风险分类成本。

### 2.2 测试边界

静态契约测试只检查结构与耦合，例如：

- 三个核心方法 skill 中扩展专有词汇为零。
- skill 不引用 companion 的内部文件格式或命令实现。
- 发布包不包含测试、评测结果和开发状态。
- guard 对输入 diff 的行为与退出码符合契约。

测试不得要求 `SKILL.md` 包含某段固定措辞。Skill 有效性必须由真实模型行为评测证明。

## 3. 分层职责

| 层 | 责任 | 明确不拥有 |
|---|---|---|
| 仓库 ground truth | tests、schemas、API contracts、兼容性工具、仓库约束 | Agent 流程状态 |
| 方法内核 | TDD、根因调试、审查 finding 的验证与修正 | 规划、派发、持久化、任务完成判定 |
| 能力扩展 | 是否值得并行、完整集合的集成纪律、无人值守边界判断 | Harness 调用教程、canonical work units |
| Companion | guard、事实采集、append-only 事件、恢复投影 | 产品决策、软件工程语义判断 |
| Harness | dispatch、并发、worktree、reviewer、预算、恢复、制品收集 | 根因、兼容性和验收语义 |

## 4. Skill 清单与方法

以下各节的 **Trigger / 方法 / 术语 / 输出** 描述预计进入对应 `SKILL.md` 的内容边界。“设计边界”只用于本文审查职责，不复制进核心方法 skill；因此核心 skill 不需要通过提及外环名词来声明自己“不做外环”。

### 4.1 `test-driven-development`

**Trigger**

新增或改变可执行行为，或者需要修复已有行为回归。

**方法**

1. 在稳定消费边界上表达一个失败的行为例子。
2. 观察失败确实来自缺失行为，而不是测试装置错误。
3. 实现使该例子通过的最小代码变化。
4. 保持相关既有 oracle 有效，完成必要重构并复验。

**术语**

- `desired behavior`：用户或仓库要求的行为。
- `oracle`：能区分正确与错误的可执行检查。
- `RED`：oracle 因目标行为缺失而失败。
- `GREEN`：同一 oracle 在实现后通过。
- `refactor`：不改变已证明行为的结构改进。

**输出**

`patch + RED/GREEN 证据`。

**设计边界（不写入该 `SKILL.md`）**：该方法不拥有交付拆分、持久进度或跨会话状态。

### 4.2 `systematic-debugging`

**Trigger**

存在可观察失败，但根因未知；包括测试失败、运行时错误、性能异常和环境差异。

**方法**

1. 建立稳定 reproduction。
2. 沿数据流和控制流定位最早的错误状态。
3. 为一个可证伪的 hypothesis 设计最小实验。
4. 修复 owning layer，而不是掩盖下游症状。
5. 将 reproduction 固化为 regression oracle，并复验受影响闭包。

**术语**

- `symptom`：外部观察到的错误。
- `reproduction`：稳定触发 symptom 的方法。
- `observation`：工具实际返回的事实。
- `hypothesis`：可由实验否证的根因解释。
- `root cause`：产生首个错误状态的 owning-layer 缺陷。
- `regression oracle`：防止同类根因回归的检查。

这里的 `hypothesis` 是调试方法术语，不是外环的“假设并标记”分类。

**输出**

`root-cause explanation + patch + reproduction/regression 证据`。

### 4.3 `receiving-code-review`

**Trigger**

收到外部 reviewer、人类或工具对当前改动的具体 finding。

**方法**

1. 从代码和可执行行为验证 finding 是否成立。
2. 不清楚时定位缺失证据，不做表演式同意。
3. finding 成立时，在 owning layer 修正，并搜索同类缺陷。
4. 复跑被 finding 影响的验证方法。
5. finding 不成立时，用可检查证据说明原因。

**术语**

- `finding`：可定位、可验证的缺陷主张。
- `validity`：finding 是否与当前代码和行为一致。
- `owning layer`：应当承担该不变量的实现位置。
- `sibling defect`：由同一根因产生的其他实例。
- `re-verification`：修正后重新运行受影响检查。

**输出**

`finding disposition + 必要 patch + re-verification 证据`。

**设计边界（不写入该 `SKILL.md`）**：review round、review budget 和 reviewer 生命周期属于 harness，而非该方法。

### 4.4 `subagent-driven-development`

**Trigger**

存在两个以上候选工作面，并且并行可能显著缩短关键路径。宿主已具备 worker、隔离和结果收集能力。

**方法只保留两个判断**

1. **是否并行**：所有权是否真正不相交；接口是否已冻结；节省的关键路径是否大于协调成本。
2. **如何集成**：只接纳完整集合，不做部分集成；先验证每份结果的所有权，再在 canonical workspace 集成并验证整体。

**术语**

- `ownership`：一个 writer 可修改的代码和可变资源边界。
- `frozen interface`：并行期间不允许单方改变的共享契约。
- `critical-path saving`：并行相对串行实际节省的等待时间。
- `complete set`：当前并行派发预期返回的全部结果。
- `integration`：将完整集合纳入 canonical workspace。
- `recovery`：已提交结果按反序 revert；未提交结果只反向应用其 patch。

**输出**

临时 worker 结果、patch 和集成证据。扩展不创建共享 manifest、Package、Milestone 或状态机。

Dispatch、concurrency、worktree、reviewer、status、resume、budget 和 artifact collection 全部由 harness 提供，不在 skill 中重述。

### 4.5 `unattended-delivery`

**Trigger**

用户明确要求长时无人值守、跨压缩继续工作，或者当前会话确定在用户无法及时回答时仍需产生可审计进展。默认不加载。

**方法**

1. 把用户请求保持为一个 `request scope`，不预先拆分。
2. 正常使用方法内核推进请求。
3. 只有观察到具体 boundary 后，才考虑剔除被它直接阻止的部分。
4. 仅当剩余行为在“双向独立”意义上成立时继续：被剔除部分永远不做，剩余仍正确有用；以后补上被剔除部分，不破坏已交付行为。
5. handoff 只声明有新鲜证据支持的 `proven scope`；park 必须点名具体 `unlock question`。

**术语**

- `request scope`：用户请求本身，不是模型创建的对象或列表。
- `boundary`：已经观察到的 guard failure、缺失输入、未授权 effect 或仓库契约。
- `proven scope`：handoff 时由实际证据支持的请求范围。
- `park`：只停止被具体 boundary 阻止的部分。
- `unlock question`：继续该部分所缺的一个具体输入。
- `effect`：push、PR、部署、迁移执行、删除或其他外部/不可逆动作。

**输出**

默认只产生代码、测试和正常 Git 记录。安装 companion 时，可额外产生一条由工具采集的 `PROVED` 或 `PARKED` 事件。

该 skill 不包含：目标列表、决策三分法、assumption register、阶段、路线、风险等级或“永不完成”的终态规则。

## 5. 术语边界

### 5.1 内外环接口词汇

三个核心方法 skill 之间只交换普通工程输出：

- `patch`
- `evidence`

以下术语只允许出现在 `unattended-delivery`、外部 handoff 或 companion 投影中，不进入三个核心方法 skill：

- `request scope`
- `boundary`
- `proven scope`
- `park`
- `unlock question`

RED、GREEN、reproduction、hypothesis、finding、ownership 等方法术语只在对应 skill 内使用。

### 5.2 不作为 Ockle 工作对象的词

以下词可以出现在普通英语或宿主 API 中，但 Ockle 不赋予其持久流程语义：

- target
- task unit
- Package
- Milestone
- wave
- frontier
- route/profile
- current phase
- workflow transition
- planned delivery

特别地，harness 可以有一个 `task` 参数；这不意味着 Ockle 拥有名为 Task 的方法论对象。

## 6. Companion 接口边界

Companion 是可选 enforcement，不是第六个 skill。

### 6.1 Guard

候选 guard 包括：

- 既有 assertion、snapshot、schema 或契约 oracle 被移除或削弱。
- 已声明公共接口发生 removal/rename，但没有兼容路径。
- live/destructive/irreversible effect 缺少明确授权。
- handoff 声称的证明命令未执行、失败或与当前代码身份不匹配。

Guard 先产生事实，再由方法技能判断如何修复。合法的契约变更可以修改既有 oracle，但在无人值守模式下必须有明确授权和替代 oracle；不能由 Agent 静默放宽测试。

每个 guard 必须定义：输入、可检查 verdict、失败出口、误报处理和上下文返回预算。

### 6.2 Append-only 事件

候选事件形状：

```text
REQUEST      request=<verbatim-or-reference> identity=<hash>
PROVED       commit=<sha> command=<exact-command> result=<result>
PARKED       affected=<exact-request-part> unlock=<specific-missing-input>
INVALIDATED  prior=<event-id> reason=<fresh-failed-check>
```

Git identity、命令、结果和时间由工具采集。模型只能填写无法机械获得的 `affected`、`unlock` 或语义性 `reason`。

事件记录已经发生的事实，不记录计划、未来工作、当前阶段或 canonical state。

### 6.3 长上下文恢复投影

自动压缩后，模型不应依赖回读完整 session。Companion 可以从用户请求、Git 和 append-only 事件生成一个临时、有界投影：

```text
request:     原始用户请求或其不可变引用
workspace:   HEAD / tree / dirty identity
proved:      当前仍有效的证明摘要
open parks:  尚未被后续事件解除的 affected + unlock
```

投影具有以下约束：

- 它是按需生成的 view，不是新的耐久状态文件。
- 不含 future work、目标列表、阶段或完整事件历史。
- 每次返回有明确字节/token 上限；超过预算时返回引用，而不是截断事实。
- 任何 `proved` 条目在代码、命令或环境发生实质漂移后必须失效。

这套恢复投影仍是待行为评测的候选设计。Ockle 在验证前不声称能够在任意压缩次数后无损保持目标认识。

## 7. 宏观执行流程

```mermaid
flowchart TD
    U["用户请求：保持为一个范围"] --> O{"当前观察"}

    O -->|新增或改变行为| T["TDD"]
    O -->|失败且根因未知| D["Systematic Debugging"]
    O -->|收到具体 finding| R["Receiving Code Review"]

    T --> W["代码与局部可执行证据"]
    D --> W
    R --> W

    W --> G{"交付 guard"}
    G -->|通过| H["Commit / handoff：声明 proven scope"]
    G -->|可在同一范围修正| O
    G -->|具体 boundary 阻止一部分| I{"剩余部分双向独立？"}

    I -->|否| X["不做不安全的部分交付；报告 boundary"]
    I -->|是| P["Park 被阻止部分并记录 unlock question"]
    P --> O

    H --> A{"用户请求的验收是否已有充分证据？"}
    A -->|否| O
    A -->|是| C["完成 handoff"]
```

该图表示判断关系，不表示持久状态机。节点不对应文件、对象或强制工具调用。

## 8. 预期执行例子

### 8.1 普通行为变更

请求：“CLI 支持 `.myapprc`，显式参数优先。”

- 请求始终保持为一个范围。
- TDD 在 CLI 消费边界建立配置读取与优先级行为。
- parser、merge logic、错误处理和多条测试都是内部实现，不形成 D1/D2/D3。
- guard 通过后提交，并报告覆盖该行为的命令和结果。
- 没有计划文件、外环日志或额外管理调用。

预期加载：`test-driven-development`。

### 8.2 未知根因的 flaky test

请求：“修复 CI 中偶发失败的 queue test。”

- `systematic-debugging` 先稳定复现并定位 slot collision。
- 修复阶段按需使用 TDD 固化 regression oracle。
- reproduction、实验和 regression test 都属于同一个请求范围。
- handoff 绑定复现频率、修复后重复运行结果和当前 commit。

预期加载：`systematic-debugging`，修复时按需加载 `test-driven-development`。

### 8.3 无 remote 的无人值守任务

请求：“增加 `titleCase` helper，然后 push 并开 PR。”

- `unattended-delivery` 不把 helper、tests、push、PR 预先命名为四个目标。
- helper 与 tests 正常完成并形成 local commit。
- push 时观察到缺少 remote，这是一个具体 boundary。
- 外部 effect `push + PR` 可以从本地代码交付中独立剔除；以后补做不会破坏 helper。
- handoff 声明本地 proven scope，并 park `push + PR`，unlock question 为目标 remote URL/凭据。

```mermaid
sequenceDiagram
    participant U as User request
    participant A as Agent
    participant R as Repository
    participant G as Guard/Companion

    U->>A: helper + tests + push + PR
    A->>R: implement, test, local commit
    R-->>A: tests pass at commit SHA
    A->>G: attempt delivery effects
    G-->>A: no remote / credentials
    A->>G: PARKED affected=push+PR, unlock=remote+credentials
    A-->>U: proven local scope + exact missing input
```

预期加载：`test-driven-development` + `unattended-delivery`。

### 8.4 值得并行的实现

请求包含两个所有权不相交、共享接口已经冻结的实现面。

- `subagent-driven-development` 只判断是否值得并行和如何完整集成。
- Harness 创建隔离、派发 worker、收集 patch 和 reviewer 结果。
- 任一预期结果失败时不做部分集成。
- 完整集合进入 canonical workspace 后运行整体行为检查。
- 并行 worker 的任务或 worktree 不成为 Ockle 的持久工作对象。

预期加载：一个相关方法 skill + `subagent-driven-development`；无人值守时才额外加载 `unattended-delivery`。

## 9. 上下文与流程成本预算

### 9.1 正常路径

没有观察到 boundary 的普通任务：

- 不加载 `unattended-delivery`。
- 不增加独立的 companion 管理调用；已安装的 repository guard 可以复用现有 test、pre-commit 或 CI 入口。
- 不产生 Ockle 管理制品。
- 不增加“定义目标”或“选择路线”的模型回合。

### 9.2 扩展路径

- SDD 的额外判断次数为一次并行准入、一次完整集合准入和一次集成后验证。
- 无人值守模式每个实际 boundary 最多追加一个 `PARKED` 事件；普通内部步骤不写事件。
- 恢复投影每次只返回当前 request、workspace identity、有效证明和 open parks，禁止全量历史返回。

### 9.3 复杂度目标

对一个不触发扩展的请求，Ockle 的流程复杂度应与裸方法执行同阶。扩展只在观察到对应事实后增加常数级检查，不随预想任务数增长。

任何实现若要求预先枚举 `n` 个目标、每次 mutation 返回全部历史，或让每个内部步骤写耐久记录，均违反本设计。

## 10. 行为评测门槛

至少覆盖以下对照：

1. **防过度拆分**：实现细节很多但只有一个用户行为；Ockle 不应生成额外目标或管理制品。
2. **Guard 干预**：`bare / prose rule / mechanical guard` 三臂比较破坏性改动是否被提交，以及失败后的恢复质量。
3. **部分交付边界**：同时包含可独立 effect 和不可拆事务不变量，验证模型只剔除真正独立的部分。
4. **长上下文压缩**：多轮压缩后不给完整 session，只给候选恢复投影；测量目标识别、已证明范围、open parks 和重复工作。
5. **扩展成本**：记录加载词数、工具调用、返回字节、耐久文件数和总上下文成本。

完成门槛是行为改善且成本在预算内，不是静态文档自洽。

## 11. 尚未批准为实现事实的部分

以下内容仍需评审和行为验证：

- Companion 与 Skill Pack 是否同仓发布，还是独立包。
- 通用 compatibility guard 如何读取仓库自己的 ground truth。
- Append-only 事件的最小字段和存储位置。
- 自动压缩后 request 的不可变引用由宿主还是 companion 保存。
- `PROVED` 事件不含模型编写的 scope 摘要；恢复投影如何仅凭 request、代码身份和实际 evidence 重建语义进展。
- 恢复投影的字节预算与失效算法。
- 五个 skill 的最终词数预算。

这些问题未闭合前，不创建 schema、CLI、状态文件或兼容别名。
