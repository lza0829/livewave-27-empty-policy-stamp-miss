"""空窗发射策略：服务层硬约束测试。

覆盖：
1. 默认发射零窗——水位跳跃跨空区间，逐窗物化零赞/零送/零笔数关闭行，扫描不遗漏；
2. 跳过空窗——同样跳跃不出现窗行，水位推进不失败，只读接口判缺口 valid；
3. 两口径对「水位跨越无事件区间后是否存在该窗关闭行」可区分；
4. 失败闭——策略未定/未知名时禁止发射，整批回滚无半截空窗；
5. 并发——多线程同时抬水位/旁路扫描，无重复、无半截，贯验通过；
6. 策略切换不暗改历史零窗（快照冻结出身）；
7. 跳过策略下系统不物化零窗；脏快照零窗行判 invalid；
8. 零窗被允许迟到事件修正后脱离空窗标记，撤回链与贯验仍对齐；
9. 老夹具回归。
"""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

_临时 = tempfile.mkdtemp(prefix="livewave-test-")
os.environ["数据目录"] = _临时
os.environ["夹具目录"] = str(Path(__file__).resolve().parent.parent.parent / "fixtures")

from app.db import 库路径, 连接  
from app.modules import 空窗发射策略 as 空策  
from app.seed import 初始化库, 此刻  
from app.services import 装载, 贯验, 空窗策略  

跳跃夹具 = json.loads(
    (Path(os.environ["夹具目录"]) / "空窗水位跳跃样例.json").read_text(encoding="utf-8")
)
窗键_1200 = "房A|2026-11-22T12:00:00Z"
窗键_1201 = "房A|2026-11-22T12:01:00Z"


def 清库重来():
    for p in Path(_临时).glob("*.db*"):
        p.unlink()
    初始化库()


