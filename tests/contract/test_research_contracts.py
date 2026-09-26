"""确定性研究领域契约测试。"""

import pytest

from finance_agent.domains.research.contracts import (
    Action,
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
)


def test_request_deduplicates_codes_and_requires_kind_shape():
    """单股请求去重；比较请求至少包含两只股票。"""
    request = AnalysisRequest(
        kind=AnalysisKind.SINGLE_STOCK,
        stock_codes=["600519", "600519"],
    )

    assert request.stock_codes == ["600519"]
    with pytest.raises(ValueError):
        AnalysisRequest(
            kind=AnalysisKind.COMPARISON,
            stock_codes=["600519"],
        )


def test_watch_cannot_be_emitted_with_critical_data_missing():
    """关键数据缺失时不得输出关注结论。"""
    with pytest.raises(ValueError, match="关键数据"):
        AnalysisResult(
            action=Action.WATCH,
            data_quality="critical_missing",
        )
