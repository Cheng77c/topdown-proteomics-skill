#!/usr/bin/env python3
"""装配 -p 上传包(pipeline.json + 本地输入)并提交 Bohrium job。

用法:agent 先按 schema 写好 pipeline.json(inputs + steps),再:
    python3 submit_pipeline.py --pipeline pipeline.json [--dataset-path /bohr/<ds>/v1]
本脚本会:把 inputs 里的本地文件拷进上传包(/bohr 挂载路径保留)、写 job.json、bohr 提交。
执行器(td_pipeline/td_cli/td_derive/run.sh)已烤在镜像 /opt/topdown,不随包上传。

env(由 openclaw 注入,先 source /bohr-workspace/.bohr_env):
  ACCESS_KEY、PROJECT_ID(默认 27108)、IMAGE_ADDRESS(默认本项目镜像)、MACHINE_TYPE
输出: JSON {ok, jobId, status, pollAfterMs, nextTool}
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import validate_pipeline

# 镜像地址单一源:skill 根的 image.txt(版本迭代只改这一处)。env IMAGE_ADDRESS 可覆盖。
_IMAGE_FILE = Path(__file__).resolve().parent.parent / "image.txt"
DEFAULT_IMAGE = _IMAGE_FILE.read_text().strip() if _IMAGE_FILE.exists() else ""
# PROJECT_ID 无默认:项目相关,必须由 env/configField 注入(同 ACCESS_KEY),否则误投错项目。


def _submit(workdir: str) -> str:
    # bohr 直接跑(不用 script 包装;ACCESS_KEY 经 env 继承——调用前须 source .bohr_env)
    p = subprocess.run(["bohr", "job", "submit", "-i", "job.json", "-p", "./"],
                       cwd=workdir, capture_output=True, text=True)
    out = p.stdout + p.stderr
    m = re.search(r"JobId:\s*(\d+)", out)
    if not m:
        sys.exit("submit 失败:\n" + out[-800:])
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", required=True, help="agent 写好的 pipeline.json(inputs+steps)")
    ap.add_argument("--dataset-path", action="append", default=[], help="/bohr/<ds>/v1,可多次")
    ap.add_argument("--job-name", default="topdown")
    ap.add_argument("--workdir", default=None,
                    help="打包目录(默认=pipeline.json 所在目录;每任务用独立子目录如 "
                         "td-runs/<名>/,勿直接放 /bohr-workspace 根)")
    a = ap.parse_args()

    pipeline = json.loads(Path(a.pipeline).read_text())

    # 先本地校验 pipeline(错则停,不浪费 job;错误带 step/tool/field/fix 供 agent 自纠),
    # 再查提交所需 env(PROJECT_ID 无默认,须注入)。
    vres = validate_pipeline.validate_with_fs(pipeline)
    if not vres["ok"]:
        print(json.dumps({"ok": False, "stage": "validate", "errors": vres["errors"]},
                         ensure_ascii=False))
        return 1

    project = os.environ.get("PROJECT_ID")
    if not project:
        sys.exit("missing env: PROJECT_ID(须经 .bohr_env/configField 注入,无默认值)")
    image = os.environ.get("IMAGE_ADDRESS", DEFAULT_IMAGE)
    machine = os.environ.get("MACHINE_TYPE", "c16_m32_cpu")

    # 就地打包:默认用 pipeline.json 所在目录(per-task 自包含、并发安全、不散落根目录)。
    # 不 rmtree(会删掉 pipeline.json 自己);约定每任务一个独立子目录,重提则覆盖同名打包物。
    wd = Path(a.workdir).resolve() if a.workdir else Path(a.pipeline).resolve().parent
    if wd == Path("/bohr-workspace"):
        sys.exit("pipeline.json 须放进专属子目录(如 /bohr-workspace/td-runs/<任务名>/pipeline.json),"
                 "勿直接放 /bohr-workspace 根——否则打包会把整个工作空间上传。")
    wd.mkdir(parents=True, exist_ok=True)

    # 本地输入拷进上传包并改为包内相对名;/bohr 挂载路径保留
    inputs = pipeline.get("inputs") or {}
    for k, v in list(inputs.items()):
        if v and not str(v).startswith("/bohr/"):
            src = Path(v).resolve()
            dst = wd / src.name
            if src != dst.resolve():   # 就地打包时输入可能已在 wd,避免 copy 自己到自己
                shutil.copy(src, dst)
            inputs[k] = src.name
    pipeline["inputs"] = inputs
    (wd / "pipeline.json").write_text(json.dumps(pipeline, ensure_ascii=False, indent=2))

    job = {
        "job_name": a.job_name,
        # 执行器在镜像 /opt/topdown;run.sh 已设 PYTHONDONTWRITEBYTECODE+ -B,不积陈旧 .pyc。
        "command": "bash /opt/topdown/run.sh --config pipeline.json",
        "log_file": "out/run.log",
        "backward_files": ["out/"],
        "project_id": int(project),
        "machine_type": machine,
        "job_type": "container",
        "disk_size": 100,
        "max_run_time": 120,
        "image_address": image,
    }
    if a.dataset_path:
        job["dataset_path"] = a.dataset_path
    (wd / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2))

    jid = _submit(str(wd))
    # per-task 自包含:wd 即任务目录(含 pipeline.json + 输入 + 待 collect 回收的 result/),不清理。
    print(json.dumps({
        "ok": True, "jobId": jid, "status": "scheduling",
        "pollAfterMs": 20000, "nextTool": "poll_job.py",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
