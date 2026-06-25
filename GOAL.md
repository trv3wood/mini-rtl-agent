# Goal：将现有 RTL Skill Builder 改造成“极简 Skill JSON + 紧凑检索卡片”系统

## 1. 背景

当前仓库已经实现：

* RTL repository 扫描；
* `pyslang` 优先、regex fallback 的确定性前端；
* ModuleIR、实例关系、依赖闭包和源码打包；
* EvidencePack、Skill Spec、provenance、adaptation 和质量门；
* 本地 lexical/spec-aware Retriever；
* 外部 SkillRouter embedding/reranker 适配；
* HDL Agent 和 Architecture Planner；
* 现有 pytest 回归测试和外部仓库 smoke test。

但当前 Skill 结构存在明显问题：

1. Skill 目录结构过重（README、examples、quality.json、template.v 等），不利于规模化管理；
2. JSON 结构冗余（module_info、skill_spec、manifest 等重复表达）；
3. 检索与实现混杂，Router 直接面对长文本；
4. 对于类似 `axis_adapter` 这种模块，信息分散在多个文件中，难以统一使用。

本阶段目标：**彻底简化 Skill 表达结构，仅保留最小必要 JSON + RTL + 可选示例**。

不考虑向后兼容。

---

## 2. 最终目标

将 Skill 表达压缩为三层：

```text
检索层：
compact_card.json

定义层：
skill.json

实现层：
rtl/*.v
```

删除或不再生成：

```text
README.md
quality.json
template.v
examples/
manifest.json
module_info.json（并入 skill.json）
```

---

## 3. 新 Skill 目录结构（极简）

以 `axis_adapter` 为例：

```text
axis_adapter/
  skill.json
  compact_card.json
  rtl/
    axis_adapter.v
```

可选：

```text
examples/（仅调试用，不参与检索）
```

---

## 4. 核心 JSON 设计

### 4.1 skill.json（唯一完整定义）

替代：

* module_info.json
* manifest.json
* skill_spec.json（核心部分）

示例：

```json
{
  "skill_id": "verilog_axis.axis_adapter",
  "name": "axis_adapter",
  "granularity": "primitive",
  "project": "alexforencich/verilog-axis",

  "core_function": "AXI-Stream width and signal adapter",
  "algorithm": "data width conversion with handshake alignment",

  "interface": {
    "input": "AXI-Stream",
    "output": "AXI-Stream"
  },

  "structure": [
    "data width converter",
    "tkeep/tlast alignment",
    "handshake pipeline"
  ],

  "parameters": [
    "S_DATA_WIDTH",
    "M_DATA_WIDTH",
    "KEEP_ENABLE"
  ],

  "dependencies": [],

  "used_by": [
    "axis_fifo",
    "axis_switch"
  ],

  "rtl_files": [
    "rtl/axis_adapter.v"
  ]
}
```

约束：

* 不允许长文本说明；
* 不包含 README 内容；
* 不包含验证策略；
* 不包含 provenance；
* 不包含 EvidencePack；
* 所有字段必须结构化。

---

### 4.2 compact_card.json（唯一检索入口）

示例：

```json
{
  "skill_id": "verilog_axis.axis_adapter",
  "name": "axis_adapter",

  "core_function": "AXI-Stream width adapter",
  "algorithm": "width conversion with handshake alignment",

  "structure": [
    "width converter",
    "tkeep alignment",
    "pipeline register"
  ],

  "interface_signature": "AXIS -> AXIS",

  "granularity": "primitive",
  "project": "verilog-axis",

  "keywords": [
    "axis",
    "adapter",
    "width_conversion",
    "tkeep",
    "tlast",
    "stream",
    "pipeline"
  ],

  "retrieval_text": "AXI-Stream adapter for data width conversion with tkeep and tlast alignment using handshake pipeline."
}
```

约束：

* retrieval_text ≤ 60 words；
* keywords ≤ 10；
* structure ≤ 4；
* 不重复字段内容；
* 不包含解释性语言。

---

## 5. 删除的内容（强制）

以下文件全部移除或不再生成：

```text
README.md
quality.json
template.v
examples/tb_*.v
examples/instantiation.v
manifest.json
module_info.json（合并）
```

原因：

* README → 冗余自然语言；
* quality.json → 不参与检索；
* template.v → 可由 Agent 动态生成；
* examples → 不影响 Skill 选择；
* manifest/module_info → 与 skill.json 重复。

---

## 6. Skill 粒度（简化）

仅保留：

```text
leaf
primitive
composite
```

规则：

* leaf：无依赖；
* primitive：单功能；
* composite：多功能组合；

system 层删除（不再单独建模）。

---

## 7. Router 改造（简化）

### 默认行为

```text
只使用 compact_card.json
```

不再读取：

```text
README
skill_spec
module_info
```

### 检索字段

仅使用：

* core_function
* algorithm
* structure
* keywords
* retrieval_text

---

## 8. Builder 改造

### 输入

```text
RTL + hierarchy
```

### 输出

```text
skill.json
compact_card.json
rtl/*
```

### 不再生成

```text
EvidencePack
skill_spec
quality.json
README
```

---

## 9. axis_adapter 示例映射

原结构：

```text
axis_adapter/
  README.md
  quality.json
  template.v
  examples/
  manifest.json
  rtl/axis_adapter.v
  module_info.json
```

新结构：

```text
axis_adapter/
  skill.json
  compact_card.json
  rtl/axis_adapter.v
```

---

## 10. Benchmark 调整

重点验证：

1. "AXI stream width adapter" → 命中 axis_adapter
2. "stream width conversion" → 命中 axis_adapter
3. 不依赖 README 仍可正确检索
4. retrieval_text 长度显著下降
5. keyword 匹配优于全文匹配

指标：

```text
hit@1
avg_text_length
keyword_match_rate
```

---

## 11. 测试要求

新增测试：

* skill.json schema 校验
* compact_card.json 长度限制
* keyword 数量限制
* 无 README 仍可检索
* RTL 文件路径正确

---

## 12. 非目标

本阶段不做：

* provenance
* EvidencePack
* 自动验证
* template 生成
* 多视图 Skill（暂不支持）
* 参数组合展开

---

## 13. 验收标准

```text
1. 每个模块仅生成 skill.json + compact_card.json
2. Skill 目录结构 ≤ 3 层
3. Router 仅依赖 compact_card.json
4. axis_adapter 可正确检索
5. JSON 总体大小减少 >70%
6. retrieval_text 平均长度减少 >60%
```

---

## 14. 最终系统定位

系统从：

```text
复杂多文件 Skill 包
```

转变为：

```text
极简结构化 Skill + 短文本检索卡片
```

核心原则：

```text
最少字段
最短文本
最强区分度
```

目标：

```text
让 Skill 更像“函数签名”，而不是“文档集合”
```
