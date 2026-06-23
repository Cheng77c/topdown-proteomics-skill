#!/usr/bin/env bash
# Bohrium job 入口。job.json: command="bash run.sh --config pipeline.json"
# 包一层 bash 躲 WAF;全程相对路径(Bohrium 自动 cd 工作目录);
# export 的 env 经 os.environ.copy() 传到工具子进程(runner.py:436)。
set -euo pipefail
# 上传目录(-p 包)优先于镜像 /opt/topdown:薄 CLI 随包走可免重建镜像迭代;
# 生产时上传包无 td_*.py 则自动回落到镜像里的副本。
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE:/opt/topdown"
export WINEPREFIX=/root/.wine
export LD_LIBRARY_PATH=/opt/toppic-suite/lib/toppic
export OPENMS_DATA_PATH=/usr/share/OpenMS
export WINEDEBUG=-all
export TOOL_SERVICE_CONFIG=/etc/topdown/tool_service.toml
# 不写字节码:否则 job 在 /opt/topdown 落 __pycache__,被快照进镜像后,下次更新 .py 时旧 .pyc
# 源 mtime 相撞会被 Python 误用→跑成旧执行器(踩过)。不写 pyc 则镜像永远只认 .py。
export PYTHONDONTWRITEBYTECODE=1
# 钉死系统 python(3.12,自带 tomllib;不依赖 mamba 在 PATH 上——真 job 容器 PATH 可能不含)
exec /usr/bin/python3 -B -m td_cli "$@"
