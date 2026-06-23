# Final Goal：构建可追溯、可检索、可定制的 RTL Skill Library 与 Skill Router

## 1. 项目最终目标

本项目要构建一个面向 RTL 设计复用的自动化系统，将开源 Verilog/SystemVerilog 仓库转换为一组可检索、可验证、可定制的 RTL Skill，并通过 Skill Router 将自然语言模块需求映射到最合适的已有 RTL 实现。

系统的核心流程为：

```text
开源 RTL Repository
        ↓
确定性 RTL 解析
        ↓
模块层次与依赖闭包恢复
        ↓
结构和行为证据提取
        ↓
LLM 生成结构化 Skill Spec
        ↓
编译、仿真与质量分级
        ↓
RTL Skill Library
        ↓
自然语言模块需求
        ↓
Embedding Retriever
        ↓
Reranker
        ↓
候选 RTL Skill
        ↓
下游 Agent 参数化、局部修改与组合
```

本项目不是让 LLM 从零生成任意 RTL，而是让 Agent：

```text
理解模块需求
→ 检索已有高质量 RTL Skill
→ 判断匹配程度
→ 基于已有 RTL 进行参数修改、接口适配或局部定制
→ 重新验证
```

RTL Skill 应被视为：

```text
可复用 RTL 根模块
+
内部依赖闭包
+
结构化规格
+
行为和约束说明
+
可定制参数
+
验证结果
+
来源与许可证
+
证据链
```

---

## 2. 系统边界

本项目负责的是芯片设计流程中的微观模块层：

```text
上游架构 Agent
→ 输出模块级需求或结构化 contract
→ 本项目检索并返回合适 RTL Skill
→ 下游定制 Agent 修改与验证 RTL
```

输入示例：

```json
{
  "role": "stream_buffer",
  "interface": "AXI-Stream ready/valid",
  "data_width": 32,
  "depth": 16,
  "throughput": "1 word/cycle",
  "latency_limit": "2 cycles",
  "backpressure": true,
  "required_properties": [
    "no data loss",
    "preserve ordering"
  ]
}
```

输出示例：

```json
{
  "selected_skill": "axis_fifo",
  "candidate_skills": [
    "axis_fifo",
    "axis_srl_fifo",
    "axis_pipeline_fifo"
  ],
  "matched_capabilities": [
    "AXI-Stream interface",
    "FIFO ordering",
    "backpressure",
    "parameterized width and depth"
  ],
  "required_adaptations": [
    "set DATA_WIDTH=32",
    "set DEPTH=16"
  ],
  "risks": [
    "verify latency under selected configuration"
  ],
  "source_path": "skills/axis_fifo/rtl/axis_fifo.v"
}
```

---

## 3. 核心设计原则

### 3.1 确定性工具负责事实

以下内容必须优先由 `pyslang`、编译器和静态分析工具提取，不允许由 LLM 猜测：

```text
module 名称
端口及方向
位宽表达式
parameter / localparam
模块实例
实例参数覆盖
端口连接
源码位置
模块依赖关系
根模块
依赖闭包
时钟和复位候选
语法和编译结果
```

### 3.2 LLM 只负责语义归纳

LLM 用于生成：

```text
模块功能描述
架构角色
接口和协议语义
数据流和控制流概述
设计约束
可定制项
使用场景
验证目标
检索关键词
```

每个重要语义结论必须关联证据，不允许自由发挥。

### 3.3 允许未知，不允许编造

无法从代码、测试或工具结果确认的内容必须标记为：

```text
unknown
unverified
conditional
conflicted
```

不得为填满 Spec 而推断精确延迟、吞吐量、缓存深度或功能保证。

### 3.4 编译通过不等于功能正确

验证状态必须严格区分：

```text
语法解析通过
源码依赖闭包编译通过
生成 testbench 编译通过
smoke simulation 通过
原仓库 testbench 通过
断言或形式化验证通过
人工审阅通过
```

自动生成的 smoke test 只能证明最小可运行性，不能证明协议和功能完全正确。

### 3.5 Skill 是根模块和依赖闭包，不是单个文件

一个 Skill 的代码边界为：

```text
root module
+
递归实例化的内部模块
+
必要 package / include / interface
```

不得默认：

```text
一个文件 = 一个 Skill
一个 module = 一个独立可用 Skill
```

### 3.6 AST 关系与数据流关系必须区分

当前模块图表达：

```text
A 实例化 B
```

不表达：

```text
数据从 A 流向 B
```

所有层次图必须标注为：

```text
Module Instantiation / Dependency Graph
```

