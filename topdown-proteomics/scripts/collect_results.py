#!/usr/bin/env python3
"""bohr job download 拉回 job 的 out/,解析 summary.json,报指标 + 本地交付物路径。输出 JSON。

job 节点隔离、写不回共享盘,故结果只能 download。小 summary + 终端产物默认下载;
大中间产物(mzML)须 pipeline.json `collect` 指定后才在 out/ 里、随之下载。
"""
import argparse
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

EXPECTED_CONTRACT_VERSION = 1   # 与 td_cli.CONTRACT_VERSION 对齐


def _metrics_from_out(out_dir: Path) -> dict:
    """从下载回的产物直接算领域指标(TopPIC 官方 PrSM/proteoform/protein + IcTda)。

    与镜像 td_cli._domain_metrics 同口径;放 collect 这边,旧镜像也能得富指标。
    """
    m: dict = {}
    prsm_tsv = next(iter(out_dir.rglob("*_toppic_prsm_single.tsv")), None)
    log = next(iter(out_dir.rglob("*toppic*stdout*.log")), None)
    txt = "".join(p.read_text(errors="replace") for p in (prsm_tsv, log) if p)
    for key, label in (("prsm_rows", "PrSMs"), ("proteoforms", "proteoforms"), ("proteins", "proteins")):
        mm = re.search(r"Number of identified " + label + r":\s*(\d+)", txt)
        if mm:
            m[key] = int(mm.group(1))
    ictda = next(iter(out_dir.rglob("*_IcTda.tsv")), None)
    if ictda:
        rows = [l for l in ictda.read_text(errors="replace").splitlines() if l.strip()]
        m["ictda_ids"] = max(0, len(rows) - 1)
    return m


def _bohr_download(job_id: str, dl_dir: str) -> str:
    Path(dl_dir).mkdir(parents=True, exist_ok=True)
    # bohr 直接跑(ACCESS_KEY 经 env 继承——调用前须 source .bohr_env);返回输出供出错时诊断
    p = subprocess.run(["bohr", "job", "download", "-j", job_id, "-o", dl_dir],
                       capture_output=True, text=True)
    return (p.stdout or "") + (p.stderr or "")


def _has_result(dl: Path) -> bool:
    return any(dl.rglob("*.zip")) or any(dl.rglob("summary.json"))


def collect(job_id: str, dl_dir: str, expected_version: int = EXPECTED_CONTRACT_VERSION,
            downloader=_bohr_download) -> dict:
    dl = Path(dl_dir)
    # 幂等关键:download 前清空目录。否则重复 collect 时,rglob 会把上次保留的 <jobId>.zip
    # 重新解压污染顶层、或锚到上次 out/summary.json 跳过扁平化 → 结构错乱(非幂等)。
    # 结果在 Bohrium 结果库,清掉本地副本可随时重下,安全。
    if dl.exists():
        shutil.rmtree(dl)
    dl.mkdir(parents=True, exist_ok=True)
    # 下载 + 校验产出:bohr download 偶发空产出(只建空 jobId 目录,无 out.zip)。
    # 校验没拿到结果就重试一次;仍失败则报 bohr 真实输出,而非笼统"没找到 summary"——
    # 否则 agent 会被迫手动 download/解压,搞出 dl/、out/out/ 等混乱。
    log = downloader(job_id, dl_dir) or ""
    if not _has_result(dl):
        log += "\n--- 重试 download ---\n" + (downloader(job_id, dl_dir) or "")
    if not _has_result(dl):
        return {"ok": False, "jobId": job_id,
                "error": f"bohr job download 未产出结果(out.zip/summary.json),重试仍失败。"
                         f"bohr 输出: {log[-500:]}"}
    # bohr job download 把结果打成 out.zip:解压用于读取/扁平化(此刻 dl 只有本次产物,rglob 安全)。
    for z in dl.rglob("*.zip"):
        try:
            zipfile.ZipFile(z).extractall(z.parent)
        except Exception:
            pass
    summ = next(iter(dl.rglob("summary.json")), None)
    if not summ:
        return {"ok": False, "jobId": job_id, "error": f"download 后未找到 summary.json: {dl_dir}"}
    # 扁平化:bohr download 多套一层 <jobId>/。把 out/ 提到 dl/out;再无条件把 zip 归位到
    # dl/<jobId>.zip 保留(供下载)、清掉残留中间层。最终:dl/out/(可读)+ dl/<jobId>.zip。
    src_out = summ.parent                    # 形如 dl/<jobId>/out
    final_out = dl / "out"
    if src_out.resolve() != final_out.resolve():
        if final_out.exists():
            shutil.rmtree(final_out)
        shutil.move(str(src_out), str(final_out))
        summ = final_out / "summary.json"
    archive = None                           # zip 归位 + 清场:无条件执行(不嵌在 if 内)
    for z in list(dl.rglob("*.zip")):
        archive = dl / f"{job_id}.zip"
        if z.resolve() != archive.resolve():
            shutil.move(str(z), str(archive))
    for child in dl.iterdir():
        if child.is_dir() and child.name != "out":
            shutil.rmtree(child, ignore_errors=True)
    summary = json.loads(summ.read_text())
    out_dir = summ.parent
    paths = [str(out_dir / d) for d in summary.get("deliverables", [])]
    warn = ""
    if summary.get("contract_version", 0) < expected_version:
        warn = "镜像执行器版本偏旧(contract_version < 期望),建议重建镜像 v2"
    # 指标:以下载产物实算为准(覆盖镜像 summary 里可能偏薄的 metrics),旧镜像也得富指标
    metrics = dict(summary.get("metrics") or {})
    metrics.update(_metrics_from_out(out_dir))
    res = {
        "ok": True, "jobId": job_id, "status": summary.get("status"),
        "steps": summary.get("steps"), "failed_step": summary.get("failed_step"),
        "metrics": metrics, "pipeline": summary.get("pipeline"),
        "deliverable_paths": paths, "result_dir": str(out_dir),
        "archive": str(archive) if archive else None,   # 保留的结果 zip,供用户下载
        "version_warning": warn,
    }
    # 失败时直接surface真错:summary.error(执行器已含日志尾)+ failed_logs 尾部,
    # 免得 agent 还得手动下日志找原因。
    if summary.get("status") == "failed":
        res["error"] = summary.get("error")
        if summary.get("missing_inputs"):
            res["missing_inputs"] = summary["missing_inputs"]
        logs = sorted((out_dir / "failed_logs").glob("*.log")) if (out_dir / "failed_logs").is_dir() else []
        if logs:
            tail = "\n".join(logs[-1].read_text(errors="replace").splitlines()[-15:]).strip()
            res["failed_log_tail"] = tail
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out", default=None, help="下载目录(默认 /bohr-workspace/td-result/<jobId>)")
    a = ap.parse_args()
    dl = a.out or f"/bohr-workspace/td-result/{a.job_id}"
    print(json.dumps(collect(a.job_id, dl), ensure_ascii=False))


if __name__ == "__main__":
    main()
