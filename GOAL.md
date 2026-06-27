# GOAL：为 HDL Agent 增加终态 IP Spec 与 C++ Reference Model 伴生产物

## 0. 当前项目边界

现有 `hdl_agent` 已经能完成：

```text
user request
→ query_plan.json
→ skill retriever
→ selected skill context
→ generated HDL
→ iverilog syntax check / repair
→ final RTL under work/generated/
```

本阶段目标是在这个链路之后新增伴生产物：

```text
final generated RTL
→ final_ip_context.json
→ engineer_spec.json
→ cpp_model.json
→ generated C++17 reference model
→ C++ build/test reports
```

这些伴生产物只服务 demo 展示和后续验证，不参与 builder/retriever 评测，不修改 `compact_card.json` 的职责。

## 1. 本阶段最终产物

一次 `hdl_agent` run 的输出目录应形如：

```text
work/generated/<ip_name>/
├── query_plan.json
├── retrieval_trace.json
├── <ip_name>.v
├── final_ip_context.json
├── engineer_spec.json
├── cpp_model.json
├── cpp/
│   ├── <ip_name>_ref.h
│   ├── <ip_name>_ref.cpp
│   ├── test_<ip_name>_ref.cpp
│   └── CMakeLists.txt
└── reports/
    ├── iverilog_check.json
    ├── cpp_build.json
    └── cpp_test.json
```

`<ip_name>.v` 是最终定制 RTL。
`engineer_spec.json` 是人类工程师爱读的结构化规格。
`cpp_model.json` 是 C++ reference model 的生成契约。
`cpp/` 下文件是可编译的 C++17 参考模型与单元测试。

## 2. 严格边界

必须遵守以下边界：

```text
1. 不修改 compact_card.json 的检索职责。
2. 不在 compact_card.json 里加入 spec、verification、C++、evidence、provenance、quality 字段。
3. 不引入 customization_plan.json。本阶段只记录终态，不记录定制变化过程。
4. 新增 final_ip_context.json，作为最终生成 IP 的终态摘要。
5. engineer_spec.json 与 cpp_model.json 必须基于 final_ip_context.json 生成。
6. C++ reference model 不允许直接由 RTL 硬猜生成。
7. C++ reference model 必须先生成 cpp_model.json，再生成 C++ 文件。
8. LLM 是 spec/model 生成主路径，不允许用启发式规则替代 LLM。
9. 允许使用确定性代码抽取事实，例如 final RTL module name、ports、parameters、clock/reset candidates。
10. 禁止通过模块名关键词硬编码行为，例如 if "priority_encoder" then generate fixed C++。
11. 禁止用一组规则直接根据 skill_id 生成 engineer_spec 或 C++。
12. 本阶段不做 UVM、不做 DPI-C、不做 Verilator RTL/C++ 对拍、不做 HLS。
13. 本阶段 C++ reference model 只要求演示级：C++17 编译通过，directed unit tests 通过。
14. 对复杂协议模块允许生成 transaction-level helper，不承诺 cycle-accurate model。
15. 如果语义缺失或冲突，必须在 cpp_model.json 中写入 unknowns/conflicts，并默认跳过 C++ 代码生成。
```

## 3. 禁止偷懒实现

以下实现方式明确禁止：

```text
禁止：根据 skill_id 写死 C++ 生成逻辑
禁止：根据模块名包含 fifo/uart/priority 等字符串直接选择固定模板并填参数
禁止：只看 RTL 全文让 LLM 猜 C++ 代码
禁止：不生成 cpp_model.json 就直接生成 C++
禁止：不做 schema validation 就保存 LLM 输出
禁止：C++ 编译失败仍报告成功
禁止：directed tests 失败仍报告成功
禁止：把 win_idx 等无效状态输出强行规定为 0，除非 spec 明确要求
禁止：把 unknown 语义编造成确定事实
禁止：让 spec/C++ 反向修改已通过 syntax check 的 RTL
```

允许的确定性逻辑仅限于：

```text
1. 读写文件。
2. 调用 retriever。
3. 从 final RTL 抽取 module header、ports、parameters。
4. 构造 final_ip_context.json。
5. 调用 LLM。
6. JSON parse 与 schema validation。
7. 渲染通用文件框架。
8. 调用 g++/clang++ 编译。
9. 运行 C++ unit tests。
10. 记录报告。
```

