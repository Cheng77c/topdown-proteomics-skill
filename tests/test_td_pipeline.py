"""通用步骤列表执行器测试(单工具/任意起点/两条主线/flashdeconv/失败/缺输入)。

注入假 step-runner(不跑真二进制),断言接线(derive_inputs)与步序/参数。
运行: PYTHONPATH=build pytest deploy/bohrium-image/tests/
"""
import asyncio
from dataclasses import dataclass

from td_pipeline import run_pipeline
from topdown_agent.runtime.models import InputType


@dataclass
class FakeResult:
    status: str
    output_files: tuple


# 各工具的预设产物(文件名匹配 derive_inputs 的扩展规则)
_OUTPUTS = {
    "msconvert": ["x.mzML"],
    "topfd": ["x_ms2.msalign", "x_ms2.feature"],
    "flashdeconv": ["x_ms2.msalign", "x_ms2.feature"],
    "toppic": ["x_toppic_prsm.tsv"],
    "pbfgen": ["x.pbf"],
    "promex": ["x.ms1ft"],
    "mspathfindert": ["x_IcTda.tsv"],
}


class Recorder:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or _OUTPUTS

    async def __call__(self, tool, input_specs, output_dir, params):
        self.calls.append({"tool": tool, "input_specs": list(input_specs),
                           "output_dir": output_dir, "params": dict(params)})
        files = tuple(f"{output_dir}/{f}" for f in self.outputs[tool])
        return FakeResult(status="completed", output_files=files)


def _cfg(steps, **inputs):
    return {"output_dir": "/work", "inputs": inputs, "steps": steps}


def _run(cfg, rec):
    return asyncio.run(run_pipeline(cfg, rec))


def test_single_tool_msconvert():
    rec = Recorder()
    r = _run(_cfg([{"tool": "msconvert"}], spectrum="/d/x.raw"), rec)
    assert [c["tool"] for c in rec.calls] == ["msconvert"]
    assert r["status"] == "completed"
    assert rec.calls[0]["input_specs"][0].path == "/d/x.raw"


def test_full_toppic_chain_wires_msalign_fasta_feature():
    rec = Recorder()
    _run(_cfg([{"tool": "msconvert"}, {"tool": "topfd"}, {"tool": "toppic"}],
              spectrum="/d/x.raw", fasta="/d/db.fasta"), rec)
    assert [c["tool"] for c in rec.calls] == ["msconvert", "topfd", "toppic"]
    specs = rec.calls[-1]["input_specs"]
    names = {s.name for s in specs}
    assert names == {"msalign", "fasta", "feature"}
    feat = next(s for s in specs if s.name == "feature")
    assert feat.input_type == InputType.EXTERNAL
    assert feat.staged_as == "x_ms2.feature"  # {msalign stem}.feature


def test_arbitrary_start_at_toppic():
    rec = Recorder()
    _run(_cfg([{"tool": "toppic", "params": {"decoy": True}}],
              spectrum="/d/x_ms2.msalign", fasta="/d/db.fasta"), rec)
    assert [c["tool"] for c in rec.calls] == ["toppic"]
    names = {s.name for s in rec.calls[0]["input_specs"]}
    assert "msalign" in names and "fasta" in names


def test_flashdeconv_injects_no_topfd_feature_into_toppic():
    rec = Recorder()
    _run(_cfg([{"tool": "msconvert"}, {"tool": "flashdeconv"}, {"tool": "toppic"}],
              spectrum="/d/x.raw", fasta="/d/db.fasta"), rec)
    assert [c["tool"] for c in rec.calls] == ["msconvert", "flashdeconv", "toppic"]
    assert rec.calls[-1]["params"].get("no_topfd_feature") is True


