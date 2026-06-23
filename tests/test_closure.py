"""运行时闭包测试:精简包必须含 runner 惰性 import 的 analysis 包(e2e 暴露过)。"""


def test_analysis_package_importable_in_slim_build():
    # runner._run_analysis 用到的名字必须能从精简包导入,否则工具被误报 failed
    from topdown_agent.analysis import (
        AnalysisResult,
        analyze_msalign_quality,
        analyze_mzml_quality,
        analyze_topfd_feature_quality,
        analyze_toppic_results,
        analyze_toppic_proteoforms,
    )
    assert AnalysisResult is not None