行为语义必须来自：

```text
user_request
selected skill context
compact_card.json / skill.json
final RTL facts
engineer_spec.json
LLM generated cpp_model.json
```

而不是硬编码规则。

## 4. CLI 需求

现有 `hdl_agent` CLI 保持兼容，新增参数：

```sh
.venv/bin/python -m hdl_agent \
  "<user request>" \
  --skills-root skills \
  --output-dir work/generated/<ip_name> \
  --emit-spec \
  --emit-cpp-ref \
  --build-cpp-ref \
  --run-cpp-ref-tests \
  --show-trace
```

参数语义：

```text
--output-dir
    将一次 agent run 的所有产物写入独立目录。

--emit-spec
    在 final RTL 通过 iverilog 后生成 final_ip_context.json 和 engineer_spec.json。

--emit-cpp-ref
    隐含 --emit-spec。
    从 engineer_spec.json 生成 cpp_model.json 和 C++ reference model 文件。

--build-cpp-ref
    使用 g++ 或 clang++ 编译 generated C++ reference model。

--run-cpp-ref-tests
    隐含 --build-cpp-ref。
    运行 generated C++ unit tests。

--show-trace
    打印 query、retrieve、HDL generation、iverilog、spec、cpp-plan、cpp-codegen、cpp-build、cpp-test 阶段动作。
```

如果用户仍使用：

```sh
--output work/generated/foo.v
```

则保持旧行为。新功能优先使用 `--output-dir`。

## 5. Agent 主流程

主流程必须是：

```text
1. Build query_plan.json from user request.
2. Invoke skill retriever.
3. Save retrieval_trace.json.
4. Select top skill.
5. Generate RTL using selected skill context.
6. Run iverilog -g2012 -Wall.
7. Feed compiler errors back to LLM for up to 3 repair attempts.
8. Save final RTL only after syntax check passes, or save failure report if all repairs fail.
9. If --emit-spec:
      build final_ip_context.json
      call LLM to generate engineer_spec.json
      validate engineer_spec.json
10. If --emit-cpp-ref:
      call LLM to generate cpp_model.json from final_ip_context.json + engineer_spec.json
      validate cpp_model.json
      if cpp_model.json has blocking unknowns/conflicts:
          skip C++ codegen unless --allow-unsafe-cpp-gen is explicitly provided
      otherwise generate C++17 files
11. If --build-cpp-ref:
      compile C++ reference model
      write reports/cpp_build.json
12. If --run-cpp-ref-tests:
      run generated unit tests
      write reports/cpp_test.json
```

Spec/C++ generation must occur only after final RTL syntax check succeeds.

## 6. Data structure：FinalIpContext

新增文件：

```text
final_ip_context.json
```

Schema version:

```text
final_ip_context.v1
```

Required JSON shape:

```json
{
  "schema_version": "final_ip_context.v1",
  "request": "string",
  "selected_skill": {
    "skill_id": "string",
    "skill_dir": "string",
    "score": 0.0,
    "name": "string",
    "compact_card": {
      "skill_id": "string",
      "name": "string",
      "project": "string",
      "category": "string | null",
      "granularity": "string | null",
      "core_function": "string",
      "algorithm": "string | null",
      "interface_signature": "string | null",
      "structure": ["string"],
      "keywords": ["string"],
      "retrieval_text": "string"
    }
  },
  "final_rtl": {
    "module_name": "string",
    "path": "string",
    "syntax_check": "passed",
    "ports": [
      {
        "name": "string",
        "direction": "input | output | inout",
        "width": "integer | string",
        "signed": false
      }
    ],
    "parameters": [
      {
        "name": "string",
        "value": "string | integer | null"
      }
    ],
    "clock_candidates": ["string"],
    "reset_candidates": [
      {
        "name": "string",
        "polarity": "active_high | active_low | unknown",
        "synchronous": "true | false | unknown"
      }
    ],
    "clocking_model": "combinational | sequential | unknown",
    "module_header": "string",
    "short_rtl_excerpt": "string"
  },
  "artifact_paths": {
    "query_plan": "string",
    "retrieval_trace": "string",
    "rtl": "string",
    "engineer_spec": "string",
    "cpp_model": "string",
    "cpp_dir": "string"
  }
}
```

Notes:

