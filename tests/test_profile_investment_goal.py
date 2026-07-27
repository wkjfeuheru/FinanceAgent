import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-placeholder")

from finance_agent.agents.profile_extraction import (
    SlotExtractionAgent,
    extract_investment_goal,
)
from finance_agent.core.memory import AgentMemoryContext, UserProfileCard


class InvestmentGoalExtractionTests(unittest.TestCase):
    def test_explicit_goal_stops_before_follow_up_condition(self):
        message = "我的投资目标是财富增值，如果这几只股票选一个，你最推荐哪个"
        self.assertEqual(extract_investment_goal(message), "财富增值")

    def test_known_goal_without_explicit_label(self):
        self.assertEqual(extract_investment_goal("我希望长期增值"), "长期增值")

    def test_screening_fast_path_keeps_investment_goal(self):
        agent = SlotExtractionAgent()
        profile = agent.extract_profile(
            "我的投资目标是财富增值，推荐一只AI行业股票",
            existing_profile={},
        )
        self.assertEqual(profile["investment_goal"], "财富增值")

    def test_stock_code_fast_path_keeps_investment_goal(self):
        agent = SlotExtractionAgent()
        profile = agent.extract_profile(
            "投资目标为稳健增值，分析一下600519",
            existing_profile={},
        )
        self.assertEqual(profile["investment_goal"], "稳健增值")


class InvestmentGoalPersistenceTests(unittest.TestCase):
    def test_result_profile_goal_is_saved_to_long_term_profile(self):
        memory = AgentMemoryContext(store=Mock(), checkpointer=None)
        profile = UserProfileCard(customer_id="CUST001")
        memory.get_profile = Mock(return_value=profile)
        memory.save_profile = Mock(return_value=True)

        saved = memory.update_profile_from_result(
            "CUST001",
            "我的投资目标是财富增值",
            {"user_profile": {"investment_goal": "财富增值"}},
        )

        self.assertTrue(saved)
        self.assertEqual(profile.investment_goal, "财富增值")
        memory.save_profile.assert_called_once_with(profile)


if __name__ == "__main__":
    unittest.main()
