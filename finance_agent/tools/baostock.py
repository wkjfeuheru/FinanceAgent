"""BaoStock A 股数据工具：附带本地缓存降级与硬超时保护。"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import baostock as bs
import pandas as pd

from finance_agent.config import BAOSTOCK_SOCKET_TIMEOUT, STOCK_CACHE_DIR, STOCK_CACHE_TTL

_A_SHARE_CODE = re.compile(r"^(?:(?:60|68|00|30)\d{4}|[84]\d{5})$")
_HARD_TIMEOUT = max(BAOSTOCK_SOCKET_TIMEOUT + 10, 25)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None or str(value).strip() == "" else float(value)
    except (TypeError, ValueError):
        return default


class _BaoStockTimeout(Exception):
    """BaoStock 操作在硬超时内未完成。"""


def _run_with_timeout(func: Callable[[], Any], timeout: float = _HARD_TIMEOUT) -> Any:
    """在子线程中执行 func，超时则抛出 _BaoStockTimeout。

    这是最后的防线：socket.setdefaulttimeout 覆盖 TCP 读写，子线程
    join(timeout) 覆盖 DNS/SSL/协议握手等无法被 socket timeout 保护的情况。
    """
    result: list[Any] = []
    error: list[Exception | None] = [None]
    done = threading.Event()

    def _target() -> None:
        try:
            result.append(func())
        except Exception as exc:
            error[0] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    if not done.wait(timeout):
        raise _BaoStockTimeout(f"BaoStock 操作超时（{timeout:.0f}s 未完成）")
    if error[0] is not None:
        raise error[0]
    return result[0] if result else None


class BaostockDataSource:
    """BaoStock 适配器，对外保持原有行情/基本面字段格式。"""

    _session_lock = threading.RLock()
    _cache_lock = threading.RLock()
    _unavailable_until = 0.0
    _last_connection_error = ""

    def __init__(self, cache_dir: str = STOCK_CACHE_DIR, cache_ttl: int = STOCK_CACHE_TTL):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = max(0, cache_ttl)
        self._migrate_legacy_cache_files()

    @staticmethod
    def _code(stock_code: str) -> str:
        code = str(stock_code).strip()
        if not _A_SHARE_CODE.fullmatch(code):
            raise ValueError(f"无效的 A 股代码: {stock_code}")
        return code

    @staticmethod
    def _bs_code(code: str) -> str:
        if code.startswith(("60", "68")):
            return f"sh.{code}"
        if code.startswith(("00", "30")):
            return f"sz.{code}"
        raise ValueError("BaoStock 暂不支持北交所股票")

    @staticmethod
    def _error(code: str, kind: str, exc: Exception | str) -> dict[str, Any]:
        return {"code": code, "error": f"获取{kind}失败: {exc}", "source": "baostock"}

    # ── 批量查询：一次登录完成多个查询，大幅减少网络往返 ──────────

    @classmethod
    def _query_batch(cls, queries: list[Callable[[], Any]]) -> list[pd.DataFrame]:
        """在单次登录会话中执行多个查询，返回与 queries 等长的 DataFrame 列表。

        每个 query 是 () -> bs query result 的无参可调用对象。
        """
        if not queries:
            return []

        with cls._session_lock:
            if time.monotonic() < cls._unavailable_until:
                raise RuntimeError(
                    cls._last_connection_error or "BaoStock 暂时不可用，已跳过重复联网请求"
                )

            previous_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(BAOSTOCK_SOCKET_TIMEOUT)
            try:
                login = bs.login()
                if login.error_code != "0":
                    raise RuntimeError(login.error_msg)

                results: list[pd.DataFrame] = []
                for query in queries:
                    result = query()
                    if result.error_code != "0":
                        raise RuntimeError(result.error_msg)
                    rows: list[list[str]] = []
                    while result.next():
                        rows.append(result.get_row_data())
                    results.append(
                        pd.DataFrame(rows, columns=result.fields) if rows
                        else pd.DataFrame(columns=result.fields or [])
                    )

                cls._unavailable_until = 0.0
                cls._last_connection_error = ""
                return results
            except Exception as exc:
                cls._last_connection_error = f"BaoStock 连接失败: {exc}"
                cls._unavailable_until = time.monotonic() + 60.0
                raise
            finally:
                try:
                    bs.logout()
                finally:
                    socket.setdefaulttimeout(previous_timeout)

    @classmethod
    def _query(cls, query: Callable[[], Any]) -> pd.DataFrame:
        """执行单个查询（登录→查询→登出），带硬超时保护。"""
        return _run_with_timeout(
            lambda: cls._query_batch([query])[0],
            _HARD_TIMEOUT,
        )

    # ── 缓存管理 ────────────────────────────────────────────────

    @staticmethod
    def _safe_cache_key(key: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", key)

    def _cache_file(self, key: str) -> Path:
        """Return the shared cache file for a data category."""
        category = self._safe_cache_key(key).split("_", 1)[0]
        return self.cache_dir / f"{category}.json"

    def _legacy_cache_file(self, key: str) -> Path:
        return self.cache_dir / f"{self._safe_cache_key(key)}.json"

    @staticmethod
    def _decode_cache_entry(payload: Any) -> tuple[pd.DataFrame | None, float]:
        if not isinstance(payload, dict):
            return None, 0.0
        try:
            return pd.DataFrame(payload.get("data", [])), float(payload.get("cached_at", 0))
        except (ValueError, TypeError):
            return None, 0.0

    def _read_cache_entry(self, key: str) -> tuple[pd.DataFrame | None, float]:
        path = self._cache_file(key)
        legacy_path = self._legacy_cache_file(key)
        with self._cache_lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                cached, cached_at = self._decode_cache_entry(payload.get("entries", {}).get(key))
                if cached is not None:
                    return cached, cached_at
            except (OSError, ValueError, TypeError):
                pass

            # Read old one-request-per-file caches and migrate them lazily.
            if legacy_path != path and legacy_path.exists():
                try:
                    entry = json.loads(legacy_path.read_text(encoding="utf-8"))
                    cached, cached_at = self._decode_cache_entry(entry)
                    if cached is not None:
                        self._write_cache_entry(key, entry)
                        try:
                            legacy_path.unlink()
                        except OSError:
                            pass
                        return cached, cached_at
                except (OSError, ValueError, TypeError):
                    pass
        return None, 0.0

    def _write_cache_entry(self, key: str, entry: dict[str, Any]) -> None:
        path = self._cache_file(key)
        with self._cache_lock:
            payload: dict[str, Any] = {"version": 1, "entries": {}}
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and isinstance(existing.get("entries"), dict):
                        payload = existing
                except (OSError, ValueError, TypeError):
                    pass
            payload["version"] = 1
            payload.setdefault("entries", {})[key] = entry
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
            temp.replace(path)

    def _migrate_legacy_cache_files(self) -> None:
        """Combine old one-request-per-file caches into category files."""
        for legacy_path in self.cache_dir.glob("*.json"):
            try:
                payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(payload, dict) or "cached_at" not in payload or "data" not in payload:
                continue
            key = legacy_path.stem
            grouped_path = self._cache_file(key)
            if grouped_path == legacy_path:
                continue
            try:
                self._write_cache_entry(key, payload)
                legacy_path.unlink()
            except OSError:
                # A failed cleanup is harmless; the legacy reader remains compatible.
                continue

    def _load_or_fetch(self, key: str, loader: Callable[[], pd.DataFrame]) -> tuple[pd.DataFrame, bool]:
        cached, cached_at = self._read_cache_entry(key)
        # 空结果也缓存，避免对尚未披露的季度反复请求远端。
        if cached is not None and time.time() - cached_at <= self.cache_ttl:
            return cached, True
        try:
            frame = loader()
            self._write_cache_entry(
                key,
                {"cached_at": time.time(), "data": frame.to_dict(orient="records")},
            )
            return frame, False
        except Exception:
            if cached is not None and not cached.empty:
                return cached, True
            raise

    # ── 批量加载：一次远端请求获取多条缓存缺失数据（减少 login/logout）──

    def _load_or_fetch_batch(self, entries: list[tuple[str, Callable[[], pd.DataFrame]]]) -> list[tuple[str, pd.DataFrame, bool]]:
        """批量加载多条数据。

        每条 entry 是 (cache_key, loader)。返回 [(key, df, from_cache), ...]。
        先检查缓存，只对未命中且未过期的条目做一次批量远端请求。
        """
        results: list[tuple[str, pd.DataFrame, bool]] = []
        missing: list[tuple[str, Callable[[], pd.DataFrame]]] = []

        for key, loader in entries:
            cached, cached_at = self._read_cache_entry(key)
            if cached is not None and time.time() - cached_at <= self.cache_ttl:
                results.append((key, cached, True))
            else:
                missing.append((key, loader))

        if missing:
            # 一次登录完成所有远端查询
            try:
                frames = self._query_batch([loader for _, loader in missing])
                for (key, _), frame in zip(missing, frames):
                    self._write_cache_entry(
                        key,
                        {"cached_at": time.time(), "data": frame.to_dict(orient="records")},
                    )
                    results.append((key, frame, False))
            except Exception:
                # 远端失败时尝试回退到过期缓存
                for key, _loader in missing:
                    cached, _ = self._read_cache_entry(key)
                    if cached is not None and not cached.empty:
                        results.append((key, cached, True))
                    else:
                        raise

        return results

    def _history_frame(self, code: str, period: str, start: str, end: str, adjust: str) -> tuple[pd.DataFrame, bool]:
        frequency = {"daily": "d", "weekly": "w", "monthly": "m"}[period]
        adjustflag = {"qfq": "2", "hfq": "1", "": "3"}.get(adjust, "2")
        fields = "date,open,high,low,close,preclose,volume,amount,pctChg,turn,peTTM,pbMRQ"
        return self._load_or_fetch(
            f"history_{code}_{period}_{start}_{end}_{adjust}",
            lambda: self._query(lambda: bs.query_history_k_data_plus(
                self._bs_code(code), fields, start_date=start, end_date=end,
                frequency=frequency, adjustflag=adjustflag,
            )),
        )

    def get_history(self, stock_code: str, period: str = "daily", start_date: str = "",
                    end_date: str = "", adjust: str = "qfq") -> pd.DataFrame | dict[str, Any]:
        try:
            code = self._code(stock_code)
            if period not in {"daily", "weekly", "monthly"}:
                raise ValueError("period 仅支持 daily/weekly/monthly")
            end = end_date or datetime.now().strftime("%Y-%m-%d")
            start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            df, from_cache = self._history_frame(code, period, start, end, adjust)
            if df.empty:
                return self._error(code, "历史行情", "返回数据为空")
            result = df.rename(columns={"pctChg": "change_pct", "turn": "turnover_rate"}).copy()
            numeric = ["open", "close", "high", "low", "volume", "amount", "change_pct", "turnover_rate"]
            for column in numeric:
                result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
            result["change_amount"] = result["close"] - pd.to_numeric(result["preclose"], errors="coerce").fillna(0)
            result.attrs["source"] = "baostock_cache" if from_cache else "baostock"
            columns = ["date", "open", "close", "high", "low", "volume", "amount",
                       "change_pct", "change_amount", "turnover_rate"]
            return result[columns].sort_values("date").reset_index(drop=True)
        except Exception as exc:
            return self._error(str(stock_code).strip(), "历史行情", exc)

    def get_realtime_quote(self, stock_code: str) -> dict[str, Any]:
        """返回最近交易日行情；BaoStock 不提供盘中实时数据。"""
        try:
            code = self._code(stock_code)
            end = datetime.now()
            df, from_cache = self._history_frame(code, "daily", (end - timedelta(days=15)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "qfq")
            if df.empty:
                return self._error(code, "最近交易日行情", "返回数据为空")
            row = df.sort_values("date").iloc[-1]
            basic = self.get_basic_info(code)
            return {
                "code": code, "name": basic.get("name", ""), "date": str(row.get("date", "")),
                "price": _number(row.get("close")), "change_pct": _number(row.get("pctChg")),
                "change_amount": _number(row.get("close")) - _number(row.get("preclose")),
                "volume": _number(row.get("volume")), "amount": _number(row.get("amount")),
                "high": _number(row.get("high")), "low": _number(row.get("low")),
                "open": _number(row.get("open")), "prev_close": _number(row.get("preclose")),
                "turnover_rate": _number(row.get("turn")), "pe": _number(row.get("peTTM")),
                "pb": _number(row.get("pbMRQ")), "total_market_cap": 0, "circulating_market_cap": 0,
                "is_realtime": False, "from_cache": from_cache, "source": "baostock",
            }
        except Exception as exc:
            return self._error(str(stock_code).strip(), "最近交易日行情", exc)

    def get_basic_info(self, stock_code: str) -> dict[str, Any]:
        try:
            code = self._code(stock_code)
            basic, cached = self._load_or_fetch(f"basic_{code}", lambda: self._query(lambda: bs.query_stock_basic(code=self._bs_code(code))))
            industry, _ = self._load_or_fetch(f"industry_{code}", lambda: self._query(lambda: bs.query_stock_industry(code=self._bs_code(code))))
            if basic.empty:
                return self._error(code, "股票基本信息", "返回数据为空")
            row = basic.iloc[0]
            return {
                "code": code, "name": str(row.get("code_name", "")),
                "industry": "" if industry.empty else str(industry.iloc[0].get("industry", "")),
                "listing_date": str(row.get("ipoDate", "")), "out_date": str(row.get("outDate", "")),
                "status": str(row.get("status", "")), "from_cache": cached, "source": "baostock",
            }
        except Exception as exc:
            return self._error(str(stock_code).strip(), "股票基本信息", exc)

    def validate_stock_identity(self, stock_code: str, expected_name: str) -> dict[str, Any]:
        """用 BaoStock 校验搜索返回的代码与证券简称是否匹配。"""
        try:
            code = self._code(stock_code)
            basic, _ = self._load_or_fetch(
                f"basic_{code}",
                lambda: self._query(lambda: bs.query_stock_basic(code=self._bs_code(code))),
            )
            if basic.empty:
                return self._error(code, "股票身份校验", "代码不存在")
            actual_name = str(basic.iloc[0].get("code_name", "")).strip()
            expected = str(expected_name).strip()
            comparable_actual = actual_name.removeprefix("ST").removeprefix("*ST")
            comparable_expected = expected.removeprefix("ST").removeprefix("*ST")
            # Empty expected_name is allowed for the regex fallback; BaoStock then
            # acts as the authoritative source for both code existence and name.
            if comparable_expected and comparable_actual != comparable_expected:
                return self._error(
                    code, "股票身份校验", f"代码对应名称为{actual_name}，搜索返回名称为{expected}"
                )
            return {"code": code, "name": actual_name, "source": "baostock"}
        except Exception as exc:
            return self._error(str(stock_code).strip(), "股票身份校验", exc)

    def get_financial_indicators(self, stock_code: str) -> dict[str, Any]:
        """获取财务指标。

        优化：一次登录批量查询 profit + growth + balance，以及最多 8 个季度
        的 profit 数据。从原来的 11 次 login/logout 压缩为最多 1-2 次。
        """
        try:
            code = self._code(stock_code)
            now = datetime.now()

            # 先尝试最近一个季度的缓存命中
            frame = pd.DataFrame()
            year = 0
            quarter = 0
            for offset in range(8):
                index = now.year * 4 + (now.month - 1) // 3 - offset
                y, q0 = divmod(index - 1, 4)
                q = q0 + 1
                cached_key = f"profit_{code}_{y}_{q}"
                cached, cached_at = self._read_cache_entry(cached_key)
                if cached is not None and time.time() - cached_at <= self.cache_ttl:
                    frame = cached
                    year, quarter = y, q
                    break

            # 无缓存命中：批量查询最近几个季度的 profit 数据
            if frame.empty:
                entries: list[tuple[str, Callable[[], pd.DataFrame]]] = []
                quarters_searched: list[tuple[int, int]] = []
                for offset in range(4):  # 只批量查询最近 4 个季度
                    index = now.year * 4 + (now.month - 1) // 3 - offset
                    y, q0 = divmod(index - 1, 4)
                    q = q0 + 1
                    key = f"profit_{code}_{y}_{q}"
                    quarters_searched.append((y, q))
                    entries.append((
                        key,
                        lambda yy=y, qq=q: bs.query_profit_data(
                            code=self._bs_code(code), year=yy, quarter=qq,
                        ),
                    ))
                try:
                    batch_results = self._load_or_fetch_batch(entries)
                    for (key, df, _), (y_found, q_found) in zip(batch_results, quarters_searched):
                        if not df.empty:
                            frame = df
                            year, quarter = y_found, q_found
                            break
                except Exception:
                    pass

            if frame.empty:
                return self._error(code, "财务指标", "最近季度均无财务数据")

            # 批量获取同季度的 growth 和 balance 数据
            growth = pd.DataFrame()
            balance = pd.DataFrame()
            try:
                growth_balance_entries = [
                    (f"growth_{code}_{year}_{quarter}", lambda: bs.query_growth_data(
                        code=self._bs_code(code), year=year, quarter=quarter,
                    )),
                    (f"balance_{code}_{year}_{quarter}", lambda: bs.query_balance_data(
                        code=self._bs_code(code), year=year, quarter=quarter,
                    )),
                ]
                gb_results = self._load_or_fetch_batch(growth_balance_entries)
                for key, df, _ in gb_results:
                    if "growth" in key:
                        growth = df
                    elif "balance" in key:
                        balance = df
            except Exception:
                pass

            row = frame.iloc[0]
            growth_row = growth.iloc[0] if not growth.empty else {}
            balance_row = balance.iloc[0] if not balance.empty else {}
            return {
                "code": code, "date": str(row.get("statDate", row.get("pubDate", ""))),
                "roe": _number(row.get("roeAvg")) * 100, "net_profit_margin": _number(row.get("npMargin")) * 100,
                "gross_margin": _number(row.get("gpMargin")) * 100,
                "revenue_growth": None,
                "net_profit_growth": _number(growth_row.get("YOYNI")) * 100,
                "total_asset_growth": _number(growth_row.get("YOYAsset")) * 100,
                "debt_ratio": _number(balance_row.get("liabilityToAsset")) * 100,
                "current_ratio": _number(balance_row.get("currentRatio")),
                "quick_ratio": _number(balance_row.get("quickRatio")),
                "eps": _number(row.get("epsTTM")), "net_profit": _number(row.get("netProfit")),
                "total_shares": _number(row.get("totalShare")),
                "net_assets_per_share": 0, "pe": 0, "pb": 0,
                "source": "baostock",
            }
        except Exception as exc:
            return self._error(str(stock_code).strip(), "财务指标", exc)


_datasource_instance: BaostockDataSource | None = None


def get_datasource() -> BaostockDataSource:
    global _datasource_instance
    if _datasource_instance is None:
        _datasource_instance = BaostockDataSource()
    return _datasource_instance
