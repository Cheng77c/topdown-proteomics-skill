"""Bohrium 镜像用的通用 top-down 流水线执行器。

按 pipeline.json 的 steps 列表逐步执行,每步用 derive_inputs 从上游产物 + 外部输入
(fasta/feature/ms1ft)自动接线,经注入的同步 step-runner(镜像里包 ToolService)运行。
绕开 JobManager/JobStore。支持:单工具 / 任意起点 / TopPIC 链 / InformedProteomics 链 / flashdeconv。

derive_inputs 来自 td_derive(= runtime/input_derivation 的随包副本)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from td_derive import derive_inputs

# step-runner 契约: (tool, input_specs, output_dir, params) -> 带 .status/.output_files 的结果
StepRunner = Callable[[str, list, str, dict], Awaitable[Any]]

# 非主链的外部输入键(随作业带入,derive_inputs 用作 extras)
_EXTERNAL_KEYS = ("fasta", "feature", "ms1ft")
# 主链起点输入的可接受键(.raw/.mzML/.msalign/.pbf... 都用 spectrum 表达)
_PRIMARY_KEYS = ("spectrum", "primary", "input")


async def run_pipeline(cfg: dict, run_step: StepRunner) -> dict:
    out = Path(cfg["output_dir"])
    inputs = dict(cfg.get("inputs") or {})
    steps = cfg.get("steps") or []
    if not steps:
        return {"status": "failed", "error": "no steps", "steps": []}

    extras = {k: inputs[k] for k in _EXTERNAL_KEYS if inputs.get(k)}
    # 起点:把用户给的**全部非 fasta 输入**(spectrum + 外部 feature/ms1ft 等)当作
    # "INPUT 节点"产物,供第一步 derive_inputs 派生——这样任意起点(如从 msalign 起、
    # 外部带 feature)也能被接线。derive_inputs 的 feature/ms1ft 是从产物池挑的,不从 extras。
    prev_node = "INPUT"
    prev_outputs = [v for k, v in inputs.items() if k != "fasta" and v]
    ancestors: list[tuple[str, list[str]]] = []  # 最近优先,供 mspathfindert 取祖先 pbf
    done: list[str] = []
    flashdeconv_used = False

    for i, step in enumerate(steps):
        tool = step["tool"]
        params = dict(step.get("params") or {})
        # FlashDeconv 的 feature 列布局与 TopFD 不同(16 vs 17 列)会让 TopPIC 段错误;
        # 上游用过 flashdeconv 时,给 toppic 关掉 feature 接力。
        if tool == "toppic" and flashdeconv_used:
            params.setdefault("no_topfd_feature", True)

        specs, missing = derive_inputs(prev_node, prev_outputs, tool,
                                       extras=extras, ancestors=ancestors)
        if missing:
            return {"status": "failed", "failed_step": tool,
                    "missing_inputs": missing, "steps": done}

        step_dir = str(out / f"{i:02d}_{tool}")
        try:
            result = await run_step(tool, specs, step_dir, params)
        except Exception as exc:
            # ToolService.submit 校验失败抛异常(非返回 failed);捕获写进 summary 以便诊断
            return {"status": "failed", "failed_step": tool, "steps": done,
                    "failed_step_dir": step_dir, "error": f"{type(exc).__name__}: {exc}"}
        if getattr(result, "status", None) != "completed":
            # error_message 是笼统句(如 "failed with exit code 1");工具真错在 log_tail。
            # 拼进 error,免得只看到 exit code 还得手动下日志(踩过:fasta_idx readonly)。
            em = getattr(result, "error_message", None) or "failed"
            tail = getattr(result, "log_tail", None) or ""
            err = em
            if tail:
                last = "\n".join(tail.splitlines()[-15:]).strip()
                if last:
                    err = f"{em}\n--- 工具日志尾 ---\n{last}"
            return {"status": "failed", "failed_step": tool, "steps": done,
                    "failed_step_dir": step_dir, "error": err}
        done.append(tool)
        if tool == "flashdeconv":
            flashdeconv_used = True
        ancestors.insert(0, (prev_node, prev_outputs))
        prev_node = step_dir
        prev_outputs = list(result.output_files)

    terminal_dir = str(out / f"{len(steps) - 1:02d}_{steps[-1]['tool']}")
    return {"status": "completed", "steps": done, "output_dir": terminal_dir}
