from app.modules import 空窗发射策略 as 空策
from app.modules import 空窗策略戳 as 空戳
from app.services import 时间


def 尝试关窗(conn, 房间键: str, 水位事件时: str, 允许迟到秒: int, 窗长秒: int, 处理时: str) -> dict:
    """关窗扫描（唯一入口）：水位越过窗止的每个窗都必须按站规有交代。

    步骤全在同一事务内完成，任一步失败整体回滚，不得半截创建空窗：
    1) 已物化的开启窗，水位>=窗止即关闭发射（允许迟到只影响关闭后能否修正，不推迟关闭）；
    2) 未物化的越过窗（水位跳跃跨过的无事件区间）：
       - **已戳窗键冻结**（架构：戳冻结区间）——只核验戳，绝不再次创建或删除空窗行；
         核验漂移（戳=发射零窗却缺行 / 戳=跳过却有零窗行）即抛错整票回滚；
       - 未戳缺口按全局空窗策略处置，**处置成功同票写策略戳**（策略码+跨越区间+窗键清单+戳号）：
         · 发射零窗：物化零窗关闭行后打戳；
         · 跳过空窗：不建行，以窗键清单为跳过证明打戳；
         · 策略未定：抛 策略未定错误（失败闭，禁止发射）。

    返回 {"关窗": 普通关闭数, "零窗": 空窗发射数, "打戳": 本次新戳号列表, "冻结校验": 已戳窗键数}。
    """
    del 允许迟到秒
    结果 = {"关窗": 0, "零窗": 0, "打戳": [], "冻结校验": 0}
    rows = conn.execute(
        "SELECT * FROM 热度窗 WHERE 房间键=? AND 状态='开启' ORDER BY 窗起事件时",
        (房间键,),
    ).fetchall()
    for 窗 in rows:
        if 时间.解析(水位事件时) >= 时间.解析(窗["窗止事件时"]):
            conn.execute(
                "UPDATE 热度窗 SET 状态='已关闭', 关闭处理时=?, 版本=CASE WHEN 版本=0 THEN 1 ELSE 版本 END WHERE 窗键=?",
                (处理时, 窗["窗键"]),
            )
            结果["关窗"] += 1

    已戳 = 空戳.已戳窗键集(conn, 房间键)
    # 冻结区间只校验：对已戳窗键独立核验（不依赖缺口枚举，零窗行本身已存在而不会入缺口）
    for wk, 戳 in 已戳.items():
        空戳.校验戳对窗(conn, 戳, wk)
        结果["冻结校验"] += 1

    全部缺口 = 空策.枚举越过窗止的空窗(conn, 房间键, 水位事件时, 窗长秒)
    if not 全部缺口:
        return 结果

    缺口 = [空窗 for 空窗 in 全部缺口 if 空窗["窗键"] not in 已戳]
    if not 缺口:
        return 结果  # 越过窗全部已被戳冻结，本次无新处置


    策略 = 空策.取策略(conn)
    if 策略 is None:
        raise 空策.策略未定错误(
            f"房间{房间键}水位{水位事件时}越过{len(缺口)}个无事件窗，但站规「{空策.策略键}」未定或非法，禁止发射"
        )
    if 策略 == 空策.跳过空窗:
        # 跳过：不建行，戳即跳过证明；打戳与判定同票，失败整票回滚。
        戳 = 空戳.尝试打戳(
            conn, 房间键=房间键, 策略码=空策.跳过空窗, 空窗们=缺口, 处理时=处理时
        )
        结果["打戳"].append(戳["戳号"])
        return 结果
    for 空窗 in 缺口:  # 发射零窗：先物化零窗行，再同票打戳
        conn.execute(
            """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,
                                   点赞合计,送礼合计,事件笔数,关闭处理时,版本,空窗,空窗策略快照)
               VALUES (?,?,?,?,'已关闭',0,0,0,?,1,1,?)""",
            (空窗["窗键"], 房间键, 空窗["窗起"], 空窗["窗止"], 处理时, 空策.发射零窗),
        )
        结果["零窗"] += 1
    戳 = 空戳.尝试打戳(
        conn, 房间键=房间键, 策略码=空策.发射零窗, 空窗们=缺口, 处理时=处理时
    )
    结果["打戳"].append(戳["戳号"])
    return 结果



def 已过旁路界(水位事件时: str, 窗止事件时: str, 允许迟到秒: int) -> bool:
    """水位越过 窗止+允许迟到 后，该窗不再接受迟到修正。"""
    旁路界 = 时间.加秒(窗止事件时, 允许迟到秒)
    return 时间.解析(水位事件时) >= 时间.解析(旁路界)

def _alias_payload(payload: dict) -> dict:
    out = dict(payload or {})
    if "窗键" in out and "window_key" not in out:
        out["window_key"] = out.get("窗键")
    if "房间键" in out and "room_key" not in out:
        out["room_key"] = out.get("房间键")
    if "事件编号" in out and "event_id" not in out:
        out["event_id"] = out.get("事件编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows(rows: list) -> list:
    return [_alias_payload(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_27(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "livewave", "nn": "27"}
    if extra:
        data.update(extra)
    return data

