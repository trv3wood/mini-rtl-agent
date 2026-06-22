from __future__ import annotations

import json
import re
from pathlib import Path

from .models import ModuleInfo, Parameter, Port, SkillScore


BUILDER_VERSION = "0.1.0"
PARSER_MODE = "deterministic"


def width_decl(width: str) -> str:
    return "" if width == "1" else f" {width}"


def safe_default_for_output(port: Port) -> str:
    name = port.name.lower()
    if name.endswith("ready") or name in {"ready", "s_axis_tready"}:
        return "1'b1"
    if "empty" in name:
        return "1'b1"
    if "tx" in name or name in {"txd"}:
        return "1'b1"
    return "1'b0"


def module_parameter_header(params: list[Parameter]) -> str:
    if not params:
        return ""
    lines = []
    for idx, param in enumerate(params):
        comma = "," if idx + 1 < len(params) else ""
        default = param.default or "1"
        lines.append(f"    parameter {param.name} = {default}{comma}")
    return " #(\n" + "\n".join(lines) + "\n)"


def port_header(ports: list[Port], output_as_reg: bool = True) -> str:
    lines = []
    for idx, port in enumerate(ports):
        comma = "," if idx + 1 < len(ports) else ""
        data_type = ""
        if port.direction == "output" and output_as_reg:
            data_type = " reg "
        elif port.direction == "inout":
            data_type = " wire "
        else:
            data_type = " wire "
        lines.append(f"    {port.direction}{data_type}{width_decl(port.width)} {port.name}{comma}")
    return "(\n" + "\n".join(lines) + "\n);"


def find_clock(ports: list[Port]) -> str | None:
    for candidate in ("clk", "clock", "wb_clk_i", "aclk"):
        for port in ports:
            if port.direction == "input" and port.name.lower() == candidate:
                return port.name
    for port in ports:
        if port.direction == "input" and "clk" in port.name.lower():
            return port.name
    return None


def find_reset(ports: list[Port]) -> tuple[str, str] | None:
    for port in ports:
        lowered = port.name.lower()
        if port.direction == "input" and ("rst" in lowered or "reset" in lowered):
            active = "0" if lowered.endswith("_n") or lowered.endswith("n") else "1"
            return port.name, active
    return None


def generate_template(module: ModuleInfo) -> str:
    outputs = [port for port in module.ports if port.direction == "output"]
    inouts = [port for port in module.ports if port.direction == "inout"]
    clk = find_clock(module.ports)
    reset = find_reset(module.ports)
    lines = [
        "`timescale 1ns/1ps",
        "",
        f"// Auto-generated educational template for {module.name}.",
        "// This is a simplified local implementation, not copied from source_refs.",
        f"module {module.name}{module_parameter_header(module.parameters)} {port_header(module.ports)}",
    ]
    for port in inouts:
        lines.append(f"    assign {port.name} = 1'bz;")
    if outputs:
        if clk:
            lines.append("")
            lines.append(f"    always @(posedge {clk}) begin")
            if reset:
                reset_name, active = reset
                condition = reset_name if active == "1" else f"!{reset_name}"
                lines.append(f"        if ({condition}) begin")
                for port in outputs:
                    lines.append(f"            {port.name} <= {safe_default_for_output(port)};")
                lines.append("        end else begin")
                for port in outputs:
                    if port.name.lower().endswith("done") or port.name.lower().endswith("valid"):
                        lines.append(f"            {port.name} <= 1'b0;")
                    else:
                        lines.append(f"            {port.name} <= {port.name};")
                lines.append("        end")
            else:
                for port in outputs:
                    lines.append(f"        {port.name} <= {safe_default_for_output(port)};")
            lines.append("    end")
        else:
            lines.append("")
            lines.append("    always @* begin")
            for port in outputs:
                lines.append(f"        {port.name} = {safe_default_for_output(port)};")
            lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def generate_instantiation(module: ModuleInfo) -> str:
    param_block = ""
    if module.parameters:
        assignments = [f"        .{param.name}({param.default or '1'})" for param in module.parameters]
        param_block = " #(\n" + ",\n".join(assignments) + "\n    )"
    ports = ",\n".join(f"        .{port.name}({port.name})" for port in module.ports)
    decls = []
    localparams = [f"    localparam {param.name} = {param.default or '1'};" for param in module.parameters]
    for port in module.ports:
        kind = "wire" if port.direction in {"output", "inout"} else "reg"
        init = " = 0" if kind == "reg" and port.width == "1" else ""
        decls.append(f"    {kind}{width_decl(port.width)} {port.name}{init};")
    return (
        "`timescale 1ns/1ps\n\n"
        f"module example_{module.name};\n"
        + ("\n".join(localparams) + "\n" if localparams else "")
        + "\n".join(decls)
        + "\n\n"
        f"    {module.name}{param_block} dut (\n{ports}\n    );\n"
        "endmodule\n"
    )


