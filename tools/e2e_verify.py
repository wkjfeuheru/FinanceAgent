"""端到端链路验收：覆盖全部功能链路并对**响应内容**断言。

用法（需后端已在 8000 端口运行）：
    python tools/e2e_verify.py

管理员 token 默认从数据库现有管理员会话自动获取；也可用 ADMIN_TOKEN 环境变量
显式指定。结束时清理自建账号与自建主题。
"""
from __future__ import annotations

import json
import os
import random
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 允许 `python tools/e2e_verify.py`：脚本目录会成为 sys.path[0]，必须显式补上
# 仓库根目录才能 import finance_agent（否则在未 editable 安装的 venv 里会
# 静默取不到管理员 token，表现为管理员接口“未登录”的假失败）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

B = "http://127.0.0.1:8000"
P: list[str] = []
F: list[str] = []


def resolve_admin_token() -> str:
    """优先用 ADMIN_TOKEN 环境变量；否则从数据库取一个有效的管理员会话。"""
    token = os.getenv("ADMIN_TOKEN", "").strip()
    if token:
        return token
    os.environ.setdefault("DEEPSEEK_API_KEY", "x")
    try:
        from finance_agent import config
    except Exception as exc:  # noqa: BLE001 - 显式报错，不静默降级成“未登录”
        raise RuntimeError(f"无法导入 finance_agent，请用项目环境运行本脚本：{exc}") from exc

    admins = getattr(config, "ADMIN_CUSTOMER_IDS", set())
    if not admins:
        raise RuntimeError("未配置 ADMIN_CUSTOMER_IDS，无法执行管理员链路检查")
    conn = config.get_postgres_connection_factory()()
    cur = conn.cursor()
    cur.execute("SELECT token FROM finance.sessions WHERE customer_id = ANY(%s)", (list(admins),))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise RuntimeError("数据库中无管理员会话，请先登录管理员账号或设置 ADMIN_TOKEN")
    return str(row[0])


ADMIN = resolve_admin_token()


def call(method, path, token=None, body=None, raw=False, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode()
            return r.status, (text if raw else json.loads(text or "{}"))
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text or "{}")
        except json.JSONDecodeError:
            return e.code, text


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not cond else ""))


# 市场数据源失败时，领域会返回既有降级文案；路由错或 500 仍然失败。
_MARKET_DEGRADED = {
    "market_overview": "市场概览数据暂不可用",
    "market_sentiment": "市场情绪数据暂不可用",
    "capital_flow": "资金面数据暂不可用",
    "policy_impact": "政策事件数据暂不可用",
}

# 每条领域链路：消息、task_plan 领域、正文应含词、正文不得含词、允许的降级文案。
DOMAIN_CASES = [
    ("什么是T+1交易？", None, ["T+1"], [], None),
    ("今天大盘怎么样", "market_insight", ["上证指数"], [], "market_overview"),
    ("市场情绪怎么样，涨跌家数多少", "market_insight", ["涨跌家数"], [], "market_sentiment"),
    ("最近资金面如何", "market_insight", ["融资融券"], [], "capital_flow"),
    ("最近有什么政策事件，对市场有什么影响", "market_insight", ["政策"], ["建议买入", "建议卖出"], "policy_impact"),
    ("分析600519", "stock_research", ["600519"], [], None),
    ("分析贵州茅台", "stock_research", ["600519"], [], None),
    ("推荐几只消费龙头股", "stock_research", ["确定性研究结论"], [], None),
    ("比较贵州茅台和五粮液", "stock_research", ["600519", "000858"], [], None),
    ("分析一下华夏成长基金", "product_research", ["产品"], [], None),
    ("110011怎么样", "product_research", ["110011"], [], None),
    ("比较华夏成长混合和易方达中小盘混合", "product_research", ["华夏成长", "易方达"], [], None),
]