```text
- final_ip_context.json is terminal-state context, not a transformation plan.
- It must be built after final RTL passes iverilog.
- It must not describe intermediate repair attempts as semantic truth.
- short_rtl_excerpt should be small and focused: module header, wrapper instantiation, and simple assign/always block if needed.
```

## 7. Data structure：EngineerSpec

新增文件：

```text
engineer_spec.json
```

Schema version:

```text
engineer_spec.v1
```

Required JSON shape:

```json
{
  "schema_version": "engineer_spec.v1",
  "ip_name": "string",
  "source_skill": "string",
  "title": "string",
  "summary": {
    "one_sentence": "string",
    "detailed_description": "string",
    "design_intent": "string"
  },
  "classification": {
    "domain": "string",
    "category": "string",
    "granularity": "leaf | wrapper_ip | composite_ip | unknown",
    "implementation_style": "combinational_logic | sequential_logic | protocol_logic | mixed | unknown",
    "statefulness": "stateless | stateful | unknown",
    "clocking_model": "no_clock | single_clock | multi_clock | unknown"
  },
  "interface": {
    "ports": [
      {
        "name": "string",
        "direction": "input | output | inout",
        "width": "integer | string",
        "role": "string",
        "description": "string"
      }
    ],
    "parameters": [
      {
        "name": "string",
        "value": "string | integer | null",
        "description": "string"
      }
    ],
    "clock": {
      "name": "string",
      "description": "string"
    },
    "reset": {
      "name": "string",
      "polarity": "active_high | active_low | unknown",
      "synchronous": "true | false | unknown",
      "description": "string"
    },
    "interface_summary": "string"
  },
  "behavior": {
    "functional_behavior": ["string"],
    "semantic_rules": ["string"],
    "invalid_or_dont_care_behavior": ["string"],
    "latency": {
      "type": "combinational | fixed_cycle | variable | unknown",
      "cycles": "integer | null",
      "note": "string"
    },
    "throughput": {
      "type": "combinational | one_per_cycle | protocol_limited | unknown",
      "note": "string"
    }
  },
  "usage": {
    "typical_use_cases": ["string"],
    "not_suitable_for": ["string"],
    "integration_notes": ["string"]
  },
  "assumptions_and_constraints": {
    "assumptions": ["string"],
    "constraints": ["string"],
    "unknowns": ["string"]
  },
  "verification_notes": {
    "recommended_strategy": "string",
    "directed_tests": ["string"],
    "random_tests": ["string"],
    "properties_to_check": ["string"],
    "uvm_suitability": "low | medium | high | unknown",
    "uvm_note": "string"
  },
  "human_review": {
    "confidence": "low | medium | high",
    "review_focus": ["string"]
  }
}
```

Rules:

```text
- engineer_spec.json must describe the final generated IP, not the original source skill.
- If behavior is uncertain, write it in assumptions_and_constraints.unknowns.
- Do not include evidence/provenance/tool_runs in this file.
- Do not generate SystemVerilog/UVM code in this file.
- Do not use this file for retrieval embedding.
```

## 8. Data structure：CppModel

新增文件：

```text
cpp_model.json
```

Schema version:

```text
cpp_model.v1
```

Required JSON shape:

```json
{
  "schema_version": "cpp_model.v1",
  "ip_name": "string",
  "source_skill": "string",
  "model_name": "string",
  "model_role": "golden_reference_model",
  "model_kind": "combinational_function | stateful_step_model | protocol_helper_model | unsupported",
  "language": "cpp17",
  "equivalence_scope": {
    "visible_outputs_only": true,
    "cycle_accurate": false,
    "four_state_logic": false,
    "timing_delays": false,
    "notes": ["string"]
  },
  "types": [
    {
      "name": "string",
      "fields": [
        {
          "name": "string",
          "type": "string",
          "width": "integer | null",
          "semantic": "string"
        }
      ]
    }
  ],
  "function_signature": {
    "name": "string",
    "return_type": "string",
    "arguments": [
      {
        "name": "string",
        "type": "string",
        "width": "integer | null",
        "role": "string"
      }
    ]
  },
  "behavior_contract": {
    "preconditions": ["string"],
    "postconditions": ["string"],
    "semantic_choices": ["string"],
    "dont_care_conditions": ["string"],
    "unknowns": ["string"],
    "conflicts": [
      {
        "topic": "string",
        "description": "string",
        "blocking": true
      }
    ]
  },
  "test_vectors": [
    {
      "name": "string",
      "inputs": {
        "key": "value"
      },
      "expected": {
        "key": "value"
      },
      "check_mask": {
        "key": "compare | ignore"
      }
    }
  ],
  "generation_outputs": {
    "header": "string",
    "source": "string",
    "test": "string",
    "build": "string"
  }
}
```

