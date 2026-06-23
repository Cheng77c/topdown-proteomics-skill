import json
from pathlib import Path

from td_cli import assemble_deliverables, CONTRACT_VERSION


def _make_work(tmp_path):
    work = tmp_path / "work"
    (work / "00_msconvert").mkdir(parents=True)
    (work / "00_msconvert" / "x.mzML").write_text("mz")
    (work / "01_topfd").mkdir(parents=True)
    (work / "01_topfd" / "x_ms2.msalign").write_text("ms")
    return work


def test_default_collects_all_steps(tmp_path):
    # 默认收所有步产物(含中间 mzML),便于按 job 归档
    work = _make_work(tmp_path)
    out = tmp_path / "out"
    result = {"status": "completed", "steps": ["msconvert", "topfd"],
              "output_dir": str(work / "01_topfd")}
    assemble_deliverables(str(out), result, work_dir=str(work))
    got = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    assert "00_msconvert/x.mzML" in got         # 中间产物也收
    assert "01_topfd/x_ms2.msalign" in got      # 各步都收
    assert "summary.json" in got


def test_summary_has_contract_version_and_metrics(tmp_path):
    work = tmp_path / "work"
    (work / "00_toppic").mkdir(parents=True)
    prsm = work / "00_toppic" / "x_toppic_prsm_single.tsv"
    prsm.write_text("********** Parameters **********\nfoo=bar\n"
                    "Data file name\tPrSM ID\n"
                    "x\t1\nx\t2\n")
    out = tmp_path / "out"
    result = {"status": "completed", "steps": ["toppic"],
              "output_dir": str(work / "00_toppic")}
    assemble_deliverables(str(out), result, work_dir=str(work))
    summ = json.loads((out / "summary.json").read_text())
    assert summ["contract_version"] == CONTRACT_VERSION
    assert summ["metrics"]["prsm_rows"] == 2


def test_failed_logs_collected(tmp_path):
    work = tmp_path / "work"
    fsd = work / "01_topfd"; fsd.mkdir(parents=True)
    (fsd / "topfd_stdout.log").write_text("Thread error")
    out = tmp_path / "out"
    result = {"status": "failed", "failed_step": "topfd", "steps": ["msconvert"],
              "failed_step_dir": str(fsd)}
    assemble_deliverables(str(out), result, work_dir=str(work))
    assert (out / "failed_logs" / "topfd_stdout.log").exists()
    summ = json.loads((out / "summary.json").read_text())
    assert summ["status"] == "failed" and summ["contract_version"] == CONTRACT_VERSION


def test_official_counts_and_pipeline_echo(tmp_path):
    # TopPIC 官方计数(PrSM/proteoform/protein)+ pipeline 回显(inputs/steps)
    work = tmp_path / "work"
    (work / "00_toppic").mkdir(parents=True)
    (work / "00_toppic" / "x_toppic_prsm_single.tsv").write_text(
        "********** Parameters **********\n"
        "Number of identified PrSMs: 126\n"
        "Number of identified proteoforms: 88\n"
        "Number of identified proteins: 40\n"
        "Data file name\tPrSM ID\n")
    out = tmp_path / "out"
    result = {"status": "completed", "steps": ["toppic"], "output_dir": str(work / "00_toppic")}
    cfg = {"inputs": {"spectrum": "/bohr/ds/v1/upload/st_1.msalign", "fasta": "db.fasta"},
           "steps": [{"tool": "toppic", "params": {"decoy": True, "mass_error_tolerance": 10}}]}
    assemble_deliverables(str(out), result, work_dir=str(work), config=cfg)
    summ = json.loads((out / "summary.json").read_text())
    assert summ["metrics"] == {"prsm_rows": 126, "proteoforms": 88, "proteins": 40}
    assert summ["pipeline"]["inputs"]["fasta"] == "db.fasta"
    assert summ["pipeline"]["steps"][0]["params"]["mass_error_tolerance"] == 10
