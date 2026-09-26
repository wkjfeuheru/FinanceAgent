"""主题/板块筛选的公开契约。

这里曾经钉的是"主题筛选能力下线后的固定拒绝文案"：用正则判定"推荐/筛选 + 主题/板块"
就在**模型调用之前**返回固定文案。现在筛选改成了真实取数 + 确定性评分排序（板块成分
来自东财，排序复用 ``evaluation.evaluate`` 的评分与行动结论），因此契约变为：

1. 研究契约里**没有** ``theme_screening`` 种类与 ``theme_id``——不恢复被删的
   主题注册表体系（themes/theme_memberships + 管理端审核 + 外部分类服务）；
2. 管理端**没有** theme 路由；
3. 题材筛选请求**能到模型层**（不再被前置固定文案短路），工具白名单里是
   ``list_boards`` / ``screen_board_candidates``，不是 ``screen_theme``；
4. 匹配不到板块时给的是引导文案（``NO_MATCH_HINT``），而不是"当前不支持…"。
"""

from pathlib import Path

from finance_agent.api.app import app
from finance_agent.api.schemas.chat import ChatResponse
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.research.expert import stock_tools
from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from tests.conftest import final_message, make_fake_tool_model


#: 旧的固定拒绝文案：重建能力后不得再出现。
RETIRED_UNSUPPORTED_MESSAGE = "当前不支持按主题或板块自动筛选股票，请提供具体股票名称或代码进行分析。"


def _run_stock_request(text: str, model):
    expert = build_expert(BusinessDomain.STOCK_RESEARCH, model=model)
    context = DomainTaskContext(
        task=PlanTask(
            task_id="screening-request",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=text,
            instruction=text,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=text,
    )
    return expert.invoke({"context": context})["domain_outcome"]


def test_research_contract_has_no_theme_screening_kind_or_theme_id():
    assert "theme_screening" not in {kind.value for kind in AnalysisKind}
    assert "theme_id" not in AnalysisRequest.model_fields


def test_chat_response_has_no_theme_capability_fields():
    response_fields = set(ChatResponse.model_fields)
    assert response_fields.isdisjoint({
        "theme_screening", "theme_screening_status", "theme_candidates", "pending_leads",
    })


def test_theme_admin_routes_are_absent():
    paths = set(app.openapi()["paths"])
    assert not any("/themes" in path or "theme-leads" in path for path in paths)


def test_board_tools_replaced_screen_theme_in_the_whitelist():
    names = {tool.name for tool in stock_tools()}
    assert {"list_boards", "screen_board_candidates"} <= names
    assert "screen_theme" not in names


def test_theme_requests_reach_the_model_instead_of_a_fixed_refusal():
    """题材筛选请求必须真正执行到模型层（而不是被前置文案拦下）。"""
    for text in ("推荐人工智能主题股票", "筛选半导体板块龙头", "推荐几只新能源股", "找一些半导体股票"):
        outcome = _run_stock_request(text, make_fake_tool_model([final_message("该板块的候选清单如下。")]))

        assert outcome.summary != RETIRED_UNSUPPORTED_MESSAGE, f"{text} 仍被前置固定文案拦截"
        assert outcome.summary == "该板块的候选清单如下。"
        assert outcome.status in {"success", "partial"}


def test_pre_model_screening_guard_is_retired():
    """模型调用前的正则守卫与其固定文案必须已被删除（能力改由工具层提供）。"""
    import finance_agent.domains.research.expert as expert
    import finance_agent.orchestration.experts.base as expert_base

    assert not hasattr(expert, "is_unsupported_stock_screening_request")
    assert not hasattr(expert, "UNSUPPORTED_SCREENING_MESSAGE")
    source = Path(expert_base.__file__).read_text(encoding="utf-8")
    assert "is_unsupported_stock_screening_request" not in source
    assert "stock_screening_unsupported" not in source


def test_no_match_guidance_replaces_the_retired_message():
    from finance_agent.domains.research.expert import screening

    assert RETIRED_UNSUPPORTED_MESSAGE not in screening.NO_MATCH_HINT
    assert "未匹配到" in screening.NO_MATCH_HINT
    # 清单必须带免责与预筛口径，回答里要原样转述。
    assert "不构成" in screening.SCREEN_DISCLAIMER
    assert "成交额" in screening.PRESCREEN_NOTE


def test_source_outage_guidance_never_blames_the_keyword():
    """数据源故障的文案必须与"没匹配到"严格区分，否则会引导用户白改关键词。"""
    from finance_agent.domains.research.expert import screening

    hint = screening.BOARD_UNAVAILABLE_HINT

    assert hint != screening.NO_MATCH_HINT
    assert "未匹配" not in hint
    assert RETIRED_UNSUPPORTED_MESSAGE not in hint
    assert "数据源" in hint and "暂不可用" in hint


def test_stock_prompt_pins_board_screening_discipline():
    """提示词必须写明：只能引用工具产出、要说预筛口径、要带免责、不得有倾向词。"""
    from finance_agent.domains.research.expert import STOCK_SYSTEM_PROMPT as prompt

    for anchor in (
        "list_boards",
        "screen_board_candidates",
        "不要凭记忆列股票",
        "预筛口径",
        "disclaimer",
        "最值得关注",
        # 两种失败必须分开处理：数据源故障不得说成"没匹配到"。
        "unavailable",
        "数据源暂不可用",
    ):
        assert anchor in prompt, f"提示词缺少板块筛选纪律锚点：{anchor}"


def test_explicit_stock_analysis_is_not_treated_as_sector_screening():
    for text in ("分析贵州茅台", "分析600519"):
        outcome = _run_stock_request(text, make_fake_tool_model([
            final_message("个股分析正常。"),
        ]))
        assert outcome.summary != RETIRED_UNSUPPORTED_MESSAGE
