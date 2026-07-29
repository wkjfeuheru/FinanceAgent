"""Test AgentProtocol, ProceduralAgent, and ReActAgent base classes."""

import pytest

from finance_agent.agents.base import AgentProtocol, ProceduralAgent, ReActAgent


# ── AgentProtocol ──────────────────────────────────────────────────

class TestAgentProtocol:
    """AgentProtocol is an abstract base — cannot instantiate directly."""

    def test_cannot_instantiate_directly(self):
        """Invoke not implemented → must raise NotImplementedError."""
        with pytest.raises(NotImplementedError):

            class _Broken(AgentProtocol):
                pass  # no invoke override

            _Broken().invoke({})

    def test_concrete_subclass_works(self):
        """A subclass implementing invoke is valid."""

        class _Valid(AgentProtocol):
            agent_name = "valid"

            def invoke(self, state):
                state["called"] = True
                return state

        agent = _Valid()
        result = agent.invoke({"user_message": "hi"})
        assert result["called"] is True


# ── ProceduralAgent ────────────────────────────────────────────────

class TestProceduralAgent:
    """ProceduralAgent is a simple pipeline agent (no LLM loop)."""

    def test_agent_name_is_set(self):
        agent = ProceduralAgent()
        assert agent.agent_name == "procedural"

    def test_shared_memory_defaults_to_none(self):
        agent = ProceduralAgent()
        assert agent.shared_memory is None

    def test_shared_memory_accepts_custom(self):
        sentinel = object()
        agent = ProceduralAgent(shared_memory=sentinel)
        assert agent.shared_memory is sentinel

    def test_invoke_passthrough(self):
        agent = ProceduralAgent()
        state = {"user_message": "hello", "thread_id": "t1"}
        result = agent.invoke(state)
        assert result is state
        assert result["user_message"] == "hello"

    def test_build_effective_message_no_memory(self):
        agent = ProceduralAgent()
        msg = agent._build_effective_message("分析 600519")
        assert "用户问题：分析 600519" in msg

    def test_build_effective_message_with_customer_id(self):
        agent = ProceduralAgent()
        msg = agent._build_effective_message("查余额", customer_id="C123")
        assert "当前客户号：C123" in msg
        assert "用户问题：查余额" in msg

    def test_build_effective_message_with_memory_context(self):
        agent = ProceduralAgent()
        msg = agent._build_effective_message(
            "继续", memory_context="上次你提到了持仓分析"
        )
        assert "上次你提到了持仓分析" in msg
        assert "用户问题：继续" in msg

    def test_build_effective_message_with_shared_memory_facts(self):
        """shared_memory.facts are injected but the source is hidden."""

        class _FakeMemory:
            def __init__(self):
                self.facts = {"balance": "100000"}

            def format_facts_for_prompt(self):
                return "余额：100000元"

        agent = ProceduralAgent(shared_memory=_FakeMemory())
        msg = agent._build_effective_message("分析持仓")
        assert "[共享上下文]" in msg
        assert "余额：100000元" in msg
        assert "用户问题：分析持仓" in msg
        # Must NOT mention the source
        assert "来自" not in msg.split("[共享上下文]", 1)[1].split("用户问题", 1)[0]


# ── ReActAgent config defaults ─────────────────────────────────────

class TestReActAgentDefaults:
    """ReActAgent has conservative safety defaults."""

    def test_max_reasoning_steps_default(self):
        agent = ReActAgent()
        assert agent.max_reasoning_steps == 10

    def test_max_tool_calls_per_step_default(self):
        agent = ReActAgent()
        assert agent.max_tool_calls_per_step == 2

    def test_per_invoke_timeout_default(self):
        agent = ReActAgent()
        assert agent.per_invoke_timeout == 90.0

    def test_tool_call_same_param_limit_default(self):
        agent = ReActAgent()
        assert agent.tool_call_same_param_limit == 3

    def test_tool_call_history_window_default(self):
        agent = ReActAgent()
        assert agent.tool_call_history_window == 6


# ── ReActAgent fallback ───────────────────────────────────────────

