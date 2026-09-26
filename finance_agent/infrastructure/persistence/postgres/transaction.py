"""共享的 PostgreSQL 连接/事务实现（Task 4）。

此前 ``postgres_stores``、``postgres_repository`` 与 ``faq.repository`` 各自内联
一份 ``_transaction``（commit / rollback / close 三行语义各写一遍），漂移风险高。
现在收敛到本模块的 ``TransactionRunner``：所有持久化适配器继承或直接引用
``TransactionRunner.transaction``，提交/回滚语义只有一处。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator


class TransactionRunner:
    """按连接工厂执行事务的共享实现。"""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """提交成功事务，异常时回滚并关闭连接。

        连接无论如何都关闭；成功即提交，失败即回滚后重新抛出，让调用方的
        降级/审计路径能看到真实异常。
        """
        connection = self._connection_factory()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


__all__ = ["TransactionRunner"]
