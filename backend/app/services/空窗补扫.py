"""空窗补扫器（主链协同，非空桩）。

对已抬过水位的区间做**补扫**：按架构「戳冻结区间」——

- 已戳窗键：只核验策略戳（策略码/窗键清单/戳号/世代），**禁止再次创建或删除空窗行**；
  核验漂移（戳=发射零窗却缺行 / 戳=跳过却有零窗行）即 fail-closed 整票回滚；
- 未戳缺口：沿用关窗扫描按现行策略处置，处置成功**同票写新策略戳**。

补扫与水位抬升共用同一 `尝试关窗` 唯一入口与整批 `BEGIN IMMEDIATE` 事务，
故补扫与抬升抢锁时不会凭空插入零窗行：要么整票成功（含戳），要么整体回滚。
"""

from app.db import 连接
from app.modules import 空窗发射策略 as 空策
from app.modules import 空窗策略戳 as 空戳
from app.seed import 此刻
from app.services import 热度窗


def 补扫一房(conn, 房间键: str, 窗长秒: int, 处理时: str = "") -> dict:
    """在调用方事务内补扫一房；返回新戳号、冻结校验数、关窗/零窗数。"""
    水位行 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()
    if not 水位行:
        return {"房间键": 房间键, "跳过": "无水位线"}
    果 = 热度窗.尝试关窗(
        conn,
        房间键,
        水位行["事件时水位"],
        int(水位行["允许迟到秒"]),
        窗长秒,
        处理时 or 此刻(),
    )
    return {"房间键": 房间键, **果}


def 补扫(房间键: str | None = None) -> dict:
    """补扫全部房（或指定房），整票事务，失败整体回滚。"""
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        窗长 = int(
            (conn.execute("SELECT 值 FROM 站规 WHERE 键='窗长秒'").fetchone() or {"值": "60"})["值"]
        )
        if 房间键:
            房们 = [{"房间键": 房间键}] if conn.execute(
                "SELECT 1 FROM 直播间 WHERE 房间键=?", (房间键,)
            ).fetchone() else []
        else:
            房们 = [dict(r) for r in conn.execute("SELECT 房间键 FROM 直播间 ORDER BY 房间键")]

        处理时 = 此刻()
        明细 = [补扫一房(conn, f["房间键"], 窗长, 处理时) for f in 房们]
        核 = 空戳.核证(conn)
        conn.commit()
        return {
            "补扫": 明细,
            "打戳数": sum(len(d.get("打戳", [])) for d in 明细),
            "冻结校验": sum(d.get("冻结校验", 0) for d in 明细),
            "核证": 核,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
