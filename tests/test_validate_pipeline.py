import json as _json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill/topdown-proteomics/scripts"))

from validate_pipeline import validate, validate_with_fs

SCRIPT = str(Path(__file__).resolve().parent.parent /
             "skill/topdown-proteomics/scripts/validate_pipeline.py")


def _cfg(steps, **inputs):
    return {"inputs": inputs, "steps": steps}


def test_ok_full_chain():
    r = validate(_cfg([{"tool": "msconvert"}, {"tool": "topfd"},
                       {"tool": "toppic", "params": {"decoy": True}}],
                      spectrum="/d/x.raw", fasta="/d/db.fasta"))
    assert r["ok"] is True and r["errors"] == []


def test_unknown_tool():
    r = validate(_cfg([{"tool": "msconverter"}], spectrum="/d/x.raw"))
    assert r["ok"] is False
    e = r["errors"][0]
    assert e["step"] == 0 and e["field"] == "tool" and "msconverter" in e["problem"]
    assert "msconvert" in str(e["allowed"])


def test_mass_error_not_in_set():
    r = validate(_cfg([{"tool": "topfd"},
                       {"tool": "toppic", "params": {"mass_error_tolerance": 20, "decoy": True}}],
                      spectrum="/d/x.mzML", fasta="/d/db.fasta"))
    errs = [e for e in r["errors"] if e["field"] == "mass_error_tolerance"]
    assert errs and errs[0]["step"] == 1 and errs[0]["allowed"] == [5, 10, 15]


def test_fdr_requires_decoy():
    r = validate(_cfg([{"tool": "topfd"},
                       {"tool": "toppic", "params": {"spectrum_cutoff_type": "FDR"}}],
                      spectrum="/d/x.mzML", fasta="/d/db.fasta"))
    errs = [e for e in r["errors"] if "decoy" in e["fix"].lower() or e["field"] == "decoy"]
    assert errs


def test_num_shift_range():
    r = validate(_cfg([{"tool": "topfd"},
                       {"tool": "toppic", "params": {"num_shift": 3, "decoy": True}}],
                      spectrum="/d/x.mzML", fasta="/d/db.fasta"))
    assert any(e["field"] == "num_shift" for e in r["errors"])


def test_no_topfd_feature_with_shift_crashes():
    r = validate(_cfg([{"tool": "toppic",
                        "params": {"no_topfd_feature": True, "num_shift": 1, "decoy": True}}],
                      spectrum="/d/x_ms2.msalign", fasta="/d/db.fasta"))
    assert any("no_topfd_feature" in e["problem"] or e["field"] == "no_topfd_feature"
               for e in r["errors"])


def test_tda_must_be_int():
    r = validate(_cfg([{"tool": "pbfgen"}, {"tool": "promex"},
                       {"tool": "mspathfindert", "params": {"tda": True}}],
                      spectrum="/d/x.raw", fasta="/d/db.fasta"))
    assert any(e["field"] == "tda" for e in r["errors"])


def test_collects_all_errors_not_just_first():
    r = validate(_cfg([{"tool": "badtool"},
                       {"tool": "toppic", "params": {"num_shift": 9, "decoy": True}}],
                      spectrum="/d/x.raw", fasta="/d/db.fasta"))
    fields = {e["field"] for e in r["errors"]}
    assert "tool" in fields and "num_shift" in fields


def test_local_input_missing_file(tmp_path):
    cfg = {"inputs": {"spectrum": str(tmp_path / "nope.raw")},
           "steps": [{"tool": "msconvert"}]}
    r = validate_with_fs(cfg)
    assert any(e["field"] == "spectrum" and "不存在" in e["problem"] for e in r["errors"])


def test_cli_exit_code_and_json(tmp_path):
    pj = tmp_path / "pipeline.json"
    pj.write_text(_json.dumps({"inputs": {}, "steps": [{"tool": "badtool"}]}))
    p = subprocess.run([sys.executable, SCRIPT, "--pipeline", str(pj)],
                       capture_output=True, text=True)
    assert p.returncode == 1
    out = _json.loads(p.stdout)
    assert out["ok"] is False and out["errors"]


def test_constraints_documented_in_parameters_md():
    md = (Path(__file__).resolve().parent.parent /
          "skill/topdown-proteomics/references/parameters.md").read_text()
    # 校验器里编码的关键约束必须在文档有迹可循,防止两边漂移
    assert "mass_error_tolerance" in md
    assert "5" in md and "10" in md and "15" in md      # mass_error 允许集
    assert "num_shift" in md
    assert "no_topfd_feature" in md
    assert "tda" in md


def test_fasta_on_readonly_dataset_rejected():
    # fasta 放只读 /bohr → toppic 建索引失败,必须提交前拦(用户真踩 job 22931339)
    r = validate(_cfg([{"tool": "msconvert"}, {"tool": "topfd"},
                       {"tool": "toppic", "params": {"decoy": True}}],
                      spectrum="/bohr/ds/v1/upload/x.raw",
                      fasta="/bohr/ds/v1/upload/db.fasta"))
    errs = [e for e in r["errors"] if e["field"] == "fasta" and "只读" in e["problem"]]
    assert errs and "本地" in errs[0]["fix"]


def test_fasta_local_ok_with_bohr_spectrum():
    # 大谱图在 dataset、fasta 本地 → 不报 fasta 错(只查存在性时 /bohr 跳过)
    r = validate(_cfg([{"tool": "topfd"}, {"tool": "toppic", "params": {"decoy": True}}],
                      spectrum="/bohr/ds/v1/upload/x.mzML", fasta="/local/db.fasta"))
    assert not any(e["field"] == "fasta" for e in r["errors"])


def test_large_local_input_must_use_dataset(tmp_path):
    # 大本地输入(>100MB)走 -p 被硬拦,逼 make_dataset(治知行不一)
    big = tmp_path / "st_1.raw"
    big.write_bytes(b"\0" * (101 * 1024 * 1024))      # 101MB
    cfg = {"inputs": {"spectrum": str(big)}, "steps": [{"tool": "msconvert"}]}
    r = validate_with_fs(cfg)
    errs = [e for e in r["errors"] if e["field"] == "spectrum" and "超过" in e["problem"]]
    assert errs and "make_dataset" in errs[0]["fix"]


def test_small_local_input_ok(tmp_path):
    fa = tmp_path / "db.fasta"; fa.write_text(">p\nMKV")     # 小文件 -p 放行
    cfg = {"inputs": {"spectrum": str(fa)}, "steps": [{"tool": "msconvert"}]}
    r = validate_with_fs(cfg)
    assert not any(e["field"] == "spectrum" and "超过" in e["problem"] for e in r["errors"])