def generate_testbench(module: ModuleInfo) -> str:
    clk = find_clock(module.ports)
    reset = find_reset(module.ports)
    localparams = [f"    localparam {param.name} = {param.default or '1'};" for param in module.parameters]
    decls = []
    conns = []
    for port in module.ports:
        if port.direction == "input":
            init = " = 0" if port.width == "1" else " = 0"
            decls.append(f"    reg{width_decl(port.width)} {port.name}{init};")
        else:
            decls.append(f"    wire{width_decl(port.width)} {port.name};")
        conns.append(f"        .{port.name}({port.name})")
    param_block = ""
    if module.parameters:
        assignments = [f"        .{param.name}({param.default or '1'})" for param in module.parameters]
        param_block = " #(\n" + ",\n".join(assignments) + "\n    )"
    lines = [
        "`timescale 1ns/1ps",
        "",
        f"module tb_{module.name};",
        *localparams,
        *decls,
        "",
        f"    {module.name}{param_block} dut (",
        ",\n".join(conns),
        "    );",
    ]
    if clk:
        lines.append(f"    always #5 {clk} = ~{clk};")
    lines.extend(["", "    initial begin", "        #1;"])
    if reset:
        reset_name, active = reset
        inactive = "0" if active == "1" else "1"
        lines.append(f"        {reset_name} = {active};")
        if clk:
            lines.append(f"        repeat (2) @(posedge {clk});")
        else:
            lines.append("        #10;")
        lines.append(f"        {reset_name} = {inactive};")
    if clk:
        lines.append(f"        repeat (4) @(posedge {clk});")
    else:
        lines.append("        #20;")
    lines.append(f"        $display(\"PASS {module.name}\");")
    lines.append("        $finish;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- Not detected."


def fallback_functional_summary(module: ModuleInfo) -> str:
    interface_text = ", ".join(module.interfaces) if module.interfaces else "the extracted RTL interface"
    pattern_text = ", ".join(module.patterns) if module.patterns else "module-specific control/data-path behavior"
    return f"{module.name} implements {pattern_text} for {interface_text}."


def fallback_structural_summary(module: ModuleInfo) -> str:
    ports = len(module.ports)
    params = len(module.parameters)
    return f"The module exposes {ports} ports and {params} parameters; no deeper LLM structural summary was provided."


def fallback_behavior_summary(module: ModuleInfo) -> str:
    if module.states:
        return f"Detected symbolic behavior states: {', '.join(module.states)}."
    return "No explicit state summary was provided; behavior should be inferred from source RTL and interface timing."


def generate_readme(module: ModuleInfo) -> str:
    port_lines = [
        (
            f"`{port.name}` ({port.direction}, {port.width}): {port.description}"
            if port.description
            else f"`{port.name}` ({port.direction}, {port.width})"
        )
        for port in module.ports
    ]
    param_lines = [
        (
            f"`{param.name}` default `{param.default or 'unspecified'}`: {param.description}"
            if param.description
            else f"`{param.name}` default `{param.default or 'unspecified'}`"
        )
        for param in module.parameters
    ] or ["No parameters detected."]
    functional_summary = module.functional_summary or fallback_functional_summary(module)
    structural_summary = module.structural_summary or fallback_structural_summary(module)
    behavior_summary = module.behavior_summary or fallback_behavior_summary(module)
    integration_notes = module.integration_notes or [
        "Confirm clock, reset, and ready/valid timing against the source RTL before integration."
    ]
    limitations = module.limitations or [
        "The generated template is an educational stub and is not behaviorally equivalent to the source RTL."
    ]
    use_cases = module.use_cases or [
        f"Use when a design needs {pattern} behavior." for pattern in module.patterns[:4]
    ] or [f"Use when the `{module.name}` interface matches the target integration."]
    comments = module.comments[:5] or ["No nearby comments were found in the source RTL."]
    return f"""# {module.name}

## Description

{functional_summary}

Category: `{module.category}`. Detected interfaces: {', '.join(module.interfaces) or 'none'}. Detected patterns: {', '.join(module.patterns) or 'none'}.

Source comments:

{markdown_list(comments)}

## When to use

{markdown_list(use_cases)}

## When not to use

{markdown_list(limitations)}

## Architecture

{structural_summary}

## Behavior Model

{behavior_summary}

## Integration Notes

{markdown_list(integration_notes)}

## Port semantics

{markdown_list(port_lines)}

## Parameter semantics

{markdown_list(param_lines)}

## Design pattern

{markdown_list(module.patterns)}

## Verification checklist

- `template.v` compiles with `iverilog -g2012`.
- `examples/tb_{module.name}.v` runs with `vvp` and prints `PASS {module.name}`.
- Reset behavior, if a reset port exists, is exercised by the generated testbench.
- Output ports have deterministic teaching defaults.

## Template Scope

- `template.v` preserves the interface shape for teaching and smoke-test purposes.
- `source_refs` are provenance only; generated files do not copy upstream implementation RTL.
- Passing the generated smoke test is not functional equivalence to the source module.
"""


def module_info_json(module: ModuleInfo) -> str:
    data = {
        "name": module.name,
        "skill_type": "module",
        "category": module.category,
        "description": module.functional_summary or fallback_functional_summary(module),
        "source_refs": [
            {
                "project": "input_repository",
                "repository": "local",
                "commit": None,
                "path": str(module.source_path),
                "module": module.name,
                "url": str(module.source_path),
                "license": "unknown",
                "notes": "Reference only; generated template does not copy source RTL.",
            }
        ],
        "parameters": [
            {
                key: value
                for key, value in {
                    "name": param.name,
                    "default": param.default,
                    "description": param.description,
                }.items()
                if key != "description" or value
            }
            for param in module.parameters
        ],
        "ports": [
            {
                key: value
                for key, value in {
                    "name": port.name,
                    "direction": port.direction,
                    "width": port.width,
                    "description": port.description,
                }.items()
                if key != "description" or value
            }
            for port in module.ports
        ],
        "states": [{"name": state} for state in module.states],
        "constraints": [
            "Review generated template before production use.",
            "source_refs are provenance only and are not runtime dependencies.",
        ],
        "dependencies": [],
        "interfaces": module.interfaces,
        "patterns": module.patterns,
        "functional_summary": module.functional_summary or fallback_functional_summary(module),
        "structural_summary": module.structural_summary or fallback_structural_summary(module),
        "behavior_summary": module.behavior_summary or fallback_behavior_summary(module),
        "integration_notes": module.integration_notes,
        "limitations": module.limitations,
        "use_cases": module.use_cases,
        "implementation_notes": [
            "Generated by deterministic RTL analysis plus structured LLM module analysis.",
            "Template is a simplified teaching implementation; use source_refs and copied RTL closure for provenance.",
        ],
        "test_strategy": [
            "Compile template.v and generated testbench with iverilog -g2012.",
            "Run the simulation with vvp and require a PASS message.",
        ],
        "verification_goals": [
            "Generated files are syntactically valid.",
            "Generated testbench can instantiate the template.",
        ],
        "keywords": module.keywords,
        "provenance": {
            "source_file": str(module.source_path),
            "detected_module_name": module.name,
            "builder_version": BUILDER_VERSION,
            "parser_mode": PARSER_MODE,
        },
    }
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def score_skill(module: ModuleInfo, files_ok: bool, sim_ok: bool) -> SkillScore:
    metadata = 20 if module.parameters is not None and module.ports else 10
    interface = min(20, 5 + len(module.ports) * 2)
    docs = 20 if module.comments or module.patterns else 14
    verification = 20 if sim_ok else 8
    template = 20 if files_ok else 8
    total = metadata + interface + docs + verification + template
    notes = []
    if not module.ports:
        notes.append("No ports extracted.")
    if not module.patterns:
        notes.append("No common design pattern detected.")
    if not sim_ok:
        notes.append("Generated testbench did not pass.")
    return SkillScore(min(100, total), metadata, interface, docs, verification, template, notes)


def sanitize_skill_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    return cleaned or "unnamed_module"