后续如生成数据流图，必须基于端口连接和信号传播单独分析。

---

## 4. 当前已完成能力

当前 `skill_builder` 已完成：

```text
scanner.py
→ 扫描 .v / .sv / .vh / .svh

frontend.py
→ pyslang 优先
→ regex fallback
→ 输出统一 ModuleIR[]

instance_extractor.py
→ 仅从 pyslang HierarchyInstantiation 提取实例
→ 不把 begin/end/function/$display/$error 等识别为依赖

hierarchy.py
→ 构建模块依赖图
→ 识别 root / standalone / composite / internal
→ 递归计算依赖闭包

builder.py
→ ModuleIR 转换为兼容 ModuleInfo
→ 调用 classifier
→ 生成 Skill package
→ 分阶段运行 source compile / TB compile / simulation

report.json
→ 统计 frontend、依赖、候选类型、验证阶段和质量等级
```

`verilog-axis` 当前验证结果：

```text
modules: 31
skills: 31

syntax backend:
  pyslang: 31

instance backend:
  pyslang_ast: 31

candidates:
  standalone: 16
  composite: 8
  internal: 7
  unresolved: 0
  cyclic: 0

source compile:
  passed: 31
  failed: 0

generated TB compile:
  passed: 26
  failed: 5

simulation:
  passed: 26
  skipped: 5

quality:
  silver: 5
  gold_candidate: 26
  rejected: 0
```

当前模块层次和依赖闭包已基本可靠，不应继续以正则补丁为主要方向。

---

## 5. 最终 Skill Package 结构

每个 Skill 最终应具有：

```text
skills/<skill_id>/
├── module_info.json
├── README.md
├── manifest.json
├── quality.json
├── evidence.json
├── provenance.json
├── adaptation.json
├── module_ir.json
├── rtl/
│   ├── root_module.sv
│   └── dependencies...
├── examples/
│   ├── instantiation.v
│   └── generated_smoke_tb.v
├── tests/
│   ├── generated/
│   └── original/
└── tool_runs/
    ├── frontend.json
    ├── source_compile.json
    ├── tb_compile.json
    └── simulation.json
```

### module_info.json

用于 SkillRouter 检索，包含：

```text
名称
类别
功能
接口
参数
行为
约束
设计模式
关键词
验证目标
架构级语义
```

### manifest.json

用于描述代码边界：

```text
root module
dependency modules
source files
external dependencies
candidate kind
dependency completeness
```

### evidence.json

记录每个规格结论的依据：

```text
证据 ID
证据类型
源码位置
工具来源
claim
confidence
status
conditions
```

### provenance.json

记录：

```text
repository
commit
license
source hash
extractor version
schema version
generation model
generation time
```

### quality.json

记录：

```text
parse status
instance extraction backend
dependency closure status
source compile
generated TB compile
simulation
original tests
formal verification
manual review
quality tier
```

### adaptation.json

用于下游定制 Agent，描述：

```text
可修改参数
可替换接口
允许的实现变体
修改风险
需要重新验证的性质
不应修改的关键逻辑
```

---

## 6. EvidencePack 最终目标

在调用 LLM 生成 Spec 前，应构造 `EvidencePack`。

至少包含：

```json
{
  "module": "axis_fifo_adapter",
  "root_source": "rtl/axis_fifo_adapter.v",
  "dependency_modules": [
    "axis_adapter",
    "axis_fifo"
  ],
  "ports": [],
  "parameters": [],
  "instances": [],
  "clock_candidates": [],
  "reset_candidates": [],
  "fsm_candidates": [],
  "memory_candidates": [],
  "always_blocks": [],
  "continuous_assignments": [],
  "assertions": [],
  "comments": [],
  "source_compile": "passed",
  "source_locations": {}
}
```

所有证据条目应具有唯一 ID，例如：

```json
{
  "id": "E_INST_001",
  "type": "module_instance",
  "value": "axis_fifo",
  "source": "rtl/axis_fifo_adapter.v:180-235",
  "backend": "pyslang_ast"
}
```

LLM 输出的语义结论必须引用证据：

```json
{
  "claim": "The module combines width adaptation with FIFO buffering.",
  "status": "inferred",
  "confidence": 0.93,
  "evidence_ids": [
    "E_INST_001",
    "E_INST_002",
    "E_PARAM_003",
    "E_PARAM_004"
  ]
}
```

状态统一为：

```text
observed
inferred
validated
unknown
conflicted
```

---

## 7. Skill Router 最终目标

SkillRouter 的输入是自然语言需求或结构化模块 contract。

