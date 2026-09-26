"""板块识别与代码格式转换的回归测试。

这两个失败模式都曾真实存在于仓库中：BaoStock 对北交所静默返回 0 行，
以及"取末三位"会把已废止代码指到另一家公司。
"""

from __future__ import annotations

import pytest

from finance_agent.infrastructure.market_data.board_codes import (
    baostock_symbol,
    ensure_current_code,
    is_legacy_bj,
    market_of,
    normalize_code,
    sina_symbol,
)
from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource
from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability


def test_normalize_code_accepts_every_vendor_writing_style():
    for value in ("600519", "sh600519", "sh.600519", "600519.SH", "SH.600519"):
        assert normalize_code(value) == "600519"
    assert normalize_code("bj920799") == "920799"
    assert normalize_code("000001.SZ") == "000001"


def test_market_of_covers_all_boards_including_beijing():
    assert market_of("600519") == "sh"
    assert market_of("688981") == "sh"
    assert market_of("000001") == "sz"
    assert market_of("300750") == "sz"
    assert market_of("920799") == "bj"
    assert market_of("830799") == "bj"
    assert market_of("430047") == "bj"


def test_symbols_are_built_per_vendor():
    assert sina_symbol("600519") == "sh600519"
    assert sina_symbol("000001") == "sz000001"
    assert sina_symbol("920799") == "bj920799"
    assert baostock_symbol("600519") == "sh.600519"
    assert baostock_symbol("688981") == "sh.688981"
    assert baostock_symbol("300750") == "sz.300750"
    assert baostock_symbol("600519.SH") == "sh.600519"


def test_baostock_rejects_beijing_instead_of_returning_empty_rows():
    """BaoStock 对北交所零支持：必须显式报错。

    实测 ``sh.830799``/``sz.830799`` 返回 ``error_code=0`` 但 0 行——空结果会被
    ``ProviderManager._call`` 当作"返回空数据"继续降级，最终表现为"这只票没数据"，
    根因却藏在代码映射里。
    """
    with pytest.raises(UnsupportedProviderCapability):
        baostock_symbol("920799")
    with pytest.raises(UnsupportedProviderCapability):
        baostock_symbol("830799")


def test_baostock_daily_fails_before_touching_the_network():
    """符号校验必须先于登录，避免为一只注定失败的票打一次网络往返。"""
    provider = BaostockDataSource()  # 不登录，仅构造

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily("920799", adjustment="forward")


def test_legacy_beijing_codes_are_rejected_rather_than_guessed():
    """末三位规则已被证伪：830799 是诺思兰德，其现行代码是 920047。

    而 920799 是另一家公司——猜测映射会把用户导到错误的股票上，比报错危险得多。
    """
    assert is_legacy_bj("830799")
    assert is_legacy_bj("430047")
    assert not is_legacy_bj("920047")

    with pytest.raises(UnsupportedProviderCapability) as excinfo:
        ensure_current_code("830799")
    message = str(excinfo.value)
    assert "830799" in message and "920" in message

    # 现行代码与沪深代码照常通过。
    assert ensure_current_code("920047") == "920047"
    assert ensure_current_code("600519") == "600519"