Rules:

```text
- cpp_model.json must be generated before any C++ code.
- cpp_model.json is the source of truth for C++ codegen.
- If behavior_contract.conflicts contains any item with blocking=true, skip C++ codegen unless --allow-unsafe-cpp-gen is provided.
- If behavior_contract.unknowns contains critical missing semantics for the selected model_kind, set model_kind="unsupported" and skip C++ codegen.
- C++ must model only visible outputs of the final generated IP.
- C++ must not claim four-state Verilog X/Z equivalence.
- C++ must not claim gate-level timing equivalence.
```

## 9. Python API requirements

Implement the following modules and functions. Names may be adjusted only if tests are updated accordingly, but the same inputs/outputs must exist.

### 9.1 `hdl_agent.final_ip_context`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

@dataclass
class PortFact:
    name: str
    direction: Literal["input", "output", "inout"]
    width: int | str
    signed: bool = False

@dataclass
class ParameterFact:
    name: str
    value: str | int | None = None

@dataclass
class ResetCandidate:
    name: str
    polarity: Literal["active_high", "active_low", "unknown"] = "unknown"
    synchronous: bool | Literal["unknown"] = "unknown"

@dataclass
class FinalRtlFacts:
    module_name: str
    path: Path
    syntax_check: Literal["passed"]
    ports: list[PortFact]
    parameters: list[ParameterFact]
    clock_candidates: list[str]
    reset_candidates: list[ResetCandidate]
    clocking_model: Literal["combinational", "sequential", "unknown"]
    module_header: str
    short_rtl_excerpt: str

def extract_final_rtl_facts(
    rtl_path: Path,
    *,
    syntax_check_status: Literal["passed"],
) -> FinalRtlFacts:
    """
    Extract final module name, ports, parameters, clock/reset candidates,
    module header, and a short RTL excerpt from the generated RTL.

    This function may use the existing parser/frontend if available.
    It must not infer functional behavior.
    It must raise ValueError if syntax_check_status != "passed".
    """

def build_final_ip_context(
    *,
    request: str,
    selected_skill: dict[str, Any],
    final_rtl_facts: FinalRtlFacts,
    output_dir: Path,
    query_plan_path: Path | None,
    retrieval_trace_path: Path | None,
) -> dict[str, Any]:
    """
    Build final_ip_context.v1 as a JSON-serializable dictionary.
    This is terminal-state context, not a customization plan.
    """