def 读窗(窗键):
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (窗键,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


class 发射零窗口径(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_水位跳跃逐窗留下零窗关闭行(self):
        报告 = 装载.装一批(跳跃夹具)
        self.assertGreaterEqual(报告["零窗发射"], 2)

        for wk in (窗键_1200, 窗键_1201):
            行 = 读窗(wk)
            self.assertIsNotNone(行, f"{wk} 应有零窗关闭行")
            self.assertEqual(行["状态"], "已关闭")
            self.assertEqual(行["点赞合计"], 0)
            self.assertEqual(行["送礼合计"], 0)
            self.assertEqual(行["事件笔数"], 0)
            self.assertEqual(行["空窗"], 1)
            self.assertEqual(行["空窗策略快照"], 空策.发射零窗)
            self.assertTrue(行["关闭处理时"])

        
        活窗 = 读窗("房A|2026-11-22T12:02:00Z")
        self.assertIsNotNone(活窗)
        self.assertEqual(活窗["状态"], "开启")
        self.assertEqual(活窗["空窗"], 0)
        self.assertEqual(活窗["事件笔数"], 2)

    def test_枚举完整性_跨五窗无一遗漏(self):
        体 = {
            "批次编号": "批-大跳",
            "事件": [
                {
                    "事件编号": "J1", "房间键": "房A", "事件类型": "点赞",
                    "事件时": "2026-11-22T12:05:10Z", "处理时": "2026-11-22T12:05:11Z",
                    "观众键": "观a", "点赞增量": 1, "送礼额": 0,
                }
            ],
        }
        装载.装一批(体)
        conn = 连接()
        try:
            零窗 = conn.execute("SELECT * FROM 热度窗 WHERE 空窗=1 ORDER BY 窗起事件时").fetchall()
            
            self.assertEqual([r["窗键"] for r in 零窗], [
                "房A|2026-11-22T12:00:00Z",
                "房A|2026-11-22T12:01:00Z",
                "房A|2026-11-22T12:02:00Z",
                "房A|2026-11-22T12:03:00Z",
                "房A|2026-11-22T12:04:00Z",
            ])
        finally:
            conn.close()

    def test_只读接口四要素_存在关闭态valid(self):
        装载.装一批(跳跃夹具)
        查 = 空窗策略.查窗键(窗键_1200)
        self.assertEqual(查["策略"], 空策.发射零窗)
        self.assertTrue(查["窗键存在"])
        self.assertTrue(查["已关闭"])
        self.assertEqual(查["关闭态"], "已关闭")
        self.assertTrue(查["空窗"])
        self.assertTrue(查["窗止已越过"])
        self.assertTrue(查["valid"], 查["依据"])

        校 = 空窗策略.全局校验()
        self.assertTrue(校["valid"], 校["问题"])
        self.assertEqual(校["越过无行缺口数"], 0)

    def test_幂等重装不产生重复零窗(self):
        装载.装一批(跳跃夹具)
        装载.装一批(跳跃夹具)  
        conn = 连接()
        try:
            n = conn.execute("SELECT COUNT(*) c FROM 热度窗 WHERE 空窗=1").fetchone()["c"]
            self.assertEqual(n, 2)
        finally:
            conn.close()

    def test_零窗遭迟到修正后脱离空窗标记且贯验对齐(self):
        装载.装一批(跳跃夹具)
        修正 = {
            "批次编号": "批-零窗修正",
            "事件": [
                {
                    "事件编号": "M1", "房间键": "房A", "事件类型": "点赞",
                    
                    "事件时": "2026-11-22T12:00:55Z", "处理时": "2026-11-22T12:02:40Z",
                    "观众键": "观晚", "点赞增量": 4, "送礼额": 0,
                }
            ],
        }
        报告 = 装载.装一批(修正)
        
        self.assertEqual(报告["旁路"], 1)
        行 = 读窗(窗键_1200)
        self.assertEqual(行["空窗"], 1)  
        self.assertEqual(行["事件笔数"], 0)

        
        清库重来()
        装载.装一批({
            "批次编号": "批-浅跳",
            "事件": [{
                "事件编号": "K1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:01:05Z", "处理时": "2026-11-22T12:01:06Z",
                "观众键": "观k", "点赞增量": 2, "送礼额": 0,
            }],
        })
        零行 = 读窗(窗键_1200)
        self.assertEqual(零行["空窗"], 1)
        装载.装一批({
            "批次编号": "批-浅跳修正",
            "事件": [{
                "事件编号": "K2", "房间键": "房A", "事件类型": "送礼",
                
                "事件时": "2026-11-22T12:00:50Z", "处理时": "2026-11-22T12:01:10Z",
                "观众键": "观m", "点赞增量": 0, "送礼额": 8,
            }],
        })
        修后 = 读窗(窗键_1200)
        self.assertEqual(修后["空窗"], 0, "真实事件修正后不再是空窗")
        self.assertEqual(修后["空窗策略快照"], 空策.发射零窗, "出身快照保留")
        self.assertEqual(修后["送礼合计"], 8)
        self.assertEqual(修后["事件笔数"], 1)
        果 = 贯验.跑贯验()
        self.assertTrue(果["是否通过"], 果["问题"])


class 跳过空窗口径(unittest.TestCase):
    def setUp(self):
        清库重来()
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")

    def test_同样跳跃不出现窗行且推进不失败(self):
        报告 = 装载.装一批(跳跃夹具)
        self.assertEqual(报告["零窗发射"], 0)
        self.assertIsNone(读窗(窗键_1200))
        self.assertIsNone(读窗(窗键_1201))
        
        self.assertIsNotNone(读窗("房A|2026-11-22T12:02:00Z"))
        
        conn = 连接()
        try:
            self.assertTrue(
                conn.execute("SELECT 1 FROM 装载批次 WHERE 编号=?", ("批-空窗-01",)).fetchone()
            )
            self.assertEqual(
                conn.execute("SELECT 事件时水位 FROM 水位线 WHERE 房间键='房A'").fetchone()[0],
                "2026-11-22T12:02:45Z",
            )
        finally:
            conn.close()

    def test_只读接口_缺口valid_两口径可区分(self):
        装载.装一批(跳跃夹具)
        查 = 空窗策略.查窗键(窗键_1200)
        self.assertEqual(查["策略"], 空策.跳过空窗)
        self.assertFalse(查["窗键存在"])
        self.assertFalse(查["已关闭"])
        self.assertTrue(查["窗止已越过"])
        self.assertTrue(查["valid"], 查["依据"])
        self.assertIn("跳过空窗", 查["依据"])

        校 = 空窗策略.全局校验()
        self.assertTrue(校["valid"], 校["问题"])
        self.assertEqual(校["空窗行数"], 0)
        self.assertGreaterEqual(校["越过无行缺口数"], 2)

        
        未越 = 空窗策略.查窗键("房A|2026-11-22T12:09:00Z")
        self.assertFalse(未越["窗止已越过"])
        self.assertTrue(未越["valid"])

    def test_系统绝不物化零窗_脏快照行判invalid(self):
        装载.装一批(跳跃夹具)
        conn = 连接()
        try:
            
            conn.execute(
                """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,
                   点赞合计,送礼合计,事件笔数,关闭处理时,版本,空窗,空窗策略快照)
                   VALUES (?,?,?,?,'已关闭',0,0,0,?,1,1,'')""",
                ("房A|2026-11-22T12:07:00Z", "房A",
                 "2026-11-22T12:07:00Z", "2026-11-22T12:08:00Z", 此刻()),
            )
            conn.commit()
        finally:
            conn.close()
        校 = 空窗策略.全局校验()
        self.assertFalse(校["valid"])
        self.assertTrue(any("冒充" in p or "快照非法" in p for p in 校["问题"]))
        果 = 贯验.跑贯验()
        self.assertFalse(果["是否通过"])


class 失败闭(unittest.TestCase):
    def setUp(self):
        清库重来()

    def _抽掉策略(self, 值):
        conn = 连接()
        try:
            conn.execute("UPDATE 站规 SET 值=? WHERE 键=?", (值, 空策.策略键))
            conn.commit()
        finally:
            conn.close()

    def test_策略缺失_禁止发射_整批回滚无半截(self):
        self._抽掉策略("")
        with self.assertRaises(空策.策略未定错误):
            装载.装一批(跳跃夹具)
        conn = 连接()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM 热度窗").fetchone()["c"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM 互动事件").fetchone()["c"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM 装载批次").fetchone()["c"], 0)
            
            self.assertEqual(
                conn.execute("SELECT 事件时水位 FROM 水位线 WHERE 房间键='房A'").fetchone()[0],
                "2026-11-22T12:00:00Z",
            )
        finally:
            conn.close()

    def test_未知名策略值_同样失败闭(self):
        self._抽掉策略("瞎写的策略")
        self.assertIsNone(空策.取策略(连接()))
        with self.assertRaises(空策.策略未定错误):
            装载.装一批(跳跃夹具)

    def test_无缺口时策略未定不连累正常关窗(self):
        
        self._抽掉策略("")
        报告 = 装载.装一批({
            "批次编号": "批-无缺口",
            "事件": [{
                "事件编号": "N1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:00:30Z", "处理时": "2026-11-22T12:00:31Z",
                "观众键": "观n", "点赞增量": 1, "送礼额": 0,
            }, {
                "事件编号": "N2", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:01:05Z", "处理时": "2026-11-22T12:01:06Z",
                "观众键": "观n2", "点赞增量": 1, "送礼额": 0,
            }],
        })
        
        self.assertEqual(报告["零窗发射"], 0)
        self.assertEqual(读窗(窗键_1200)["状态"], "已关闭")


class 并发不半截(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_八线程并发抬水位_零窗不重复不撕裂(self):
        错误 = []

        def  worker(i):
            try:
                装载.装一批({
                    "批次编号": f"批-并发-{i}",
                    "事件": [{
                        "事件编号": f"C{i}", "房间键": "房A", "事件类型": "点赞",
                        "事件时": f"2026-11-22T12:03:0{i}Z",
                        "处理时": f"2026-11-22T12:03:1{i}Z",
                        "观众键": f"观{i}", "点赞增量": 1, "送礼额": 0,
                    }],
                })
            except Exception as e:  
                错误.append(e)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(错误, [])

        conn = 连接()
        try:
            
            self.assertEqual(
                conn.execute("SELECT COUNT(*) c FROM 装载批次").fetchone()["c"], 8
            )
            
            零窗 = [r["窗键"] for r in conn.execute(
                "SELECT 窗键 FROM 热度窗 WHERE 空窗=1 ORDER BY 窗起事件时")]
            self.assertEqual(零窗, [
                "房A|2026-11-22T12:00:00Z",
                "房A|2026-11-22T12:01:00Z",
                "房A|2026-11-22T12:02:00Z",
            ])
            
            活 = conn.execute(
                "SELECT * FROM 热度窗 WHERE 窗键='房A|2026-11-22T12:03:00Z'"
            ).fetchone()
            self.assertEqual(活["事件笔数"], 8)
            self.assertEqual(活["点赞合计"], 8)
        finally:
            conn.close()
        果 = 贯验.跑贯验()
        self.assertTrue(果["是否通过"], 果["问题"])


class 切换与历史零窗(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_切换后历史零窗命运不分叉_履历留痕(self):
        装载.装一批(跳跃夹具)
        历史行 = 读窗(窗键_1200)
        self.assertEqual(历史行["空窗策略快照"], 空策.发射零窗)

        切 = 空窗策略.切换策略(空策.跳过空窗, 来源="测试切换")
        self.assertTrue(切["已切换"])
        self.assertEqual(切["前值"], 空策.发射零窗)

        
        仍在 = 读窗(窗键_1200)
        self.assertEqual(仍在["空窗"], 1)
        self.assertEqual(仍在["空窗策略快照"], 空策.发射零窗)
        self.assertEqual(仍在["点赞合计"], 0)
        self.assertEqual(仍在["事件笔数"], 0)

        查 = 空窗策略.查窗键(窗键_1200)
        self.assertEqual(查["策略"], 空策.跳过空窗)
        self.assertTrue(查["valid"], 查["依据"])
        self.assertIn("历史零窗", 查["依据"])

        校 = 空窗策略.全局校验()
        self.assertTrue(校["valid"], 校["问题"])
        self.assertEqual(校["其中历史零窗"], 2)

        
        空窗策略.切换策略(空策.发射零窗, 来源="测试切回")
        self.assertTrue(空窗策略.查窗键(窗键_1200)["valid"])
        历 = 空窗策略.读策略()["履历"]
        self.assertEqual([r["策略"] for r in 历[:3]], [
            空策.发射零窗, 空策.跳过空窗, 空策.发射零窗,
        ])

    def test_切换只影响此后_新空窗按新口径(self):
        装载.装一批(跳跃夹具)  
        空窗策略.切换策略(空策.跳过空窗, 来源="测试切换")
        装载.装一批({
            "批次编号": "批-跳过期",
            "事件": [{
                "事件编号": "P1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:05:10Z", "处理时": "2026-11-22T12:05:11Z",
                "观众键": "观p", "点赞增量": 1, "送礼额": 0,
            }],
        })
        conn = 连接()
        try:
            
            self.assertIsNone(读窗("房A|2026-11-22T12:03:00Z"))
            self.assertIsNone(读窗("房A|2026-11-22T12:04:00Z"))
            n = conn.execute("SELECT COUNT(*) c FROM 热度窗 WHERE 空窗=1").fetchone()["c"]
            self.assertEqual(n, 2)
        finally:
            conn.close()
        self.assertTrue(空窗策略.全局校验()["valid"])


class 老夹具回归(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_准时迟到旁路三夹具贯验通过(self):
        基 = Path(os.environ["夹具目录"])
        for 名 in ("准时热度样例", "迟到修正样例", "超迟到旁路样例"):
            装载.装一批(json.loads((基 / f"{名}.json").read_text(encoding="utf-8")))
        果 = 贯验.跑贯验()
        self.assertTrue(果["是否通过"], 果["问题"])
        conn = 连接()
        try:
            self.assertGreaterEqual(
                conn.execute("SELECT COUNT(*) c FROM 旁路匣").fetchone()["c"], 1
            )
            self.assertGreaterEqual(
                conn.execute("SELECT COUNT(*) c FROM 撤回单").fetchone()["c"], 1
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
