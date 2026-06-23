import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill/topdown-proteomics/scripts"))
import collect_results as cr


def _fake_download(dl_dir, summary, with_mzml=True):
    """模拟 bohr job download 把 out/ 拉到 dl_dir。"""
    out = Path(dl_dir) / "22926999_job" / "out"
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(summary))
    term = out / "02_toppic"; term.mkdir()
    (term / "x_toppic_prsm_single.tsv").write_text("data\n")
    if with_mzml:
        mz = out / "00_msconvert"; mz.mkdir()
        (mz / "x.mzML").write_text("big")


def test_parses_downloaded_summary(tmp_path):
    summ = {"status": "completed", "metrics": {"prsm_rows": 159},
            "deliverables": ["02_toppic/x_toppic_prsm_single.tsv", "00_msconvert/x.mzML"],
            "contract_version": 1}
    dl = tmp_path / "dl"
    r = cr.collect("999", dl_dir=str(dl), expected_version=1,
                   downloader=lambda jid, d: _fake_download(d, summ))
    assert r["status"] == "completed" and r["metrics"]["prsm_rows"] == 159
    assert any(p.endswith("x.mzML") for p in r["deliverable_paths"])    # 报本地路径
    assert Path(r["deliverable_paths"][0]).exists()                     # 真在本地
    assert not r.get("version_warning")


def test_version_warning_when_stale(tmp_path):
    summ = {"status": "completed", "contract_version": 0}
    r = cr.collect("998", dl_dir=str(tmp_path / "dl2"), expected_version=1,
                   downloader=lambda jid, d: _fake_download(d, summ, with_mzml=False))
    assert r["version_warning"]


def test_missing_summary_reports_error(tmp_path):
    r = cr.collect("997", dl_dir=str(tmp_path / "dl3"), downloader=lambda jid, d: None)
    assert r["ok"] is False and "summary.json" in r["error"]


def test_unzips_download_out_zip(tmp_path):
    # bohr job download 实际给的是 out.zip;collect 必须先解压(Task7 曾漏掉=真 bug)
    import json as _j, zipfile
    def _zip_download(jid, d):
        dd = Path(d); dd.mkdir(parents=True, exist_ok=True)
        staging = dd / "_s" / "out"; staging.mkdir(parents=True)
        (staging / "summary.json").write_text(_j.dumps(
            {"status": "completed", "metrics": {"prsm_rows": 159},
             "deliverables": [], "contract_version": 1}))
        with zipfile.ZipFile(dd / "out.zip", "w") as z:
            z.write(staging / "summary.json", "out/summary.json")
    r = cr.collect("996", dl_dir=str(tmp_path / "dlz"), downloader=_zip_download)
    assert r["ok"] is True and r["metrics"]["prsm_rows"] == 159


def test_failed_surfaces_log_tail(tmp_path):
    import json as _j, zipfile
    def _dl(jid, d):
        out = Path(d) / "j" / "out"; (out / "failed_logs").mkdir(parents=True)
        (out / "summary.json").write_text(_j.dumps(
            {"status": "failed", "failed_step": "toppic",
             "error": "toppic failed with exit code 1", "contract_version": 1, "deliverables": []}))
        (out / "failed_logs" / "toppic_stdout.log").write_text(
            "line1\nLOG ERROR: fasta_idx could not be created (readonly)\n")
    r = cr.collect("955", dl_dir=str(tmp_path / "d"), downloader=_dl)
    assert r["status"] == "failed"
    assert "exit code 1" in r["error"]
    assert "fasta_idx" in r["failed_log_tail"]


