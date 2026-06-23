#!/usr/bin/env python3
"""把 sandbox 里的大输入(GB 级 .raw)创建为 Bohrium Dataset,返回挂载路径。

大文件走 dataset 挂载,不进 -p 上传包 / LLM 上下文。
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="sandbox 里的大文件路径")
    ap.add_argument("--name", required=True, help="数据集名(也作 -p 前缀)")
    a = ap.parse_args()
    project = os.environ.get("PROJECT_ID")
    if not project:
        sys.exit("missing env: PROJECT_ID")

    src = Path(a.file)
    if not src.exists():
        sys.exit(f"file not found: {src}")
    # fasta 绝不做成 dataset:dataset 是只读挂载,toppic/mspathfindert 要在 fasta 旁建
    # .fasta_idx 索引,只读会失败(LOG ERROR: ...fasta_idx could not be created)。
    # fasta 小,走本地路径随 -p 上传(可写)。dataset 只给大谱图(.raw/.mzML)。
    if src.suffix.lower() in (".fasta", ".fa", ".faa"):
        sys.exit("fasta 不要做成 dataset(只读挂载,搜索工具建索引会失败)。"
                 "fasta 直接在 pipeline.json 用本地路径(submit 自动拷进 -p 可写区);"
                 "dataset 只给大谱图 .raw/.mzML。")

    # bohr dataset create -n <name> ... -l <目录>(目录级上传,支持断点续传)
    # 直接调 bohr(ACCESS_KEY 经 env 继承——调用前须 source .bohr_env)
    # 喂 stdin:bohr 可能弹 "Detected cached files, resume? (y/n)",无 stdin 会 panic
    p = subprocess.run(
        ["bohr", "dataset", "create", "-n", a.name, "-p", a.name, "-i", project, "-l", str(src.parent)],
        input="y\n", capture_output=True, text=True,
    )
    raw = p.stdout + p.stderr

    # bohr CLI 上传失败/超时会 panic(非优雅报错);明确提示而非后面查不到时困惑
    if "Upload Failed" in raw or "panic:" in raw or p.returncode != 0:
        tail = raw[-400:]
        sys.exit("dataset 上传失败(网络慢/文件过大致 tiefblue 超时,bohr CLI 会 panic)。"
                 "Shrimp 内网通常正常;或重试(支持断点续传)。原始: " + tail)

    # ★ 关键:Bohrium 给数据集名加随机后缀(如 -hvx3),真实挂载路径必须从 API 查;
    #   不能假设 /bohr/<name>/v1,否则 job 报 "Dataset ... has been deleted"。
    ak = os.environ.get("ACCESS_KEY") or os.environ.get("BOHR_ACCESS_KEY", "")
    url = f"https://openapi.dp.tech/openapi/v1/ds/?projectId={project}&page=1&pageSize=50"
    req = urllib.request.Request(url, headers={"accessKey": ak})
    items = json.load(urllib.request.urlopen(req, timeout=20)).get("data", {}).get("items", [])
    match = next((i for i in items if i.get("title") == a.name), None)
    if not match:
        sys.exit(f"dataset '{a.name}' 创建后未在列表中找到(create 输出: {raw[-200:]})")
    mount = match["path"]          # /bohr/<name>-<随机>/v1
    # ★ bohr dataset create -l <dir> 会把 <dir> 的 basename 作为一层嵌进挂载路径
    #   (实测: -l /x/upload → 文件在 v1/upload/file,不在 v1/file)。故返回路径必须带这层。
    spectrum_mount = f"{mount}/{src.parent.name}/{src.name}"
    print(json.dumps({
        "ok": True, "dataset": a.name, "dataset_id": match.get("id"), "mount": mount,
        "spectrum_mount": spectrum_mount,
        "hint": "pipeline.json 的 inputs.spectrum 填 %s;submit 带 --dataset-path %s" % (spectrum_mount, mount),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
