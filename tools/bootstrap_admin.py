"""引导管理员账号：创建/提升一个管理员，并把其余用户降为普通用户。

背景：管理员此前只由 ``ADMIN_CUSTOMER_IDS`` 环境变量决定，无法在库内表达。
本脚本把角色落进 ``finance.users.is_admin``（``sql/013_admin_console.sql``），
使"谁是管理员"成为可持久、可审计的数据。

用法：

    # 创建（或提升）管理员 admin，并确保其他人都不是管理员
    python tools/bootstrap_admin.py --username admin --password 'YourPassw0rd'

    # 只查看当前角色分布，不做任何写入
    python tools/bootstrap_admin.py --dry-run

脚本是幂等的：重复运行只会把目标账号置为管理员、其余账号置为非管理员。
密码不回显，明文不落库（与注册接口同用 PBKDF2-SHA256 + 随机盐）。

安全提示：``--password`` 会出现在 shell 历史里；如需避免，可改用
``FINANCE_ADMIN_PASSWORD`` 环境变量。
"""

from __future__ import annotations

import argparse
import os
import sys

from finance_agent.data.auth import get_user_store


def _print_roles(store) -> int:
    rows = store.list_users()
    if not rows:
        print("库内没有用户。")
        return 0
    admins = 0
    for row in rows:
        mark = "管理员" if row.get("is_admin") else "普通用户"
        if row.get("is_admin"):
            admins += 1
        print(f"  {row.get('customer_id'):<14} {row.get('username'):<20} {mark}")
    print(f"共 {len(rows)} 个用户，其中管理员 {admins} 个。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="引导管理员账号并同步库内角色")
    parser.add_argument("--username", default="admin", help="管理员用户名（默认 admin）")
    parser.add_argument(
        "--password",
        default=os.environ.get("FINANCE_ADMIN_PASSWORD", ""),
        help="管理员密码；也可用环境变量 FINANCE_ADMIN_PASSWORD",
    )
    parser.add_argument("--display-name", default="", help="显示名（默认与用户名相同）")
    parser.add_argument(
        "--keep-others",
        action="store_true",
        help="保留其他用户的管理员角色（默认把其他人都降为普通用户）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印当前角色，不写入任何数据")
    args = parser.parse_args(argv)

    # list_users 内部会触发建表（含 013 的角色列补齐）。
    store = get_user_store()

    if args.dry_run:
        print("当前用户角色：")
        return _print_roles(store)

    if not args.password:
        parser.error("必须提供 --password 或环境变量 FINANCE_ADMIN_PASSWORD")
    from finance_agent.config import IS_PRODUCTION
    from finance_agent.data.postgres_stores import _validate_password

    try:
        _validate_password(args.password)
    except ValueError as exc:
        parser.error(str(exc))
    if IS_PRODUCTION and len(args.password) < 12:
        parser.error("生产环境管理员密码至少 12 个字符")

    username = args.username.strip()

    # 已存在则只重置密码并提升；不存在则创建。
    existing = store.get_user_by_username(username)
    if existing is None:
        created = store.register(
            username=username, password=args.password,
            display_name=args.display_name, is_admin=True,
        )
        customer_id = created["customer_id"]
        print(f"已创建管理员 {username}（customer_id={customer_id}）")
    else:
        customer_id = existing["customer_id"]
        store.set_password(customer_id, args.password)
        store.set_admin(customer_id, True)
        print(f"已将既有用户 {username}（customer_id={customer_id}）提升为管理员并重置密码")

    if not args.keep_others:
        demoted: list[str] = []
        for row in store.list_users():
            if str(row.get("customer_id")) == customer_id:
                continue
            if row.get("is_admin") and store.set_admin(row["customer_id"], False):
                demoted.append(str(row.get("username")))
        if demoted:
            print(f"已降为普通用户：{', '.join(demoted)}")
        else:
            print("没有其他管理员需要降级。")

    print("\n当前用户角色：")
    _print_roles(store)
    print(
        "\n下一步：确认 .env 未把普通用户写进 ADMIN_CUSTOMER_IDS —— 该白名单与库内角色"
        "\n取并集，留着旧值会让被降级的用户继续拥有管理员权限。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