def test_collect_computes_rich_metrics(tmp_path):
    # collect 从下载产物实算 PrSM/proteoform/protein(旧镜像 summary 偏薄也能富)
    import json as _j
    def _dl(jid, d):
        out = Path(d) / "j" / "out" / "02_toppic"; out.mkdir(parents=True)
        (Path(d) / "j" / "out" / "summary.json").write_text(_j.dumps(
            {"status": "completed", "metrics": {"prsm_rows": 126}, "deliverables": [], "contract_version": 1}))
        (out / "x_toppic_prsm_single.tsv").write_text(
            "Number of identified PrSMs: 126\nNumber of identified proteoforms: 46\n"
            "Number of identified proteins: 25\nData file name\n")
    r = cr.collect("954", dl_dir=str(tmp_path / "d"), downloader=_dl)
    assert r["metrics"] == {"prsm_rows": 126, "proteoforms": 46, "proteins": 25}


def test_flattens_double_nesting_and_keeps_zip(tmp_path):
    # bohr download 多套一层 <jobId>/ + out.zip;collect 拍平成 dl/out/,zip 保留为 dl/<jobId>.zip
    import json as _j, zipfile
    def _dl(jid, d):
        inner = Path(d) / jid / "out" / "02_toppic"; inner.mkdir(parents=True)
        (Path(d) / jid / "out" / "summary.json").write_text(_j.dumps(
            {"status": "completed", "metrics": {}, "deliverables": ["02_toppic/x_prsm.tsv"], "contract_version": 1}))
        (inner / "x_prsm.tsv").write_text("d")
        with zipfile.ZipFile(Path(d) / jid / "out.zip", "w") as z:   # 模拟 bohr 的 out.zip
            z.writestr("out/summary.json", "{}")
    dl = tmp_path / "td-result" / "999"
    r = cr.collect("999", dl_dir=str(dl), downloader=_dl)
    assert (dl / "out" / "summary.json").exists()              # 扁平:dl/out/
    assert not (dl / "999").exists()                           # 冗余 <jobId> 层已删
    assert (dl / "999.zip").exists()                           # zip 保留(供下载)
    assert r["archive"] == str(dl / "999.zip")
    assert r["result_dir"] == str(dl / "out")


def test_collect_idempotent(tmp_path):
    # 连跑两次同一 job:结构恒为 out/ + <jobId>.zip,无顶层散落、无嵌套累积
    import json as _j, zipfile
    def _dl(jid, d):
        inner = Path(d) / jid / "out" / "02_toppic"; inner.mkdir(parents=True)
        (Path(d) / jid / "out" / "summary.json").write_text(_j.dumps(
            {"status": "completed", "metrics": {}, "deliverables": [], "contract_version": 1}))
        (inner / "x_prsm.tsv").write_text("d")
        with zipfile.ZipFile(Path(d) / jid / "out.zip", "w") as z:
            z.writestr("out/summary.json", "{}")
    dl = tmp_path / "td-result" / "999"
    cr.collect("999", dl_dir=str(dl), downloader=_dl)
    cr.collect("999", dl_dir=str(dl), downloader=_dl)      # 第二次
    entries = sorted(p.name for p in dl.iterdir())
    assert entries == ["999.zip", "out"]                   # 顶层只这两个,无散落/无嵌套
    assert (dl / "out" / "summary.json").exists()
    assert not (dl / "999" ).exists() and not (dl / "out" / "02_toppic" / "out").exists()


def test_empty_download_retries_then_reports_bohr_output():
    # 下载空产出(只建空 jobId 目录)→ 重试 → 仍失败则报 bohr 真实输出(非笼统)
    import tempfile
    calls = {"n": 0}
    def _empty_dl(jid, d):
        calls["n"] += 1
        (Path(d) / jid).mkdir(parents=True, exist_ok=True)   # 只建空目录,无 out.zip
        return "Downloading outfile ... (no file produced)"
    dd = tempfile.mkdtemp()
    r = cr.collect("888", dl_dir=str(Path(dd) / "888"), downloader=_empty_dl)
    assert r["ok"] is False
    assert calls["n"] == 2                       # 重试过一次
    assert "bohr" in r["error"] and "no file produced" in r["error"]   # 报真实输出
