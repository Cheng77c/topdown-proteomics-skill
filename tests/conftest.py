"""Conftest for bohrium-image tests.

Ensures the build/ closure directory takes precedence over the worktree root in
sys.path so the stub topdown_agent package (with empty runtime/__init__.py) is
loaded instead of the full one (which has circular imports not present in the
slim closure).

pytest.ini 的 pythonpath = . 把 worktree 根插在前面,需要在这里把 build/ 抢到第一位。
"""
import sys
from pathlib import Path

# build/ is a sibling of tests/ (both under deploy/bohrium-image/)
_BUILD = str(Path(__file__).parent.parent / "build")
if _BUILD not in sys.path:
    sys.path.insert(0, _BUILD)
# Also remove the worktree root topdown_agent from priority by ensuring build
# takes precedence — move build to index 0 if worktree root snuck in before it.
elif sys.path[0] != _BUILD:
    sys.path.remove(_BUILD)
    sys.path.insert(0, _BUILD)