class TestReActAgentFallback:
    """_fallback replaces state in a safe, observable way."""

    def test_fallback_sets_agent_response(self):
        agent = ReActAgent()
        state = {"user_message": "hello"}
        result = agent._fallback(state, "网络超时")
        assert result is state
        assert "网络超时" in state["agent_response"]

    def test_fallback_reason_in_response(self):
        agent = ReActAgent()
        state = {}
        result = agent._fallback(state, "模型不可用")
        assert result["agent_response"] == "分析暂时不可用：模型不可用"


# ── _check_tool_call_health ────────────────────────────────────────

class TestToolCallHealth:
    """Unit tests for ReActAgent._check_tool_call_health."""

    def _make_call(self, name, **args):
        return {"name": name, "args": args}

    def test_empty_history_returns_none(self):
        agent = ReActAgent()
        result = agent._check_tool_call_health(
            [self._make_call("search", q="茅台")], []
        )
        assert result is None

    def test_normal_different_calls_returns_none(self):
        agent = ReActAgent()
        history = [
            self._make_call("search", q="茅台"),
            self._make_call("search", q="格力"),
            self._make_call("fetch_price", code="600519"),
        ]
        result = agent._check_tool_call_health(
            [self._make_call("search", q="五粮液")], history
        )
        assert result is None

    def test_same_param_detected_in_window(self):
        """3 calls with identical (name, args) in 6-window triggers error."""
        agent = ReActAgent()
        history = [
            self._make_call("fetch_price", code="600519"),
            self._make_call("fetch_price", code="000858"),
            self._make_call("fetch_price", code="600519"),  # 1
            self._make_call("fetch_price", code="000001"),
            self._make_call("fetch_price", code="600519"),  # 2
            self._make_call("other", x="1"),
        ]
        # The current call would be the 3rd identical one in the window
        result = agent._check_tool_call_health(
            [self._make_call("fetch_price", code="600519")], history
        )
        assert result is not None
        assert "重复调用" in result
        assert "fetch_price" in result

    def test_same_param_below_limit_returns_none(self):
        """Only 2 identical calls → not flagged."""
        agent = ReActAgent()
        history = [
            self._make_call("fetch_price", code="600519"),  # 1
            self._make_call("fetch_price", code="000858"),
            self._make_call("fetch_price", code="000001"),
        ]
        # Current call would make it the 2nd in window
        result = agent._check_tool_call_health(
            [self._make_call("fetch_price", code="600519")], history
        )
        assert result is None

    def test_alternating_loop_detected(self):
        """A→B→A→B alternating pattern triggers error."""
        agent = ReActAgent()
        history = [
            self._make_call("search", q="茅台"),
            self._make_call("fetch", code="600519"),
            self._make_call("search", q="茅台"),
            self._make_call("fetch", code="600519"),
        ]
        result = agent._check_tool_call_health(
            [self._make_call("search", q="茅台")], history
        )
        assert result is not None
        assert "交替循环" in result

    def test_no_progress_three_consecutive_identical(self):
        """3 consecutive identical calls → no progress."""
        agent = ReActAgent()
        history = [
            self._make_call("search", q="茅台"),
            self._make_call("search", q="茅台"),
            self._make_call("search", q="茅台"),
        ]
        result = agent._check_tool_call_health(
            [self._make_call("search", q="茅台")], history
        )
        assert result is not None
        assert "无进展" in result

    def test_no_progress_only_two_consecutive_returns_none(self):
        """2 consecutive identical calls → not yet no-progress."""
        agent = ReActAgent()
        history = [
            self._make_call("search", q="茅台"),
            self._make_call("other", x="1"),
            self._make_call("search", q="茅台"),
        ]
        result = agent._check_tool_call_health(
            [self._make_call("search", q="茅台")], history
        )
        assert result is None

    def test_same_param_count_resets_with_different_call(self):
        """Check that the same-param counter is scoped to the window."""
        agent = ReActAgent()
        # Make window size = 6
        agent.tool_call_history_window = 6
        history = [
            self._make_call("fetch_price", code="600519"),  # identical #1
            self._make_call("a", x="1"),
            self._make_call("b", x="2"),
            self._make_call("c", x="3"),
            self._make_call("d", x="4"),
            self._make_call("fetch_price", code="600519"),  # identical #2
        ]
        # Current call is also identical, but history count is only 2
        # (the check counts history, not current call). 2 < limit 3.
        result = agent._check_tool_call_health(
            [self._make_call("fetch_price", code="600519")], history
        )
        assert result is None
