import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill/topdown-proteomics/scripts"))
import poll_job as pj


def test_failed_points_to_collect():
    r = pj.decide("777", -1)
    assert r["status"] == "failed" and r["done"] is True
    assert r["nextTool"] == "collect_results.py"      # 失败也去取日志,不断链


def test_completed_points_to_collect():
    r = pj.decide("777", 2)
    assert r["status"] == "completed" and r["nextTool"] == "collect_results.py"


def test_running_stops_no_spin():
    # 运行中:不给下一步、不给 pollAfterMs(避免诱导自旋),hint 明确"结束本轮"
    r = pj.decide("777", 1)
    assert r["done"] is False and r["nextTool"] is None
    assert "pollAfterMs" not in r
    assert "结束本轮" in r["hint"] and "自旋" in r["hint"]