def test_informed_chain_wires_pbf_from_ancestor_to_mspathfindert():
    rec = Recorder()
    _run(_cfg([{"tool": "pbfgen"}, {"tool": "promex"}, {"tool": "mspathfindert"}],
              spectrum="/d/x.raw", fasta="/d/db.fasta"), rec)
    assert [c["tool"] for c in rec.calls] == ["pbfgen", "promex", "mspathfindert"]
    paths = [s.path for s in rec.calls[-1]["input_specs"]]
    assert any(p.endswith(".pbf") for p in paths), "pbf 未从祖先接到 mspathfindert"
    assert any(p.endswith(".ms1ft") for p in paths)
    assert any(p.endswith("db.fasta") for p in paths)


def test_chain_halts_on_step_failure():
    class FailAtTopfd:
        def __init__(self):
            self.calls = []

        async def __call__(self, tool, specs, out, params):
            self.calls.append(tool)
            ok = tool != "topfd"
            return FakeResult(
                status="completed" if ok else "failed",
                output_files=tuple(f"{out}/{f}" for f in _OUTPUTS[tool]) if ok else (),
            )

    rec = FailAtTopfd()
    r = asyncio.run(run_pipeline(
        _cfg([{"tool": "msconvert"}, {"tool": "topfd"}, {"tool": "toppic"}],
             spectrum="/d/x.raw", fasta="/d/db.fasta"), rec))
    assert rec.calls == ["msconvert", "topfd"]
    assert r["status"] == "failed" and r["failed_step"] == "topfd"


def test_missing_fasta_reports_missing_without_running():
    rec = Recorder()
    r = _run(_cfg([{"tool": "toppic"}], spectrum="/d/x_ms2.msalign"), rec)  # 无 fasta
    assert r["status"] == "failed"
    assert "fasta" in r.get("missing_inputs", [])
    assert rec.calls == []  # 缺输入不应提交


def test_arbitrary_start_toppic_wires_provided_feature():
    # 从 msalign 起步、外部提供 feature:必须接到 toppic(任意起点场景,真 job 实测 bug)
    rec = Recorder()
    _run(_cfg([{"tool": "toppic", "params": {"decoy": True}}],
              spectrum="/d/x_ms2.msalign", fasta="/d/db.fasta", feature="/d/x_ms2.feature"), rec)
    specs = rec.calls[-1]["input_specs"]
    names = {s.name for s in specs}
    assert names == {"msalign", "fasta", "feature"}, f"feature 没接上: {names}"
    feat = next(s for s in specs if s.name == "feature")
    assert feat.path == "/d/x_ms2.feature"


def test_step_runner_exception_becomes_failed_not_crash():
    # ToolService.submit 校验失败会抛异常(非返回 failed);执行器须捕获→写进 summary,别崩
    class Boom:
        def __init__(self):
            self.calls = []
        async def __call__(self, tool, specs, out, params):
            self.calls.append(tool)
            raise RuntimeError("input validation failed")
    r = asyncio.run(run_pipeline(_cfg([{"tool": "msconvert"}], spectrum="/d/x.raw"), Boom()))
    assert r["status"] == "failed"
    assert r["failed_step"] == "msconvert"
    assert "validation failed" in (r.get("error") or "")


def test_failure_includes_log_tail_in_error():
    # 工具失败时,真错(log_tail)要拼进 error,不能只给笼统 exit code(踩过)
    class Boom:
        async def __call__(self, tool, specs, out, params):
            class R:
                status = "failed"
                error_message = "toppic failed with exit code 1"
                log_tail = "Reading database\nLOG ERROR: fasta_idx could not be created (readonly)\n"
                output_files = ()
            return R()
    r = asyncio.run(run_pipeline(
        _cfg([{"tool": "toppic"}], spectrum="/d/x_ms2.msalign", fasta="/d/db.fasta",
             feature="/d/x_ms2.feature"), Boom()))
    assert r["status"] == "failed"
    assert "exit code 1" in r["error"] and "fasta_idx" in r["error"]   # 笼统+真错都在
