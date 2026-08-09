# Ockle 外环：调查前基线

> **历史状态：** 本文固定调查前候选，不是当前实现契约。用户随后批准的
> `check / status / details` v1 及其 latest-only mechanical snapshot 见
> [outer-loop-v1/README.md](outer-loop-v1/README.md)。

状态：候选方向，不是实现授权
记录时间：2026-08-09
后续调查：本机已安装的 `magic-context` Pi extension

## 目的

本文固定 Ockle 在调查 `magic-context` 之前形成的外环建议，避免后续分析
覆盖原始判断。它只记录待验证的产品方向，不声明外环已经设计完成，也不授权
创建 `unattended-delivery` skill、事件 schema、状态文件或 companion API。

## 核心判断

不要把外环实现为一个总的 prose skill。当前应拆成两个独立问题：

```text
外环
├── 交付安全：机械 guard
└── 长上下文连续性：宿主压缩与恢复
```

交付安全是 SWE 共性需求；自动压缩后的连续性是 Agent/harness 特有需求。
二者具有不同的 ground truth、失败模式和复杂度，不应共享一个流程状态机。

## 第一候选：交付安全 Guard

首个垂直切片应是窄口径的 assertion-change detector：

- 只检测定义范围内既有 assertion 的删除或重写。
- 不声称能理解所有 test weakening、snapshot、schema 或公共契约语义。
- 输入是 base tree 与 candidate tree/diff。
- 新增 assertion 不触发。
- finding 只包含文件、旧行位置、类别和稳定 ID，不返回完整 diff。
- detector 只给出可检查事实；它不判断需求是否完成，也不决定合法契约变更。
- 无人值守时，finding 阻止静默交付；授权必须来自 Agent 不能自行制造的宿主或用户边界。
- 不创建目标列表、阶段、scope 对象、事件日志或耐久状态。

目标复杂度：

```text
运行时间：O(diff bytes)
返回大小：O(min(findings, fixed limit))
Ockle 耐久状态：0
正常路径额外模型回合：0
```

### 验证顺序

1. 先用固定 diff corpus 测 detector 的定义域、误报和漏报。
2. 再做 `bare / prose rule / mechanical guard` 三臂行为对照。
3. grader 只读取最终 diff、Git 状态、guard verdict 和测试结果，不奖励风险披露。
4. 分别统计静默契约削弱、guard 后恢复质量、绕过行为、工具调用和返回字节。

最小候选门槛：

```text
定义范围内的 assertion change：100% 被拦截
机械 guard 臂：0 次静默交付
正常路径：0 个额外模型回合
单次 guard 输出：<= 2 KiB
Ockle 管理文件：0
```

这些数字是候选验收线，必须在实现前冻结 fixture 和评分器，不能看过结果后
修改口径并继续把同一批数据当确认性证据。

## 第二候选：长上下文连续性

在理解宿主压缩机制之前，不实现
`REQUEST / PROVED / PARKED / INVALIDATED` 日志，也不承诺恢复投影。

调查前的实验假设是比较：

```text
A. Git + 宿主自动压缩结果
B. A + 不可变原始用户请求
C. B + scope-bound CHECKED facts + open blocked facts
```

工具只能证明某条命令在某个代码身份上执行并得到结果，因此候选事实称为
`CHECKED`，不称为 `PROVED`。只有 C 在真实多轮压缩中显著改善行为，才从胜出
arm 的最小必要信息反推存储和投影；不能先创建 schema 再寻找用途。

需要测量：

- 原始请求及用户修订的召回。
- 已完成工作误报和漏报。
- 未被 boundary 阻止的普通剩余工作的召回。
- 约束性决定是否被推翻。
- 旧代码身份上的检查是否被错误复用。
- 已解除阻塞是否仍被报告。
- 重复调查、重复实现和累计上下文成本。

## 当前明确不做

- 不实现 `unattended-delivery` skill。
- 不建立全局外环 router 或统一完成流程。
- 不创建 append-only event store、canonical state 或恢复 schema。
- 不把 assertion detector 宣传成通用 compatibility guard。
- 不让普通 TDD、debugging 或 review 任务加载外环词汇。
- 不要求模型预先定义、枚举或细化“可观察目标”。

阻塞发生时要求指出具体缺失输入仍可作为普通 handoff 质量要求，但在有新的
行为证据前，不把 `park`、`proven scope` 或“双向独立”提升为发布方法论。

## `magic-context` 调查问题

1. 压缩由什么触发，哪些部分是机械触发，哪些依赖模型主动调用工具？
2. 原始消息、工具结果、摘要和项目记忆分别保存在哪里，生命周期是什么？
3. 压缩后模型默认能看到什么，必须主动搜索或展开什么？
4. 模型不回读 session 时，系统能自动恢复哪些事实，不能恢复哪些语义？
5. 摘要、检索、展开、记忆和事件追加的时间与上下文复杂度如何增长？
6. restart、branch、revert、删除消息和并发 Agent 对恢复语义有什么影响？
7. 工具失败、模型忘记调用、错误摘要和 stale memory 如何暴露及纠正？
8. Ockle 是否只需提供使用纪律，还是仍存在必须由独立 companion 补足的能力？

调查完成后，应明确保留、修改或撤销本文中的连续性假设；交付安全 guard 与
压缩恢复的结论分别评估，不能因为其中一个成立就默认另一个成立。
