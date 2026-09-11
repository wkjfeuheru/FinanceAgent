"""A 股板块识别与各数据源的代码格式转换。

为什么需要这一层：

- 新浪源用 ``sh600519`` / ``sz000001`` / ``bj920799`` 形式；
- BaoStock 用 ``sh.600519`` / ``sz.000001``，且**完全不支持北交所**；
- 北交所现行代码统一为 ``920`` 前缀，``43``/``83``/``87`` 开头为已废止代码。

北交所的两个实现事实（本机实测，2026-09-11）：

1. BaoStock 对北交所是零支持，且失败方式是**静默空**：``bj.430047`` 报
   ``error_code=10004011 股票代码未识别sh、sz``，而 ``sh.830799``/``sz.830799``
   返回 ``error_code=0`` 却只有 **0 行**。因此本模块对北交所直接拒绝，
   绝不返回可能被静默清空的前缀。
2. 已废止代码**不做猜测映射**：免费数据源中不存在旧→新代码对照表
   （``stock_info_bj_name_code()`` 的 343 行全部是 ``920`` 前缀，东财 clist 同），
   而"取末三位"规则已被证伪——``830799``（诺思兰德）的现行代码是 ``920047``，
   而 ``920799`` 是另一家公司。猜测映射会把用户导到错误的股票上。
"""

from __future__ import annotations

from finance_agent.data.providers import UnsupportedProviderCapability

_SH_PREFIX = "6"
_BJ_CURRENT_PREFIX = "92"  # 920xxx
_BJ_LEGACY_PREFIXES = ("43", "83", "87")

_LEGACY_BJ_MESSAGE = (
    "北交所代码已废止：{code}。现行代码统一为 920 前缀，且本仓库不做猜测映射"
    "（末三位规则会把 830799 错指到 920799，而 830799 对应的现行代码是 920047）。"
    "请更新代码表后重试。"
)


def normalize_code(value: str) -> str:
    """去掉市场前缀与后缀，返回纯数字代码。

    兼容 ``600519`` / ``sh600519`` / ``sh.600519`` / ``600519.SH`` 四种写法。
    """
    text = str(value).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip(".")
            break
    if "." in text:
        text = text.split(".")[0]
    return text.strip()


def market_of(value: str) -> str:
    """返回 ``sh`` / ``sz`` / ``bj``；北交所含现行 920 与已废止的 43/83/87 前缀。"""
    code = normalize_code(value)
    if code.startswith(_BJ_LEGACY_PREFIXES) or code.startswith(_BJ_CURRENT_PREFIX):
        return "bj"
    return "sh" if code.startswith(_SH_PREFIX) else "sz"


def is_legacy_bj(value: str) -> bool:
    """判断是否为已废止的北交所代码前缀。"""
    return normalize_code(value).startswith(_BJ_LEGACY_PREFIXES)


def ensure_current_code(value: str) -> str:
    """拒绝已废止的北交所代码，返回规范化代码。

    北交所代码变更无法从免费数据源还原，因此宁可显式失败，也不猜测映射。
    """
    code = normalize_code(value)
    if is_legacy_bj(code):
        raise UnsupportedProviderCapability(_LEGACY_BJ_MESSAGE.format(code=code))
    return code


def sina_symbol(value: str) -> str:
    """构造新浪源符号，如 ``sh600519`` / ``bj920799``。"""
    return f"{market_of(value)}{normalize_code(value)}"


def baostock_symbol(value: str) -> str:
    """构造 BaoStock 符号，如 ``sh.600519``；北交所显式拒绝。"""
    code = normalize_code(value)
    market = market_of(code)
    if market == "bj":
        raise UnsupportedProviderCapability(
            f"BaoStock 不支持北交所：{code}（bj. 报 10004011，sh./sz. 会静默返回 0 行）"
        )
    return f"{market}.{code}"


__all__ = [
    "baostock_symbol",
    "ensure_current_code",
    "is_legacy_bj",
    "market_of",
    "normalize_code",
    "sina_symbol",
]
