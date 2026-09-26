"""编排层共享的 reducer 与状态读取工具模块。

供根图在 LangGraph ``Send`` 并发扇出时合并同名状态键：
- 映射类（分片结果、股票数据等）按 key 合并（``merge_dict``）；
- 单键承载的每轮派生状态用顶层浅覆盖（``replace_keys``）；
- 列表类（事实、分析结果、告警等）拼接并按身份去重（``dedupe_concat``）。
其余键保持 LangGraph 默认的 last-write-wins。

同时提供 ``run_of`` / ``routing_of`` / ``task_results_of`` 三个读取器：根图状态
把"轮次输入"与"每轮派生状态"分开存放，读取口径必须只有一份实现。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _identity(value: Any) -> str:
    """返回去重身份：优先业务 ID，其次稳定 JSON 序列化。"""
    for attr in ("fact_id", "task_id"):
        identifier = getattr(value, attr, None)
        if identifier:
            return str(identifier)
    if isinstance(value, dict):
        for key in ("fact_id", "task_id", "stock_code", "code"):
            if value.get(key):
                return str(value[key])
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def merge_dict(left: Dict[str, Any] | None, right: Dict[str, Any] | None) -> Dict[str, Any]:
    """并发分支写入的映射按 key 合并；同 key 的嵌套 dict 再浅合并。"""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            nested = dict(current)
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def replace_keys(left: Dict[str, Any] | None, right: Dict[str, Any] | None) -> Dict[str, Any]:
    """顶层浅覆盖：与 ``dict.update`` 同语义，**不**递归合并嵌套值。

    与 ``merge_dict`` 的区别是必需的而非风格偏好：每轮派生状态里存在"显式清空"
    的语义（例如追问拿到答案后把 ``param_missing`` 置回 ``{}``）。用 ``merge_dict``
    时 ``{}`` 会被当成"无更新"，旧表单会残留下来，导致拿到答案后仍被判定为缺参。
    """
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def dedupe_concat(left: List[Any] | None, right: List[Any] | None) -> List[Any]:
    """并发分支写入的列表拼接并按身份去重（保持首次出现顺序）。"""
    merged = list(left or [])
    seen = {_identity(item) for item in merged}
    for item in right or []:
        identifier = _identity(item)
        if identifier in seen:
            continue
        seen.add(identifier)
        merged.append(item)
    return merged


# ── 根图状态的读取器 ──────────────────────────────────────────────────
# 放在这个叶子模块（不依赖任何编排子包）是为了让 routing/task_rewrite 与
# graphs/supervisor 共用同一份实现：曾出现"状态搬家了、读取方没跟上"的静默
# 降级（`scoped_queries` 读顶层 routing，导致各领域拿到整句而不是子请求）。


def run_of(state: Dict[str, Any] | None) -> Dict[str, Any]:
    """读取每轮派生状态（``run`` 键）；缺省空 dict 便于单测构造局部状态。"""
    if not isinstance(state, dict):
        return {}
    value = state.get("run")
    return dict(value) if isinstance(value, dict) else {}


def routing_of(state: Dict[str, Any] | None) -> Dict[str, Any]:
    """读取本轮路由决策（``run.routing``）。"""
    routing = run_of(state).get("routing")
    return dict(routing) if isinstance(routing, dict) else {}


def task_results_of(state: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    """读取扇出结果通道（``task_results``）。"""
    if not isinstance(state, dict):
        return {}
    value = state.get("task_results")
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "dedupe_concat",
    "merge_dict",
    "replace_keys",
    "routing_of",
    "run_of",
    "task_results_of",
]

