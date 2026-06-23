"""td-run-pipeline CLI 层:交付物组装 + ToolService 接线 + 入口。

work/ 跑中间步骤(留节点,不回收);out/ 放交付物(Bohrium backward_files 回收 -> /personal)。
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

CONTRACT_VERSION = 1   # 执行器契约版本;collect_results 的 EXPECTED 不一致则告警


def _domain_metrics(out: Path) -> dict:
    """领域指标:TopPIC 官方计数(PrSM/proteoform/protein)+ InformedProteomics IcTda 数。

    优先取 TopPIC 自报的 'Number of identified PrSMs/proteoforms/proteins'(单产物 tsv / 日志的
    参数块),比数行更准;解析不到时回退按数据行计 PrSM。
    """
    import re
    m: dict = {}
    prsm_tsv = next(iter(out.rglob("*_toppic_prsm_single.tsv")), None)
    log = next(iter(out.rglob("*toppic*stdout*.log")), None)
    txt = "".join(p.read_text(errors="replace") for p in (prsm_tsv, log) if p)
    for key, label in (("prsm_rows", "PrSMs"), ("proteoforms", "proteoforms"), ("proteins", "proteins")):
        mm = re.search(r"Number of identified " + label + r":\s*(\d+)", txt)
        if mm:
            m[key] = int(mm.group(1))
    if "prsm_rows" not in m and prsm_tsv:   # 回退:数据行数(扣参数块 + 表头)
        lines = prsm_tsv.read_text(errors="replace").splitlines()
        hdr = next((i for i, l in enumerate(lines) if "data file name" in l.lower()), None)
        if hdr is not None:
            m["prsm_rows"] = sum(1 for l in lines[hdr + 1:] if l.strip())
    ictda = next(iter(out.rglob("*_IcTda.tsv")), None)
    if ictda:
        rows = [l for l in ictda.read_text(errors="replace").splitlines() if l.strip()]
        m["ictda_ids"] = max(0, len(rows) - 1)
    return m


def tool_service_runner(svc):
    """把 ToolService 包成执行器要的 step-runner: submit -> wait -> ToolResult。"""
    async def run_step(tool, input_specs, output_dir, params):
        handle = await svc.submit(tool, input_specs, output_dir, params)
        return await handle.wait()
    return run_step


def assemble_deliverables(out_dir: str, result: dict, work_dir: str | None = None,
                          collect: list | None = None, config: dict | None = None) -> None:
    """把终端步 + collect 指定步的产物拷进 out/<NN_tool>/,写 rich out/summary.json。

    out/ 经 backward_files 由 bohr job download 拉回(job 节点隔离,写不回共享盘)。
    默认只收终端步(小);中间大产物(mzML)须 pipeline.json `collect` 指定才收(下载贵)。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deliverables: list[str] = []
    # 默认收**所有步**的产物(每步一个 out/<NN_tool>/),含中间 mzML/msalign 等——
    # 一个 job 的全部结果都在 out/ 下,便于按 job 归档。collect 参数保留但不再用于过滤。
    if work_dir and Path(work_dir).exists():
        for step_dir in sorted(Path(work_dir).iterdir()):
            if not step_dir.is_dir():
                continue
            dest = out / step_dir.name
            dest.mkdir(parents=True, exist_ok=True)
            for f in sorted(step_dir.iterdir()):
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
                    deliverables.append(f"{step_dir.name}/{f.name}")
    # 失败时把出错步骤的日志收进 out/failed_logs/(否则留 work/ 不回收,无法诊断)
    fsd = result.get("failed_step_dir")
    if result.get("status") == "failed" and fsd and Path(fsd).exists():
        logs = out / "failed_logs"
        logs.mkdir(parents=True, exist_ok=True)
        for f in sorted(Path(fsd).iterdir()):
            if f.is_file() and (f.suffix == ".log" or f.name.endswith("_stdout.log")):
                shutil.copy2(f, logs / f.name)
                deliverables.append(f"failed_logs/{f.name}")
    summary = {k: v for k, v in result.items() if k not in ("output_dir", "failed_step_dir")}
    summary["deliverables"] = deliverables
    summary["metrics"] = _domain_metrics(out)
    # 溯源:回显本次跑了哪些输入 + 步骤/参数(pipeline.json 在 -p 包,不在 out/,故记进 summary)
    if config:
        summary["pipeline"] = {
            "inputs": config.get("inputs", {}),
            "steps": config.get("steps", []),
        }
        if config.get("collect"):
            summary["pipeline"]["collect"] = config["collect"]
    summary["contract_version"] = CONTRACT_VERSION
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )


async def run_from_config(config_path: str, svc=None,
                          work_root: str = "work", out_root: str = "out") -> dict:
    """读 pipeline.json -> 中间步骤落 work/ -> 跑步骤列表 -> 交付物组装到 out/。"""
    from td_pipeline import run_pipeline

    cfg = json.loads(Path(config_path).read_text())
    # output_dir 解析为绝对:真 runner 以 cwd=output_dir 跑工具,相对路径会被再拼一遍致翻倍。
    # work/out 仍在 CWD 下,故 Bohrium 的相对 backward_files("out/")照样命中。
    cfg["output_dir"] = str(Path(work_root).resolve())
    # inputs 里的本地路径也解析为绝对:runner 暂存按路径建符号链接,相对路径会变断链
    # (真 job 实测: "[msconvert] no files found")。/bohr 挂载路径已是绝对,原样保留。
    inputs = cfg.get("inputs") or {}
    for k, v in list(inputs.items()):
        if v and not str(v).startswith("/bohr/"):
            inputs[k] = str(Path(v).resolve())
    cfg["inputs"] = inputs
    abs_out = str(Path(out_root).resolve())
    if svc is None:
        from topdown_agent.service import ToolService
        svc = ToolService.auto()
    result = await run_pipeline(cfg, tool_service_runner(svc))
    # 终端 + collect 指定步产物 + rich summary 进 out/(backward_files 回收,download 拉回)
    assemble_deliverables(abs_out, result, work_dir=cfg["output_dir"],
                          collect=cfg.get("collect"), config=cfg)
    return result


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="td-run-pipeline",
                                 description="Run the top-down proteomics pipeline (Bohrium job entry).")
    ap.add_argument("--config", required=True, help="pipeline.json 路径(相对工作目录)")
    ap.add_argument("--work", default="work", help="中间产物目录(不回收)")
    ap.add_argument("--out", default="out", help="交付物目录(backward_files 回收)")
    args = ap.parse_args(argv)
    result = asyncio.run(run_from_config(args.config, work_root=args.work, out_root=args.out))
    print(json.dumps({k: v for k, v in result.items() if k != "output_dir"}, ensure_ascii=False))
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