def write_final_ip_context(
    context: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Validate minimal required keys and write pretty JSON.
    """
```

### 9.2 `spec_generator.engineer_spec`

```python
from pathlib import Path
from typing import Any

def build_engineer_spec_prompt(
    *,
    final_ip_context: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Return chat messages for the LLM.
    The prompt must require valid JSON only.
    The prompt must forbid evidence/provenance/tool_runs.
    The prompt must forbid SystemVerilog/UVM code generation.
    The prompt must instruct the LLM to mark unknowns explicitly.
    """

def generate_engineer_spec(
    *,
    llm_client: Any,
    final_ip_context: dict[str, Any],
    max_repair_attempts: int = 1,
) -> dict[str, Any]:
    """
    Call LLM to generate engineer_spec.v1.
    Parse JSON and validate schema.
    If invalid, perform at most max_repair_attempts repair calls.
    Return a JSON-serializable dict.
    """

def validate_engineer_spec(spec: dict[str, Any]) -> None:
    """
    Validate engineer_spec.v1 required structure.
    Raise ValueError with actionable message on failure.
    """

def write_engineer_spec(
    spec: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Write pretty JSON after validation.
    """
```

### 9.3 `cpp_model_gen.model_plan`

```python
from pathlib import Path
from typing import Any

def build_cpp_model_prompt(
    *,
    final_ip_context: dict[str, Any],
    engineer_spec: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Return chat messages for LLM.
    The prompt must require cpp_model.v1 JSON only.
    The prompt must forbid direct C++ code.
    The prompt must ask for model_kind, equivalence_scope, function_signature,
    preconditions, postconditions, unknowns, conflicts, and test_vectors.
    """

def generate_cpp_model_plan(
    *,
    llm_client: Any,
    final_ip_context: dict[str, Any],
    engineer_spec: dict[str, Any],
    max_repair_attempts: int = 1,
) -> dict[str, Any]:
    """
    Call LLM to generate cpp_model.v1.
    Parse JSON and validate schema.
    If invalid, perform at most max_repair_attempts repair calls.
    Return a JSON-serializable dict.
    """

def validate_cpp_model_plan(plan: dict[str, Any]) -> None:
    """
    Validate cpp_model.v1 required structure.
    Raise ValueError with actionable message on failure.
    """

def has_blocking_cpp_model_issue(plan: dict[str, Any]) -> bool:
    """
    Return True if:
    - model_kind == "unsupported"
    - any behavior_contract.conflicts[].blocking == true
    - required signature/test vector fields are missing
    """

def write_cpp_model_plan(
    plan: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Write pretty JSON after validation.
    """
```

### 9.4 `cpp_model_gen.codegen`

```python
from pathlib import Path
from typing import Any

def build_cpp_codegen_prompt(
    *,
    cpp_model_plan: dict[str, Any],
    engineer_spec: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Return chat messages for LLM.
    The prompt may request C++17 files, but must require them in a structured JSON envelope:
    {
      "files": [
        {"path": "...", "content": "..."}
      ]
    }
    The LLM must not write outside the cpp/ directory.
    """

def generate_cpp_files(
    *,
    llm_client: Any,
    cpp_model_plan: dict[str, Any],
    engineer_spec: dict[str, Any],
    output_cpp_dir: Path,
    max_repair_attempts: int = 1,
) -> list[Path]:
    """
    Generate C++17 reference model files from cpp_model.v1.
    Must refuse if has_blocking_cpp_model_issue(plan) is True.
    Must write only:
      - <ip>_ref.h
      - <ip>_ref.cpp
      - test_<ip>_ref.cpp
      - CMakeLists.txt
    Must return written file paths.
    """

def validate_cpp_file_set(
    *,
    files: list[Path],
    output_cpp_dir: Path,
    expected_ip_name: str,
) -> None:
    """
    Ensure required files exist, are under output_cpp_dir,
    and do not contain absolute include paths or shell commands.
    """
```

### 9.5 `cpp_model_gen.build`

```python
from pathlib import Path
from typing import Any

def build_cpp_reference(
    *,
    cpp_dir: Path,
    compiler: str = "g++",
    std: str = "c++17",
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Compile generated C++ reference model and test.
    May use CMake or direct compiler invocation.
    Must capture command, returncode, stdout, stderr.
    Must not report success if returncode != 0.
    """

def run_cpp_reference_tests(
    *,
    cpp_dir: Path,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """
    Run generated C++ unit test executable.
    Must capture command, returncode, stdout, stderr.
    Must not report success if returncode != 0.
    """

def write_report(
    report: dict[str, Any],
    output_path: Path,
) -> Path:
    """
    Write report JSON.
    Reports must include:
      - status: passed | failed | skipped
      - command
      - returncode
      - stdout
      - stderr
    """
```

## 10. LLM requirements

The implementation must use the project’s configured LLM client for:

```text
1. engineer_spec.json generation
2. cpp_model.json generation
3. C++ file generation
```

Fallback to static rules is not allowed.

Acceptable cache behavior:

```text
- It is acceptable to add --use-cached-llm-output for tests.
- Cached output must be treated as prior LLM output.
- The normal demo path must call the LLM.
```

The prompt must state:

```text
You are generating artifacts for the final generated IP, not the original skill.
Use final_ip_context as terminal truth for module name, ports, parameters, and syntax status.
Use engineer_spec as the behavior contract for C++.
Do not invent missing semantics.
Represent missing or conflicting semantics as unknowns/conflicts.
```

## 11. Reports

`reports/iverilog_check.json` should already exist or be added if missing.

`reports/cpp_build.json` shape:

```json
{
  "status": "passed | failed | skipped",
  "command": ["g++", "..."],
  "returncode": 0,
  "stdout": "string",
  "stderr": "string"
}
```

`reports/cpp_test.json` shape:

```json
{
  "status": "passed | failed | skipped",
  "command": ["./test_<ip>_ref"],
  "returncode": 0,
  "stdout": "string",
  "stderr": "string"
}
```

If C++ codegen is skipped due to unknowns/conflicts:

```json
{
  "status": "skipped",
  "reason": "blocking_unknown_or_conflict",
  "details": ["string"]
}
```

## 12. Trace output

With `--show-trace`, the CLI must print stage events like:

```text
[plan] wrote query_plan.json
[retriever] selected skills/priority_encoder score=...
[hdl] wrote custom_priority8.v
[check] iverilog passed
[context] wrote final_ip_context.json
[spec] wrote engineer_spec.json
[cpp-plan] wrote cpp_model.json
[cpp-codegen] wrote cpp/custom_priority8_ref.h
[cpp-codegen] wrote cpp/custom_priority8_ref.cpp
[cpp-codegen] wrote cpp/test_custom_priority8_ref.cpp
[cpp-build] passed
[cpp-test] passed
```

If skipped:

```text
[cpp-codegen] skipped: blocking unknown/conflict in cpp_model.json
```

## 13. First required demo

The first required demo is:

```sh
.venv/bin/python -m hdl_agent \
  "Create IP named custom_priority8 that converts an 8-bit request vector into a valid flag and encoded winning index." \
  --skills-root skills \
  --output-dir work/generated/custom_priority8 \
  --emit-spec \
  --emit-cpp-ref \
  --build-cpp-ref \
  --run-cpp-ref-tests \
  --show-trace
```

Expected behavior:

```text
- Retriever selects skills/priority_encoder.
- Generated RTL module name is custom_priority8.
- Final RTL passes iverilog -g2012 -Wall.
- final_ip_context.json is generated.
- engineer_spec.json describes custom_priority8, not generic priority_encoder.
- cpp_model.json defines a combinational_function C++ reference model.
- Generated C++ function takes uint8_t req.
- Generated C++ result exposes valid and win_idx.
- Directed C++ tests include at least:
    req = 0x00
    req = 0x01
    req = 0x80
    req = 0x29
    req = 0xff
- Tests must not require win_idx to be meaningful when valid is false unless engineer_spec explicitly says so.
- C++ build passes.
- C++ tests pass.
```

## 14. Recommended behavior for complex modules

For UART TX:

```text
Allowed first-stage C++ model:
    protocol_helper_model
    e.g. encode one byte into start/data/stop bit sequence.

Not required:
    full cycle-accurate baud counter model.
```

For AXI-stream register slice:

```text
Allowed first-stage C++ model:
    stateful_step_model draft or unsupported with unknowns.

Do not claim cycle accuracy unless latency, bypass behavior, reset behavior,
and valid-ready stability rules are clearly specified.
```

For reset synchronizer:

```text
Allowed first-stage C++ model:
    stateful step model for reset chain behavior.

Do not claim CDC correctness proof.
```

## 15. Acceptance criteria

This stage is complete when:

```text
1. Existing hdl_agent examples still work without new flags.
2. --output-dir writes a self-contained artifact directory.
3. --emit-spec generates valid engineer_spec.json after final RTL syntax check passes.
4. --emit-cpp-ref generates valid cpp_model.json after engineer_spec.json.
5. C++ codegen refuses to run on blocking unknown/conflict unless explicitly overridden.
6. custom_priority8 demo generates C++17 files.
7. custom_priority8 C++ reference model builds with g++ or clang++.
8. custom_priority8 directed C++ tests pass.
9. --show-trace prints all new stages.
10. No heuristic-only behavior generator is used.
11. compact_card.json remains retrieval-only.
```

## 16. Non-goals

Do not implement these in this stage:

```text
- UVM generation
- DPI-C integration
- Verilator RTL/C++ co-simulation
- HLS
- Formal verification
- Coverage closure
- Full protocol verification
- Full cycle-accurate C++ model for every skill
- Batch generation for all skills
- Heavy evidence/provenance/quality tracking
- customization_plan.json or transformation trace
```

This stage is a demo-quality extension of `hdl_agent`: generated RTL plus human-readable spec plus executable C++ reference model for selected simple IP customizations.
