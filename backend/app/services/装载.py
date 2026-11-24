import json
import sqlite3
import time

from app.db import 连接
from app.modules.空窗发射策略 import 策略未定错误
from app.seed import 此刻
from app.services import 时间, 热度窗


def _关窗(conn, 房间键, 水位, 允许迟到, 窗长, 处理时) -> dict:
    return 热度窗.尝试关窗(conn, 房间键, 水位, 允许迟到, 窗长, 处理时)


def 装一批(体: dict) -> dict:
    """入流一批互动事件：推进水位线，尝试关窗，处理迟到/旁路/撤回。

    口径（类 Flink）：
    - 水位 = 已见最大事件时
    - 窗 [起,止) 在 水位>=止 时关闭发射；无事件空窗按站规「空窗发射策略」处置
    - 关闭后至 水位>=止+允许迟到 仍可迟到修正并发撤回
    - 越过 止+允许迟到 则旁路

    并发：整批一个 IMMEDIATE 事务，写锁冲突短重试；任何异常整体回滚——
    策略未定或锁竞争失败都不得留下半截空窗/半截批次。
    """
    批次编号 = 体.get("批次编号") or f"批-{此刻().replace(':', '').replace('-', '')}"
    事件列表 = 体.get("事件") or []

    末次错 = None
    for 第次 in range(5):
        conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")  
            return _跑一批(conn, 批次编号, 事件列表)
        except 策略未定错误:
            conn.rollback()
            raise  
        except sqlite3.OperationalError as e:
            conn.rollback()
            末次错 = e
            time.sleep(0.05 * (第次 + 1))  
        except Exception:
            conn.rollback()  
            raise
        finally:
            conn.close()
    raise 末次错


def _跑一批(conn, 批次编号: str, 事件列表: list) -> dict:
    报告 = {
        "批次编号": 批次编号,
        "入流": 0,
        "入窗": 0,
        "旁路": 0,
        "撤回": 0,
        "新关窗": 0,
        "零窗发射": 0,
        "策略戳": 0,
        "冻结校验": 0,
        "明细": [],
    }
    站 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    窗长 = int(站.get("窗长秒", "60"))
    默许迟到 = int(站.get("允许迟到秒", "30"))

    def 记账(果: dict):
        报告["新关窗"] += 果["关窗"] + 果["零窗"]
        报告["零窗发射"] += 果["零窗"]
        报告["策略戳"] += len(果.get("打戳", []))
        报告["冻结校验"] += 果.get("冻结校验", 0)

    for ev in 事件列表:
        房间键 = ev["房间键"]
        房 = conn.execute("SELECT * FROM 直播间 WHERE 房间键=?", (房间键,)).fetchone()
        if not 房:
            conn.execute(
                "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                ("未知直播间", json.dumps(ev, ensure_ascii=False), 此刻()),
            )
            报告["旁路"] += 1
            报告["明细"].append({"事件编号": ev.get("事件编号"), "命运": "旁路-未知房"})
            continue

        水位 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()
        if not 水位:
            conn.execute(
                "INSERT INTO 水位线(房间键, 事件时水位, 允许迟到秒, 更新处理时) VALUES (?,?,?,?)",
                (房间键, 房["开播事件时"], 默许迟到, 此刻()),
            )
            水位 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()

        允许迟到 = int(水位["允许迟到秒"])
        事件时 = ev["事件时"]
        处理时 = ev.get("处理时") or 此刻()
        事件编号 = ev["事件编号"]
        点赞 = int(ev.get("点赞增量") or 0)
        送礼 = int(ev.get("送礼额") or 0)
        类型 = ev.get("事件类型") or "点赞"

        if conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号=?", (事件编号,)).fetchone():
            报告["明细"].append({"事件编号": 事件编号, "命运": "幂等跳过"})
            continue

        当前水位 = 水位["事件时水位"]
        if 时间.解析(事件时) > 时间.解析(当前水位):
            当前水位 = 事件时
            conn.execute(
                "UPDATE 水位线 SET 事件时水位=?, 更新处理时=? WHERE 房间键=?",
                (当前水位, 处理时, 房间键),
            )
        
        记账(_关窗(conn, 房间键, 当前水位, 允许迟到, 窗长, 处理时))

        窗起 = 时间.对齐窗起(事件时, 窗长)
        窗止 = 时间.窗止(窗起, 窗长)
        wk = 时间.窗键(房间键, 窗起)

        
        if 热度窗.已过旁路界(当前水位, 窗止, 允许迟到):
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已旁路", "", 批次编号,
                ),
            )
            conn.execute(
                "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                (
                    "超允许迟到",
                    json.dumps(
                        {
                            "事件编号": 事件编号,
                            "事件时": 事件时,
                            "窗止": 窗止,
                            "旁路界": 时间.加秒(窗止, 允许迟到),
                            "水位": 当前水位,
                        },
                        ensure_ascii=False,
                    ),
                    处理时,
                ),
            )
            报告["旁路"] += 1
            报告["明细"].append({"事件编号": 事件编号, "命运": "已旁路", "窗键本应": wk})
            continue

        窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()
        if not 窗:
            conn.execute(
                """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,点赞合计,送礼合计,事件笔数,版本,空窗,空窗策略快照)
                   VALUES (?,?,?,?, '开启', 0, 0, 0, 0, 0, '')""",
                (wk, 房间键, 窗起, 窗止),
            )
            
            记账(_关窗(conn, 房间键, 当前水位, 允许迟到, 窗长, 处理时))
            窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()

        if 窗["状态"] == "已关闭":
            旧赞, 旧送 = 窗["点赞合计"], 窗["送礼合计"]
            新赞, 新送 = 旧赞 + 点赞, 旧送 + 送礼
            新版本 = int(窗["版本"]) + 1
            conn.execute(
                """UPDATE 热度窗 SET 点赞合计=?, 送礼合计=?, 事件笔数=事件笔数+1, 版本=?, 空窗=0 WHERE 窗键=?""",
                (新赞, 新送, 新版本, wk),
            )
            conn.execute(
                """INSERT INTO 撤回单(窗键,房间键,原因,旧点赞,新点赞,旧送礼,新送礼,处理时,事件编号)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (wk, 房间键, "迟到修正", 旧赞, 新赞, 旧送, 新送, 处理时, 事件编号),
            )
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 批次编号,
                ),
            )
            报告["入窗"] += 1
            报告["撤回"] += 1
            报告["入流"] += 1
            报告["明细"].append({"事件编号": 事件编号, "命运": "迟到修正撤回", "窗键": wk})
        else:
            conn.execute(
                """UPDATE 热度窗 SET 点赞合计=点赞合计+?, 送礼合计=送礼合计+?, 事件笔数=事件笔数+1 WHERE 窗键=?""",
                (点赞, 送礼, wk),
            )
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 批次编号,
                ),
            )
            报告["入窗"] += 1
            报告["入流"] += 1
            报告["明细"].append({"事件编号": 事件编号, "命运": "已入窗", "窗键": wk})

    for 房行 in conn.execute("SELECT 房间键, 事件时水位, 允许迟到秒 FROM 水位线"):
        记账(_关窗(
            conn, 房行["房间键"], 房行["事件时水位"], int(房行["允许迟到秒"]), 窗长, 此刻()
        ))

    
    conn.execute(
        """INSERT INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)
           ON CONFLICT(编号) DO UPDATE SET 时刻=excluded.时刻, 报告=excluded.报告""",
        (批次编号, 此刻(), json.dumps(报告, ensure_ascii=False)),
    )
    conn.commit()
    return 报告

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

