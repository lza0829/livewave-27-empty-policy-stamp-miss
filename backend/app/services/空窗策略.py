"""空窗策略只读接口 + 策略切换（写）。

只读四要素：当前策略、窗键是否存在、关闭态、valid。
两口径下「水位跨越无事件区间后是否存在该窗关闭行」必须可区分且可证：
- 发射零窗：缺口必须有 空窗=1 的已关闭零窗行，否则 invalid；
- 跳过空窗：缺口必须无窗行；任何 空窗=1 的行都是冒充发射，invalid。
历史零窗行带策略快照，切换策略后仍按其出身判 valid，不被暗改。
"""

from app.db import 连接
from app.modules import 空窗发射策略 as 空策
from app.seed import 此刻
from app.services import 时间


def 读策略(conn=None) -> dict:
    自有 = conn is not None
    conn = conn or 连接()
    try:
        原始 = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", (空策.策略键,)).fetchone()
        原始值 = 原始["值"] if 原始 else ""
        规范 = 空策.取策略(conn)
        履历 = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 空窗策略履历 ORDER BY 编号 DESC LIMIT 20"
            )
        ]
        return {
            "键": 空策.策略键,
            "策略": 规范,  
            "站规原值": 原始值,
            "已定": 规范 is not None,
            "合法取值": list(空策.合法策略),
            "履历": 履历,
        }
    finally:
        if not 自有:
            conn.close()


def 查窗键(窗键: str, conn=None) -> dict:
    """只读查单个窗键：存在性、关闭态、空窗标记、策略快照与 valid。"""
    自有 = conn is not None
    conn = conn or 连接()
    try:
        当前策略 = 空策.取策略(conn)
        窗行 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (窗键,)).fetchone()
        房间键, 窗起 = 空策.解析窗键(窗键)
        窗长 = int(
            (conn.execute("SELECT 值 FROM 站规 WHERE 键='窗长秒'").fetchone() or {"值": "60"})["值"]
        )
        水位行 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()
        窗止 = 时间.窗止(窗起, 窗长) if 窗起 else ""
        已越过 = bool(
            窗起 and 水位行 and 时间.解析(水位行["事件时水位"]) >= 时间.解析(窗止)
        )

        if 窗行:
            合法, 依据 = 空策.窗行是否合法(窗行, 当前策略)
            return {
                "窗键": 窗键,
                "策略": 当前策略,
                "窗键存在": True,
                "关闭态": 窗行["状态"],
                "已关闭": 窗行["状态"] == "已关闭",
                "空窗": bool(int(窗行["空窗"])),
                "空窗策略快照": 窗行["空窗策略快照"],
                "窗止已越过": 已越过,
                "valid": 合法,
                "依据": 依据,
            }

        合法, 依据 = (
            空策.缺失窗是否合法(当前策略) if 已越过 else (True, "窗止未越过，尚无行属正常")
        )
        return {
            "窗键": 窗键,
            "策略": 当前策略,
            "窗键存在": False,
            "关闭态": None,
            "已关闭": False,
            "空窗": False,
            "空窗策略快照": "",
            "窗止已越过": 已越过,
            "valid": 合法,
            "依据": 依据,
        }
    finally:
        if not 自有:
            conn.close()


def 全局校验(conn=None) -> dict:
    """扫描所有房的越过窗缺口与全部空窗行，给出全局 valid 结论（关窗扫描完整性证据）。"""
    自有 = conn is not None
    conn = conn or 连接()
    try:
        当前策略 = 空策.取策略(conn)
        窗长 = int(
            (conn.execute("SELECT 值 FROM 站规 WHERE 键='窗长秒'").fetchone() or {"值": "60"})["值"]
        )
        问题 = []

        
        缺口数 = 0
        for 房行 in conn.execute("SELECT 房间键 FROM 直播间"):
            水位行 = conn.execute(
                "SELECT 事件时水位 FROM 水位线 WHERE 房间键=?", (房行["房间键"],)
            ).fetchone()
            if not 水位行:
                continue
            缺口 = 空策.枚举越过窗止的空窗(
                conn, 房行["房间键"], 水位行["事件时水位"], 窗长
            )
            缺口数 += len(缺口)
            合法, 依据 = 空策.缺失窗是否合法(当前策略)
            if 缺口 and not 合法:
                问题.append(f"房{房行['房间键']}有{len(缺口)}个越窗止空窗无行：{依据}")

        
        空窗行 = conn.execute("SELECT * FROM 热度窗 WHERE 空窗=1").fetchall()
        冒充 = []
        历史零窗 = 0
        for 行 in 空窗行:
            合法, 依据 = 空策.窗行是否合法(行, 当前策略)
            if not 合法:
                冒充.append(f"{行['窗键']}（{依据}）")
            elif 当前策略 == 空策.跳过空窗:
                历史零窗 += 1
        if 冒充:
            问题.append("跳过口径下的冒充零窗行：" + "、".join(冒充[:10]))

        return {
            "策略": 当前策略,
            "已定": 当前策略 is not None,
            "空窗行数": len(空窗行),
            "其中历史零窗": 历史零窗,
            "越过无行缺口数": 缺口数,
            "valid": not 问题,
            "问题": 问题,
        }
    finally:
        if not 自有:
            conn.close()


def 切换策略(新策略: str, 来源: str = "站规切换") -> dict:
    """改站规并留履历；只影响此后发射，绝不改写/删除历史零窗行。"""
    if 新策略 not in 空策.合法策略:
        raise ValueError(f"非法空窗策略:{新策略}，合法值{空策.合法策略}")
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        旧 = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", (空策.策略键,)).fetchone()
        旧值 = 旧["值"] if 旧 else ""
        if 旧值 == 新策略:
            conn.rollback()
            return {"已切换": False, "策略": 新策略, "说明": "策略未变"}
        conn.execute(
            "INSERT INTO 站规(键, 值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (空策.策略键, 新策略),
        )
        conn.execute(
            "INSERT INTO 空窗策略履历(策略, 前值, 时刻, 来源) VALUES (?,?,?,?)",
            (新策略, 旧值, 此刻(), 来源),
        )
        conn.commit()
        return {"已切换": True, "策略": 新策略, "前值": 旧值}
    finally:
        conn.close()