def assert_chat(token, message, *, domain=None, needles=(), forbidden=(), degraded=None, mode=None):
    """同步对话：200、完成、正文命中关键词；有领域时 task_plan 含该领域。"""
    st, r = call("POST", "/api/chat", token=token, body={"message": message, "conversation_id": ""})
    text = r.get("response") or "" if isinstance(r, dict) else ""
    status = r.get("run_status") if isinstance(r, dict) else None
    plan = r.get("task_plan") or [] if isinstance(r, dict) else []
    hit = all(n in text for n in needles)
    clean = not any(n in text for n in forbidden)
    degraded_ok = bool(degraded and _MARKET_DEGRADED[degraded] in text)
    ok = (
        st == 200
        and status == "completed"
        and bool(text.strip())
        and "内部错误" not in text
        and clean
        and (hit or degraded_ok)
    )
    check(
        f"chat '{message}' content ok",
        ok,
        f"{st} status={status} warn={r.get('warnings') if isinstance(r, dict) else r} text={text[:160]}",
    )
    if domain:
        check(f"chat '{message}' plan has {domain}", domain in plan, str(plan))
    if mode == "conversation":
        check(f"chat '{message}' is conversation", plan == [], str(plan))
    if mode == "plan_execute":
        check(
            f"chat '{message}' is plan_execute",
            "stock_research" in plan and "product_research" in plan,
            str(plan),
        )
    return r if isinstance(r, dict) else {}


