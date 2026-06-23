#!/usr/bin/env bash
# 组装镜像的 /opt/topdown Python 包(TD 闭包,已实测:9 文件 + 空 runtime/__init__)。
# 双用途:① 本地测试(symlink,源码改动即时生效)② 镜像打包(--copy 实拷)。
# 用法: build-pkg.sh [--copy] [dest]   默认 symlink 到 ./build/
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/../.." && pwd)/topdown_agent"   # worktree 的 topdown_agent 源
MODE="link"; [ "${1:-}" = "--copy" ] && { MODE="copy"; shift; }
DEST="${1:-$HERE/build}"
PKG="$DEST/topdown_agent"

put() { if [ "$MODE" = copy ]; then cp "$1" "$2"; else ln -sf "$1" "$2"; fi; }

rm -rf "$DEST"; mkdir -p "$PKG/service" "$PKG/runtime"
put "$SRC/__init__.py" "$PKG/__init__.py"                       # 空
for f in __init__ models specs runner limits service; do
  put "$SRC/service/$f.py" "$PKG/service/$f.py"
done
put "$SRC/runtime/models.py" "$PKG/runtime/models.py"
: > "$PKG/runtime/__init__.py"                                  # ★ 置空(斩断循环 import + 闭合闭包)

# analysis 包:runner._run_analysis 惰性 import(产物 QC,进 metadata)。
# 自包含、纯 stdlib;import-smoke 测不到,e2e 才暴露,故整包烤入。
mkdir -p "$PKG/analysis"
for f in "$SRC"/analysis/*.py; do put "$f" "$PKG/analysis/$(basename "$f")"; done

# CLI 模块(top-level,镜像 /opt/topdown 下,与 topdown_agent/ 并列)
for f in td_pipeline.py td_cli.py td_derive.py run.sh pipeline.example.json \
         bu_dag.py bu_pipeline.py; do
  put "$HERE/pkg/$f" "$DEST/$f"
done

echo "组装完成($MODE) -> $DEST"
echo "  topdown_agent 保留集:$(find "$PKG" -name '*.py' | wc -l) 个 .py + CLI 模块"
