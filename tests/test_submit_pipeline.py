import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill/topdown-proteomics/scripts"))
import submit_pipeline as sp


def test_invalid_pipeline_aborts_before_submit(tmp_path, monkeypatch, capsys):
    pj = tmp_path / "pipeline.json"
    pj.write_text(json.dumps({"inputs": {}, "steps": [{"tool": "badtool"}]}))
    called = {"submit": False}
    monkeypatch.setattr(sp, "_submit", lambda wd: called.__setitem__("submit", True) or "1")
    monkeypatch.setattr(sys, "argv", ["x", "--pipeline", str(pj), "--workdir", str(tmp_path / "wd")])
    sp.main()
    out = capsys.readouterr().out
    assert called["submit"] is False        # 校验失败不应提交
    assert "errors" in out


def test_dataset_path_passthrough(tmp_path, monkeypatch):
    fa = tmp_path / "db.fasta"; fa.write_text(">p\nMKV")
    pj = tmp_path / "pipeline.json"
    # 大输入已在 dataset 挂载路径;小 fasta 走 -p
    pj.write_text(json.dumps({"inputs": {"spectrum": "/bohr/st2-x/v1/x.raw", "fasta": str(fa)},
                              "steps": [{"tool": "msconvert"}]}))
    monkeypatch.setenv("PROJECT_ID", "24980")      # 无默认,必须注入
    monkeypatch.setattr(sp, "_submit", lambda wd: "999")
    monkeypatch.setattr(sys, "argv", ["x", "--pipeline", str(pj), "--workdir", str(tmp_path / "wd"),
                                      "--dataset-path", "/bohr/st2-x/v1"])
    sp.main()
    job = json.loads((tmp_path / "wd" / "job.json").read_text())
    assert job["dataset_path"] == ["/bohr/st2-x/v1"]      # 大输入靠挂载
    assert "result_path" not in job                        # job 写不回共享盘,不用 result_path
