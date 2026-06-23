"""td-run-pipeline CLI 层测试:交付物组装(work/ 终产物 -> out/ + summary.json)。

不依赖真 ToolService/二进制。运行: PYTHONPATH=build:pkg pytest
"""
import json
from pathlib import Path

from td_cli import assemble_deliverables


def test_assemble_copies_all_step_outputs_and_writes_summary(tmp_path):
    # 模拟链跑完: work/ 下 NN_tool 步目录;默认收所有步(含中间 mzML)
    work = tmp_path / "work"
    (work / "00_msconvert").mkdir(parents=True)
    (work / "00_msconvert" / "x.mzML").write_text("mz")     # 中间产物,也收
    term = work / "02_toppic"
    term.mkdir(parents=True)
    (term / "st_prsm.tsv").write_text("scan\tmass\n1\t1000\n")
    (term / "st_proteoform.tsv").write_text("pf\n")

    out = tmp_path / "out"
    result = {
        "status": "completed",
        "steps": ["msconvert", "topfd", "toppic"],
        "output_dir": str(term),
    }
    assemble_deliverables(str(out), result, work_dir=str(work))

    summary = json.loads((out / "summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["steps"] == ["msconvert", "topfd", "toppic"]
    # 所有步产物都收(终端 + 中间)
    assert (out / "02_toppic" / "st_prsm.tsv").exists()
    assert (out / "02_toppic" / "st_proteoform.tsv").exists()
    assert (out / "00_msconvert" / "x.mzML").exists()
    assert "02_toppic/st_prsm.tsv" in summary["deliverables"]
    assert "00_msconvert/x.mzML" in summary["deliverables"]


def test_assemble_on_failure_writes_summary_without_copy(tmp_path):
    out = tmp_path / "out"
    result = {"status": "failed", "failed_step": "topfd", "steps": ["msconvert"]}
    assemble_deliverables(str(out), result)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert summary["failed_step"] == "topfd"
    assert summary["deliverables"] == []


def test_tool_service_runner_submits_then_waits():
    import asyncio
    from td_cli import tool_service_runner

    class FakeResult:
        status = "completed"
        output_files = ("out.tsv",)

    class FakeHandle:
        async def wait(self):
            return FakeResult()

    class FakeSvc:
        def __init__(self):
            self.submitted = []
        async def submit(self, tool, input_specs, output_dir, params):
            self.submitted.append((tool, output_dir, params))
            return FakeHandle()

    svc = FakeSvc()
    run_step = tool_service_runner(svc)
    res = asyncio.run(run_step("topfd", [], "work/topfd", {"a": 1}))
    assert svc.submitted == [("topfd", "work/topfd", {"a": 1})]
    assert res.status == "completed"


def test_run_from_config_resolves_relative_output_dir_to_absolute(tmp_path, monkeypatch):
    # 真 runner 以 cwd=output_dir 跑工具;若传相对 output_dir,工具会在 cwd 内再拼一遍
    # 导致路径翻倍(e2e 实测 bug)。run_from_config 必须把相对 work_root 解析成绝对。
    import asyncio, os, json
    from td_cli import run_from_config

    captured = []

    class FakeResult:
        status = "completed"
        output_files = ()

    class FakeHandle:
        async def wait(self):
            return FakeResult()

    class FakeSvc:
        async def submit(self, tool, input_specs, output_dir, params):
            captured.append(output_dir)
            return FakeHandle()

    cfg_path = tmp_path / "pipeline.json"
    cfg_path.write_text(json.dumps({"inputs": {"spectrum": "/data/st.raw"},
                                    "steps": [{"tool": "msconvert"}]}))
    monkeypatch.chdir(tmp_path)
    # 传相对路径(模拟 Bohrium 工作目录里的 work/ out/)
    asyncio.run(run_from_config(str(cfg_path), svc=FakeSvc(), work_root="work", out_root="out"))
    assert captured, "没有任何步骤被提交"
    assert all(os.path.isabs(o) for o in captured), f"output_dir 非绝对: {captured}"


def test_run_from_config_resolves_relative_input_paths_to_absolute(tmp_path, monkeypatch):
    # runner 暂存输入按路径建符号链接;相对 spectrum/fasta 会变断链(真 job 实测 bug:
    # "[msconvert] no files found matching st_2.raw")。须在 CLI 边界解析成绝对。
    import asyncio, os, json
    from td_cli import run_from_config

    captured = []

    class FakeResult:
        status = "completed"
        output_files = ()

    class FakeHandle:
        async def wait(self):
            return FakeResult()

    class FakeSvc:
        async def submit(self, tool, input_specs, output_dir, params):
            captured.append((tool, [s.path for s in input_specs]))
            return FakeHandle()

    cfg_path = tmp_path / "pipeline.json"
    cfg_path.write_text(json.dumps({"inputs": {"spectrum": "st_2.raw", "fasta": "db.fasta"},
                                    "steps": [{"tool": "msconvert"}]}))
    monkeypatch.chdir(tmp_path)
    asyncio.run(run_from_config(str(cfg_path), svc=FakeSvc(), work_root="work", out_root="out"))
    msconv = next(c for c in captured if c[0] == "msconvert")
    assert all(os.path.isabs(p) for p in msconv[1]), f"msconvert 输入非绝对: {msconv[1]}"


def test_assemble_retains_failed_step_logs(tmp_path):
    # 失败时把出错步骤的 *_stdout.log 收进 out/(否则留 work/ 不回收,无法诊断)
    import json
    from td_cli import assemble_deliverables
    stepdir = tmp_path / "work" / "01_topfd"
    stepdir.mkdir(parents=True)
    (stepdir / "topfd_stdout.log").write_text("FATAL: boom\n")
    out = tmp_path / "out"
    result = {"status": "failed", "failed_step": "topfd", "steps": ["msconvert"],
              "error": "topfd failed", "failed_step_dir": str(stepdir)}
    assemble_deliverables(str(out), result)
    logs = list(out.rglob("*.log"))
    assert any("topfd_stdout" in p.name for p in logs), f"失败日志没收进 out/: {logs}"
    summary = json.loads((out / "summary.json").read_text())
    assert summary["status"] == "failed" and summary["failed_step"] == "topfd"
