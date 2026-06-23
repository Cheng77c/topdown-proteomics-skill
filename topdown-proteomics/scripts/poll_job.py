#!/usr/bin/env python3
"""轮询 Bohrium job 状态(OpenAPI,无需 TTY)。输出 JSON。

按 jobId 匹配(共享项目有他人并发 job,故 pageSize 取大些;别按 jobName)。
"""
import argparse
import json
import os
import sys
import urllib.request

STATUS = {0: "pending", 1: "running", 2: "completed", 3: "scheduling", -1: "failed"}


def decide(job_id: str, code) -> dict:
    status = STATUS.get(code, "unknown")
    done = status in ("completed", "failed")
    out = {
        "ok": True, "jobId": job_id, "status": status, "done": done,
        # 完成或失败都去 collect:失败时 collect 也 download 失败 summary + 失败日志,不断链
        "nextTool": "collect_results.py" if done else None,
    }
    if done:
        out["hint"] = "已终态:运行 collect_results.py 取结果。"
    else:
        # 不返回 pollAfterMs 之类"稍后再轮询"的信号——那会诱导 agent 自旋。
        out["hint"] = ("仍在运行:向用户报告 jobId + 状态后**结束本轮**,不要自旋轮询;"
                       "作业在后台独立运行,用户稍后回来或下次调用时再查一次。")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    a = ap.parse_args()
    ak = os.environ.get("ACCESS_KEY") or os.environ.get("BOHR_ACCESS_KEY")
    if not ak:
        sys.exit("missing env: ACCESS_KEY(也没 BOHR_ACCESS_KEY;先 source .bohr_env 或完成授权)")

    url = "https://openapi.dp.tech/openapi/v1/job/list?page=1&pageSize=50"
    req = urllib.request.Request(url, headers={"accessKey": ak})
    data = json.load(urllib.request.urlopen(req, timeout=20))

    code = None
    for j in data.get("data", {}).get("items", []):
        if str(j.get("id")) == str(a.job_id):
            code = j.get("status")
            break
    print(json.dumps(decide(a.job_id, code), ensure_ascii=False))


if __name__ == "__main__":
    main()
