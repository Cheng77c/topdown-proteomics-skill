#!/usr/bin/env python3
"""提交前本地校验 pipeline.json,返回可定位可纠错的错误。纯 stdlib。

⚠️ 规则与 references/parameters.md 同源。镜像 service/specs.py 改校验时,必须同步本文件的
   检查规则与 parameters.md 的「ParamError 约束」节(见 tests/test_validate_pipeline 漂移测试)。

用法: python3 validate_pipeline.py --pipeline pipeline.json
输出: {"ok": bool, "errors": [{step, tool, field, problem, allowed?, fix}]}
退出码: 0 通过 / 1 有错。
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

TOOLS = ("msconvert", "topfd", "flashdeconv", "toppic", "pbfgen", "promex", "mspathfindert")
_ACT = ("FILE", "CID", "ETD", "HCD", "UVPD")
_NTERM = ("NONE", "NME", "NME_ACETYLATION", "M_ACETYLATION")
_CUTOFF = ("EVALUE", "FDR")
DECONV = ("topfd", "flashdeconv")


def _err(step, tool, field, problem, allowed=None, fix=""):
    e = {"step": step, "tool": tool, "field": field, "problem": problem, "fix": fix}
    if allowed is not None:
        e["allowed"] = allowed
    return e


def _check_toppic(i, tool, p, errors):
    mt = p.get("mass_error_tolerance")
    if mt is not None and mt not in (5, 10, 15):
        errors.append(_err(i, tool, "mass_error_tolerance", f"{mt} 不被接受",
                           allowed=[5, 10, 15], fix="改成 5/10/15 之一(默认 10)"))
    ns = p.get("num_shift")
    if ns is not None and ns not in (0, 1, 2):
        errors.append(_err(i, tool, "num_shift", f"{ns} 超出范围",
                           allowed=[0, 1, 2], fix="改成 0/1/2"))
    act = p.get("activation")
    if act is not None and act not in _ACT:
        errors.append(_err(i, tool, "activation", f"{act} 非法",
                           allowed=list(_ACT), fix="用枚举值之一(默认 FILE)"))
    for f in ("spectrum_cutoff_type", "proteoform_cutoff_type"):
        ct = p.get(f)
        if ct is not None and ct not in _CUTOFF:
            errors.append(_err(i, tool, f, f"{ct} 非法",
                               allowed=list(_CUTOFF), fix="EVALUE 或 FDR"))
    uses_fdr = p.get("spectrum_cutoff_type") == "FDR" or p.get("proteoform_cutoff_type") == "FDR"
    if uses_fdr and not p.get("decoy"):
        errors.append(_err(i, tool, "decoy", "用 FDR cutoff 但未开 decoy",
                           fix="设 decoy=true(FDR 估计需要 decoy 库)"))
    if p.get("no_topfd_feature") and (p.get("num_shift") or 0) >= 1:
        errors.append(_err(i, tool, "no_topfd_feature",
                           "no_topfd_feature=true 且 num_shift>=1 是已知崩溃组合",
                           fix="去掉 no_topfd_feature,或把 num_shift 设为 0"))
    ntf = p.get("n_terminal_form")
    if ntf:
        bad = [x for x in str(ntf).split(",") if x and x not in _NTERM]
        if bad:
            errors.append(_err(i, tool, "n_terminal_form", f"非法项 {bad}",
                               allowed=list(_NTERM), fix="逗号分隔的枚举值"))


def _check_topfd(i, tool, p, errors):
    act = p.get("activation")
    if act is not None and act not in ("FILE", "CID", "ETD", "HCD", "MPD", "UVPD"):
        errors.append(_err(i, tool, "activation", f"{act} 非法",
                           allowed=["FILE", "CID", "ETD", "HCD", "MPD", "UVPD"], fix="用枚举值"))
    msn = p.get("min_scan_number")
    if msn is not None and msn not in (1, 2, 3):
        errors.append(_err(i, tool, "min_scan_number", f"{msn} 超出范围",
                           allowed=[1, 2, 3], fix="改成 1/2/3"))
    for f in ("env_cnn_cutoff", "ecscore_cutoff"):
        v = p.get(f)
        if v is not None and not (0.0 <= float(v) <= 1.0):
            errors.append(_err(i, tool, f, f"{v} 不在 [0,1]",
                               allowed="[0,1]", fix="改成 0~1"))


def _check_mspathfindert(i, tool, p, errors):
    tda = p.get("tda")
    if tda is not None and isinstance(tda, bool):
        errors.append(_err(i, tool, "tda", "tda 必须是整数(0/1),不是 bool",
                           allowed=[0, 1], fix='写 "tda": 1 不是 true'))


_PARAM_CHECKS = {"toppic": _check_toppic, "topfd": _check_topfd,
                 "mspathfindert": _check_mspathfindert}


def _check_inputs(cfg, errors):
    inputs = cfg.get("inputs") or {}
    steps = cfg.get("steps") or []
    tools = [s.get("tool") for s in steps]
    if not inputs.get("spectrum"):
        errors.append(_err("inputs", None, "spectrum", "缺起点主输入",
                           fix="inputs.spectrum 填 .raw/.mzML/.msalign/.pbf 之一"))
    if any(t in ("toppic", "mspathfindert") for t in tools) and not inputs.get("fasta"):
        errors.append(_err("inputs", None, "fasta", "搜索步需要数据库",
                           fix="inputs.fasta 填蛋白库路径"))
    # fasta 不能放只读 dataset:toppic/mspathfindert 要在 fasta 旁建索引(.fasta_idx),
    # 只读 /bohr 挂载会失败(exit 1)。fasta 小,走本地路径随 -p 上传(可写)。
    fa = inputs.get("fasta")
    if fa and str(fa).startswith("/bohr/") and any(t in ("toppic", "mspathfindert") for t in tools):
        errors.append(_err("inputs", None, "fasta",
                           "fasta 在只读 dataset 上,搜索工具建索引会失败",
                           fix="fasta 改用本地路径(随 -p 上传,可写);大谱图才放 dataset"))
    # toppic 作为第一步、上游无反卷积、又没关 feature → 必须外部给 feature
    for i, s in enumerate(steps):
        if s.get("tool") == "toppic":
            upstream_deconv = any(t in DECONV for t in tools[:i])
            no_feat = (s.get("params") or {}).get("no_topfd_feature")
            if not upstream_deconv and not no_feat and not inputs.get("feature"):
                errors.append(_err(i, "toppic", "feature",
                                   "从 msalign 起步且无上游反卷积,缺 feature",
                                   fix="加 inputs.feature,或设 no_topfd_feature=true"))
            break


def validate(cfg: dict) -> dict:
    """纯逻辑校验(不碰文件系统),返回 {ok, errors}。一次返回全部错误。"""
    errors: list[dict] = []
    steps = cfg.get("steps") or []
    if not steps:
        errors.append(_err("steps", None, "steps", "steps 为空", fix="至少放一个工具"))
    for i, s in enumerate(steps):
        tool = s.get("tool")
        if tool not in TOOLS:
            errors.append(_err(i, tool, "tool", f"未知工具 {tool!r}",
                               allowed=list(TOOLS), fix="用合法工具名"))
            continue
        check = _PARAM_CHECKS.get(tool)
        if check:
            check(i, tool, dict(s.get("params") or {}), errors)
    _check_inputs(cfg, errors)
    return {"ok": not errors, "errors": errors}


# 本地输入(走 -p 上传)体积上限:超过必须改走 make_dataset 挂载,不得 -p。
# 与 SKILL 阈值一致;硬拦在提交前,杜绝"判断该建 dataset 却仍 -p"的知行不一。
MAX_LOCAL_INPUT_MB = 100


def validate_with_fs(cfg: dict) -> dict:
    """validate + 本地输入存在性 + 体积上限(/bohr 挂载路径跳过)。"""
    res = validate(cfg)
    errors = res["errors"]
    for k, v in (cfg.get("inputs") or {}).items():
        if not v or str(v).startswith("/bohr/"):
            continue
        p = Path(v)
        if not p.exists():
            errors.append(_err("inputs", None, k, f"本地文件不存在: {v}",
                               fix="确认路径,或用 /bohr 挂载/dataset"))
            continue
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > MAX_LOCAL_INPUT_MB:
            errors.append(_err("inputs", None, k,
                               f"{p.name} {size_mb:.0f}MB 超过 {MAX_LOCAL_INPUT_MB}MB,不能走 -p 上传",
                               fix=f"先 make_dataset.py --file {v} 注册成 dataset,"
                                   f"inputs.{k} 改用返回的 /bohr/<ds>/v1/... 挂载路径,submit 带 --dataset-path"))
    return {"ok": not errors, "errors": errors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="validate_pipeline")
    ap.add_argument("--pipeline", required=True)
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.pipeline).read_text())
    res = validate_with_fs(cfg)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