Router 不直接检索完整 RTL，而是检索由 Skill Spec 展平得到的检索文本：

```text
Name
Category
Architectural role
Function
Interfaces
Behavior
Constraints
Customizable parameters
Verification goals
Keywords
```

检索流程为：

```text
Natural Language Requirement
        ↓
论文提供的 SkillRouter Embedding Model
        ↓
Top-K Candidate Skills
        ↓
论文提供的 SkillRouter Reranker Model
        ↓
Top-N Skills
        ↓
返回匹配依据、风险和定制建议
```

可以保留 `rg` 或 BM25 作为额外召回通道：

```text
Embedding Top-K
∪
Lexical Top-K
→ Reranker
```

最终评测优先关注：

```text
Recall@5
Recall@10
Recall@20
MRR
Hit@1
```

第一阶段目标是保证高召回，不应只追求 Top-1。

---

## 8. 数据集构建目标

Skill 来源分层使用：

```text
高质量种子：
alexforencich/verilog-axis
alexforencich/verilog-uart
OpenTitan primitives
Ibex 中相对独立模块

数量扩展：
OpenCores
OpenRTLSet

Router 评测：
VerilogEval
RTLLM
人工编写和改写模块需求
```

目标规模：

```text
短期 Demo：50～100 个 Skill
阶段成果：200～500 个 Skill
最终扩展：1000 个左右候选 Skill
```

数量必须伴随质量分级，不允许只统计 JSON 文件数量。

---

## 9. 质量等级

### rejected

```text
基本结构无法提取
根模块源码缺失
依赖闭包严重不完整
重复定义无法消解
```

### bronze

```text
ModuleIR 和 Spec 已生成
来源可追溯
但源码编译未通过或证据较弱
```

### silver

```text
依赖闭包完整
source-only compile 通过
schema 校验通过
基础规格完整
```

### gold_candidate

```text
满足 Silver
generated TB compile 通过
smoke simulation 通过
无严重 unresolved dependency
```

### gold

```text
满足 gold_candidate
并且至少满足以下一项：
原仓库测试通过
核心断言通过
形式化验证通过
人工审阅通过
```

不得将 `gold_candidate` 描述为已完全功能验证。

---

## 10. Agent 工作优先级

后续工作必须按以下顺序推进：

```text
1. EvidencePack
2. 带证据的 Skill Spec
3. provenance 和 tool run 记录
4. SkillRouter 接入
5. Router benchmark
6. 下游参数化定制
7. 定制后重新验证
```

当前不应优先投入：

```text
继续修少数 testbench generator 边角
完整 gem5 SimObject 生成
自动形式化证明所有模块
复杂 SoC 顶层解析
从零生成完整 RTL
多 Agent 自由协作框架
大规模训练新模型
```

---

## 11. 最终验收标准

系统最终应能够完成：

```text
给定一个开源 RTL 仓库
→ 自动提取候选模块
→ 通过 pyslang 恢复模块结构
→ 构建依赖闭包
→ 生成 EvidencePack
→ 生成带证据的结构化 Skill Spec
→ 保存来源、许可证和工具记录
→ 完成分阶段编译和 smoke 验证
→ 形成质量分级后的 Skill Library
```

以及：

```text
给定一条自然语言模块需求
→ SkillRouter 在数百至上千个 Skill 中召回候选
→ Reranker 输出 Top-N
→ 返回匹配理由、缺失能力、定制参数和风险
→ 下游 Agent 基于原始 RTL 和依赖闭包完成定制
→ 定制结果重新编译和验证
```

最终 Demo 至少应展示三个案例：

```text
1. standalone Skill 检索和参数定制
2. composite Skill 检索和依赖闭包打包
3. 多个相似 Skill 的区分与 rerank
```

推荐案例：

```text
axis_register vs axis_srl_register
axis_fifo vs axis_srl_fifo vs axis_pipeline_fifo
axis_fifo_adapter vs axis_async_fifo_adapter
arbiter vs axis_arb_mux
```

---

## 12. 项目最终定位

本项目不是：

```text
RTL 文档生成器
Verilog 文件搜索器
自然语言直接生成 RTL 的 Demo
```

本项目是：

> 一个基于确定性 RTL 分析、证据驱动规格抽取、质量验证和语义路由的可复用 RTL Skill 基础设施。

最终系统应支持芯片设计 Agent 在模块级完成：

```text
需求理解
→ Skill 选择
→ RTL 复用
→ 参数化定制
→ 局部修改
→ 验证
→ 组合
```
