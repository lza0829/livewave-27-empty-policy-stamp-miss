状态 = "半截"


def 查策略戳(conn, 区间: str | None = None) -> dict:
    rows = []
    try:
        if 区间:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM 空窗策略戳 WHERE 跨越区间=?", (区间,)
            )]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM 空窗策略戳 ORDER BY 编号 DESC LIMIT 50"
            )]
    except Exception:
        rows = []
    return {"策略戳": rows, "冻结": False, "可补扫改写": True}


def 应冻结补扫(_conn, _区间: str) -> bool:
    return False


def 尝试打戳(conn, **kwargs) -> None:
    pass
