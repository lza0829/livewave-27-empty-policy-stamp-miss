from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 空窗策略戳 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  策略码 TEXT NOT NULL DEFAULT '',
  跨越区间 TEXT NOT NULL DEFAULT '',
  窗键清单 TEXT NOT NULL DEFAULT '[]',
  戳号 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL DEFAULT '',
  世代 INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_空窗策略戳_区间 ON 空窗策略戳(跨越区间);

CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 直播间 (
  房间键 TEXT PRIMARY KEY,
  标题 TEXT NOT NULL,
  主播 TEXT NOT NULL,
  开播事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '直播中'
);
CREATE TABLE IF NOT EXISTS 互动事件 (
  事件编号 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  事件类型 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  观众键 TEXT NOT NULL DEFAULT '',
  点赞增量 INTEGER NOT NULL DEFAULT 0,
  送礼额 INTEGER NOT NULL DEFAULT 0,
  命运 TEXT NOT NULL DEFAULT '已入流',
  窗键 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 水位线 (
  房间键 TEXT PRIMARY KEY REFERENCES 直播间(房间键),
  事件时水位 TEXT NOT NULL,
  允许迟到秒 INTEGER NOT NULL DEFAULT 30,
  更新处理时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 热度窗 (
  窗键 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  窗起事件时 TEXT NOT NULL,
  窗止事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '开启',
  点赞合计 INTEGER NOT NULL DEFAULT 0,
  送礼合计 INTEGER NOT NULL DEFAULT 0,
  事件笔数 INTEGER NOT NULL DEFAULT 0,
  关闭处理时 TEXT NOT NULL DEFAULT '',
  版本 INTEGER NOT NULL DEFAULT 0,
  空窗 INTEGER NOT NULL DEFAULT 0,
  空窗策略快照 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 撤回单 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  窗键 TEXT NOT NULL,
  房间键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  旧点赞 INTEGER NOT NULL,
  新点赞 INTEGER NOT NULL,
  旧送礼 INTEGER NOT NULL,
  新送礼 INTEGER NOT NULL,
  处理时 TEXT NOT NULL,
  事件编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 旁路匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 窗贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  事件数 INTEGER NOT NULL,
  已关闭窗数 INTEGER NOT NULL,
  撤回数 INTEGER NOT NULL,
  旁路数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 空窗策略履历 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  策略 TEXT NOT NULL,
  前值 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '站规切换'
);
"""


迁移列 = [
    ("热度窗", "空窗", "INTEGER NOT NULL DEFAULT 0"),
    ("热度窗", "空窗策略快照", "TEXT NOT NULL DEFAULT ''"),
    ("空窗策略戳", "世代", "INTEGER NOT NULL DEFAULT 1"),
]


def _迁移(conn) -> None:
    表列缓存: dict[str, set] = {}
    for 表, 列, 声明 in 迁移列:
        if 表 not in 表列缓存:
            表列缓存[表] = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})")}
        if 列 not in 表列缓存[表]:
            conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {声明}")
            表列缓存[表].add(列)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_空窗策略戳_区间 ON 空窗策略戳(跨越区间)"
    )


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
        for k, v in {
            "站名": "播浪",
            "窗长秒": "60",
            "允许迟到秒": "30",
            "水位推进策略": "事件时最大值",
            "关窗条件": "水位>=窗止即关闭发射",
            "旁路条件": "水位>=窗止+允许迟到",
            
            "空窗发射策略": "发射零窗",
            "骨架": "互动事件入流→事件时间水位线推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
        }.items():
            conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))
        conn.execute(
            "INSERT INTO 空窗策略履历(策略, 前值, 时刻, 来源) VALUES (?,?,?,?)",
            ("发射零窗", "", 此刻(), "初始化默认"),
        )
    else:
        
        已有 = conn.execute("SELECT 1 FROM 站规 WHERE 键='空窗发射策略'").fetchone()
        if not 已有:
            conn.execute(
                "INSERT INTO 站规(键, 值) VALUES (?, ?)", ("空窗发射策略", "发射零窗")
            )
            conn.execute(
                "INSERT INTO 空窗策略履历(策略, 前值, 时刻, 来源) VALUES (?,?,?,?)",
                ("发射零窗", "", 此刻(), "老库补默认"),
            )
    if conn.execute("SELECT COUNT(*) AS c FROM 直播间").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO 直播间(房间键, 标题, 主播, 开播事件时, 状态) VALUES (?,?,?,?,?)",
            ("房A", "晚间热聊", "主播小浪", "2026-11-22T12:00:00Z", "直播中"),
        )
        conn.execute(
            "INSERT INTO 水位线(房间键, 事件时水位, 允许迟到秒, 更新处理时) VALUES (?,?,?,?)",
            ("房A", "2026-11-22T12:00:00Z", 30, 此刻()),
        )
    conn.commit()
    conn.close()
