"""编排层共享 reducer 工具模块。

供 Plan-and-Execute 等子图在 LangGraph Send 并发扇出时合并同名状态键：
- 映射类（分片结果、股票数据等）按 key 合并（merge_dict）；
- 列表类（事实、分析结果、告警等）拼接并按身份去重（dedupe_concat）。
其余键保持 LangGraph 默认的 last-write-wins。
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