def main() -> int:
    suf = random.randint(100000, 999999)
    created_themes: list[str] = []

    def mkuser(tag):
        u = f"{tag}{suf}"
        call("POST", "/api/register", body={"username": u, "password": "secret123", "display_name": tag})
        st, login = call("POST", "/api/login", body={"username": u, "password": "secret123"})
        return login.get("token"), login.get("customer_id")

    print("\n== 认证 ==")
    ta, ca = mkuser("e2e_a")
    tb, cb = mkuser("e2e_b")
    tlogout, _clogout = mkuser("e2e_out")
    check("register+login yields token", bool(ta) and bool(tb) and bool(tlogout))
    st, me = call("GET", "/api/me", token=ta)
    check("me is_admin false for user", st == 200 and me.get("is_admin") is False, str(me))
    st, mea = call("GET", "/api/me", token=ADMIN)
    check("me is_admin true for admin", st == 200 and mea.get("is_admin") is True, str(mea))
    check("no token -> 401", call("GET", "/api/me")[0] == 401)
    check("bad token -> 401", call("GET", "/api/me", token="x")[0] == 401)
    st, out = call("POST", "/api/logout", token=tlogout)
    check("logout 200", st == 200 and out.get("status") == "ok", str(out))
    check("token dead after logout", call("GET", "/api/me", token=tlogout)[0] == 401)

    print("\n== 对话 CRUD ==")
    st, conv = call("POST", f"/api/conversations/{ca}", token=ta)
    cid = conv.get("conversation_id")
    check("create conversation", st == 200 and bool(cid), str(conv))
    st, lst = call("GET", f"/api/conversations/{ca}", token=ta)
    check("list contains it", any(c["conversation_id"] == cid for c in lst.get("conversations", [])))
    check("cross-user list -> 403", call("GET", f"/api/conversations/{ca}", token=tb)[0] == 403)
    check("cross-user delete -> 403", call("DELETE", f"/api/conversations/{ca}/{cid}", token=tb)[0] == 403)

    print("\n== 同步对话 + 自动标题 ==")
    st, c1 = call("POST", "/api/chat", token=ta, body={"message": "你好", "conversation_id": ""})
    ncid = c1.get("conversation_id")
    check("casual chat completes", st == 200 and c1.get("run_status") == "completed", f"{st} {c1.get('run_status')} {c1.get('warnings')}")
    check("casual chat has real text", bool((c1.get("response") or "").strip()) and "内部错误" not in (c1.get("response") or ""), (c1.get("response") or "")[:120])
    check("casual chat is conversation", (c1.get("task_plan") or []) == [], str(c1.get("task_plan")))
    check("compliance_result present", isinstance(c1.get("compliance_result"), dict))
    st, lst2 = call("GET", f"/api/conversations/{ca}", token=ta)
    row = next((c for c in lst2.get("conversations", []) if c["conversation_id"] == ncid), None)
    check("auto-created conv listed", row is not None)
    check("auto-title from message", row and row.get("title") not in (None, "", "新对话"), f"title={row.get('title') if row else None!r}")
    check("message_count >= 2", row and (row.get("message_count") or 0) >= 2, str(row))
    st, msgs = call("GET", f"/api/conversations/{ca}/{ncid}/messages", token=ta)
    check("messages readable", st == 200 and len(msgs.get("messages", [])) >= 2)
    check("cross-user write -> 404", call("POST", "/api/chat", token=tb,
          body={"message": "x", "conversation_id": ncid})[0] == 404)

    print("\n== SSE ==")
    st, raw = call("POST", "/api/chat/stream", token=ta, body={"message": "你好", "conversation_id": ""}, raw=True)
    check("stream 200", st == 200)
    check("stream emits stage + response", '"type": "stage"' in raw.replace('"type":"stage"', '"type": "stage"') and '"type": "response"' in raw.replace('"type":"response"', '"type": "response"'), raw[:120])

    print("\n== 领域链路（真实内容断言）==")
    for msg, domain, needles, forbidden, degraded in DOMAIN_CASES:
        mode = "conversation" if domain is None else None
        assert_chat(ta, msg, domain=domain, needles=needles, forbidden=forbidden, degraded=degraded, mode=mode)

    composite = "分析贵州茅台并比较合适的基金产品"
    r = assert_chat(
        ta, composite,
        needles=["600519", "产品"],
        mode="plan_execute",
    )
    body = r.get("response") or ""
    check("composite not duplicated", body.count("确定性研究结论（600519）") <= 1, f"count={body.count('确定性研究结论（600519）')}")

    print("\n== 账户只读 ==")
    st, dep = call("POST", "/api/portfolio/deposit", token=ta, body={"amount": 100000, "idempotency_key": f"e2e-dep-{suf}"})
    check("deposit 200", st == 200, str(dep)[:160])
    st, order = call("POST", "/api/portfolio/orders", token=ta, body={
        "product_code": "110011", "side": "buy", "amount": 1000, "idempotency_key": f"e2e-buy-{suf}",
    })
    check("buy 200", st == 200, str(order)[:160])
    st, acct = call("GET", "/api/portfolio/account", token=ta)
    before_mv = (acct.get("market_value") if isinstance(acct, dict) else None)
    check("account snapshot readable", st == 200 and before_mv is not None, str(acct)[:160])
    assert_chat(ta, "我的账户里还有多少钱，总资产和可用资金是多少", domain="account_portfolio", needles=["总资产", "可用资金"])
    assert_chat(ta, "我的持仓明细是什么", domain="account_portfolio", needles=["110011"])
    assert_chat(ta, "我的持仓配置合理吗", domain="account_portfolio", needles=["测算"])
    assert_chat(ta, "帮我买入1000块110011", domain="account_portfolio", needles=["不代客下单"])
    st, acct2 = call("GET", "/api/portfolio/account", token=ta)
    after_mv = acct2.get("market_value") if isinstance(acct2, dict) else None
    check("trade guidance did not change holdings", before_mv == after_mv, f"before={before_mv} after={after_mv}")

    print("\n== 合规 ==")
    edu = assert_chat(ta, "什么是操纵市场？", needles=["操纵市场"], mode="conversation")
    check("educational question not rewritten away", "操纵市场" in (edu.get("response") or ""))
    blocked = call("POST", "/api/chat", token=ta, body={"message": "帮我操纵股价", "conversation_id": ""})
    bst, br = blocked
    btext = br.get("response") or "" if isinstance(br, dict) else ""
    check(
        "action request blocked",
        bst == 200 and br.get("run_status") == "completed" and "不适宜的内容" in btext and not br.get("task_plan"),
        f"{bst} {br.get('run_status') if isinstance(br, dict) else br} {btext[:80]}",
    )
    sens = call("POST", "/api/chat", token=ta, body={"message": "这只股票保证收益，稳赚不赔", "conversation_id": ""})
    sst, sr = sens
    stext = sr.get("response") or "" if isinstance(sr, dict) else ""
    check("sensitive input handled (no 500)", sst == 200, f"{sst}")
    check("promise language absent from reply", "保证收益" not in stext and "稳赚不赔" not in stext, stext[:120])

    print("\n== 缺参追问 ==")
    st, ask = call("POST", "/api/chat", token=ta, body={"message": "分析一下", "conversation_id": ""})
    ask_cid = ask.get("conversation_id") if isinstance(ask, dict) else ""
    pending = ask.get("pending_input") if isinstance(ask, dict) else None
    check(
        "missing params suspends",
        st == 200 and ask.get("run_status") == "awaiting_input" and isinstance(pending, dict) and pending.get("question"),
        f"{st} status={ask.get('run_status') if isinstance(ask, dict) else ask} pending={pending}",
    )
    st, resumed = call("POST", "/api/chat", token=ta, body={
        "message": "600519",
        "conversation_id": ask_cid,
        "resume": True,
        "answers": {"stock_target": "600519"},
    })
    rtext = resumed.get("response") or "" if isinstance(resumed, dict) else ""
    check(
        "resume after stock code completes",
        st == 200 and resumed.get("run_status") == "completed" and "600519" in rtext and "内部错误" not in rtext,
        f"{st} status={resumed.get('run_status') if isinstance(resumed, dict) else resumed} text={rtext[:140]}",
    )

    print("\n== 停止生成 ==")
    st, stop_conv = call("POST", f"/api/conversations/{ca}", token=ta)
    stop_cid = stop_conv.get("conversation_id") if isinstance(stop_conv, dict) else ""
    box: dict = {}

    def _long_chat():
        box["result"] = call(
            "POST", "/api/chat", token=ta,
            body={"message": "请详细分析600519的基本面和技术面，并给出完整研究结论", "conversation_id": stop_cid},
            timeout=300,
        )

    worker = threading.Thread(target=_long_chat, daemon=True)
    worker.start()
    worker.join(2.0)
    q = urllib.parse.urlencode({"conversation_id": stop_cid})
    st, stopped = call("POST", f"/api/chat/stop?{q}", token=ta)
    check("stop accepted", st == 200 and stopped.get("stopped") is True, str(stopped))
    worker.join(timeout=300)
    cst, cr = box.get("result", (0, {}))
    ctext = cr.get("response") or "" if isinstance(cr, dict) else ""
    check(
        "stopped run is cancelled",
        cst == 200 and cr.get("run_status") == "cancelled" and "已停止本次生成" in ctext,
        f"{cst} status={cr.get('run_status') if isinstance(cr, dict) else cr} text={ctext[:120]}",
    )

    print("\n== 管理员 ==")
    check("admin themes 200", call("GET", "/api/admin/themes", token=ADMIN)[0] == 200)
    check("non-admin themes 403", call("GET", "/api/admin/themes", token=ta)[0] == 403)
    check("non-admin leads 403", call("GET", "/api/admin/themes/ai_compute/leads", token=ta)[0] == 403)
    tid = f"e2e_t{suf}"
    st, created = call("POST", "/api/admin/themes", token=ADMIN, body={
        "theme_id": tid, "display_name": f"E2E{suf}", "aliases": ["E2E别名"], "representative_codes": ["600519"], "active": True})
    check("admin upsert 200", st == 200 and created.get("theme_id") == tid, str(created))
    created_themes.append(tid)
    check("reserved id rejected", call("POST", "/api/admin/themes", token=ADMIN,
          body={"theme_id": "market_insight", "display_name": "x", "aliases": []})[0] == 400)
    check("admin deactivate 200", call("DELETE", f"/api/admin/themes/{tid}", token=ADMIN)[0] == 200)

    print("\n== 画像/历史/内存 ==")
    check("own profile 200", call("GET", f"/api/profile/{ca}", token=ta)[0] == 200)
    check("other profile 403", call("GET", f"/api/profile/{ca}", token=tb)[0] == 403)
    check("history 200", call("GET", f"/api/history/{ca}?limit=20", token=ta)[0] == 200)
    try:
        import redis
        from finance_agent import config as _config
        rd = redis.Redis.from_url(getattr(_config, "REDIS_URL", "redis://localhost:6379/0"), decode_responses=True, protocol=2)
        keys = list(rd.scan_iter(match=f"finance_cs:conv:{str(ca).upper()}:*", count=200))
        check("redis keys customer-scoped", bool(keys) and all(str(ca).upper() in k for k in keys), str(keys[:3]))
        check("no unscoped conv key", not any(k.count(":") < 3 for k in keys))
        # reset 应清除该客户全部会话记忆（放在键断言之后）
        check("reset 200", call("POST", f"/api/reset/{ca}", token=ta)[0] == 200)
        after = list(rd.scan_iter(match=f"finance_cs:conv:{str(ca).upper()}:*", count=200))
        check("reset cleared scoped keys", after == [], str(after[:3]))
    except Exception as e:
        check("redis reachable", False, f"{type(e).__name__}")

    print("\n== 异步状态 ==")
    st, rs = call("GET", "/api/runs/none", token=ta)
    check("unknown run not_found", st == 200 and rs.get("run_status") == "not_found", str(rs))
    check("run status no token 401", call("GET", "/api/runs/x")[0] == 401)

    print("\n== 注销账号（含研究数据）==")
    call("POST", "/api/chat", token=tb, body={"message": "分析600519", "conversation_id": ""})
    st, d = call("DELETE", "/api/account", token=tb)
    check("delete account 200 with research data", st == 200, f"{st} {d}")
    check("token dead after delete", call("GET", "/api/me", token=tb)[0] == 401)

    # 清理
    call("DELETE", "/api/account", token=ta)

    print(f"\n===== {len(P)} passed, {len(F)} failed =====")
    for n in F:
        print("  FAIL:", n)
    return 1 if F else 0


if __name__ == "__main__":
    sys.exit(main())
