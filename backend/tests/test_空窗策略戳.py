"""空窗策略戳：同票打戳 / 戳冻结区间 / 补扫只校验 / 半截回滚。

架构：**戳冻结区间**——空窗处置成功同票写策略戳；已戳区间禁止再次创建或删除
空窗行，补扫只能校验戳；策略切换与补扫交错也不得暗改历史空窗。

覆盖：
1. 甲：跨过空区间后立刻再补扫——空窗行集合与戳世代均冻结（无新戳、无新行、无删行）；
2. 乙（反证）：未戳区间补扫可补处置并写新戳，已戳窗键始终不重复打戳、世代恒 1；
3. 戳载荷完整：策略码 / 跨越区间 / 窗键清单或跳过证明 / 戳号；
4. 硬约束：禁止戳空；戳=跳过不得物化零窗；戳=发射零窗不得被补扫删行（漂移即 fail-closed）；
5. 失败闭：打戳与处置同票，任一漂移整票回滚；
6. 补扫与抬升抢锁——不得半截凭空插入零窗行；
7. 只读核证接口与水位抬升 / 补扫器 / 热度页 / 对齐核验协同。
"""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

_临时 = tempfile.mkdtemp(prefix="livewave-stamp-test-")
os.environ.setdefault("数据目录", _临时)
os.environ.setdefault("夹具目录", str(Path(__file__).resolve().parent.parent.parent / "fixtures"))

from app.db import 连接, 数据目录 as _库目录
from app.modules import 空窗发射策略 as 空策
from app.modules import 空窗策略戳 as 空戳
from app.seed import 初始化库, 此刻
from app.services import 装载, 贯验, 空窗策略, 空窗补扫, 目录

跳跃夹具 = json.loads(
    (Path(os.environ["夹具目录"]) / "空窗水位跳跃样例.json").read_text(encoding="utf-8")
)
窗键_1200 = "房A|2026-11-22T12:00:00Z"
窗键_1201 = "房A|2026-11-22T12:01:00Z"


def 清库重来():
    for p in Path(_库目录).glob("*.db*"):
        p.unlink()
    初始化库()


def 读窗(窗键):
    conn = 连接()
    try:
        row = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (窗键,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def 读戳():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 空窗策略戳 ORDER BY 编号")]
    finally:
        conn.close()


def 戳窗键集():
    return {wk for t in 读戳() for wk in json.loads(t["窗键清单"])}


class 同票打戳(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_发射零窗_处置成功同票写戳_载荷完整(self):
        装载.装一批(跳跃夹具)
        戳们 = 读戳()
        self.assertEqual(len(戳们), 1, "两个空窗属同一跨越区间应一票一戳")
        戳 = 戳们[0]
        self.assertEqual(戳["策略码"], 空策.发射零窗)
        self.assertEqual(戳["跨越区间"], f"{窗键_1200}~2026-11-22T12:02:00Z")
        self.assertTrue(戳["戳号"])
        self.assertEqual(戳["世代"], 空戳.世代基准)
        self.assertEqual(sorted(json.loads(戳["窗键清单"])), sorted([窗键_1200, 窗键_1201]))
        # 零窗行与戳同票落地
        for wk in (窗键_1200, 窗键_1201):
            self.assertEqual(读窗(wk)["空窗"], 1)

    def test_跳过空窗_以窗键清单为跳过证明打戳(self):
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")
        装载.装一批(跳跃夹具)
        戳们 = 读戳()
        self.assertEqual(len(戳们), 1)
        self.assertEqual(戳们[0]["策略码"], 空策.跳过空窗)
        self.assertEqual(sorted(json.loads(戳们[0]["窗键清单"])), sorted([窗键_1200, 窗键_1201]))
        self.assertIsNone(读窗(窗键_1200), "跳过口径不得物化零窗行")

    def test_无缺口不打戳(self):
        装载.装一批({
            "批次编号": "批-单窗",
            "事件": [{
                "事件编号": "S1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:00:10Z", "处理时": "2026-11-22T12:00:11Z",
                "观众键": "观s", "点赞增量": 1, "送礼额": 0,
            }],
        })
        self.assertEqual(读戳(), [], "无空窗处置不应凭空打戳")


class 甲_戳冻结区间(unittest.TestCase):
    """跨过空区间后立刻再补扫：行集合与戳世代均冻结。"""

    def setUp(self):
        清库重来()

    def test_夹具_跨五窗一次打戳_补扫行集与世代冻结(self):
        夹 = json.loads(
            (Path(os.environ["夹具目录"]) / "空窗补扫冻结样例.json").read_text(encoding="utf-8")
        )
        装载.装一批(夹)
        戳们 = 读戳()
        self.assertEqual(len(戳们), 1, "一次跨越处置应一票一戳")
        戳 = 戳们[0]
        self.assertEqual(戳["跨越区间"], "房A|2026-11-22T12:00:00Z~2026-11-22T12:05:00Z")
        self.assertEqual(len(json.loads(戳["窗键清单"])), 5)
        前行 = {wk: 读窗(wk) for wk in json.loads(戳["窗键清单"])}

        果 = 空窗补扫.补扫()
        self.assertEqual(果["打戳数"], 0)
        self.assertGreaterEqual(果["冻结校验"], 5)
        self.assertEqual(读戳(), 戳们, "戳世代冻结")
        for wk, 行 in 前行.items():
            self.assertEqual(读窗(wk), 行, f"{wk} 行集冻结")

    def test_立刻补扫_不新增不删行_不新增戳_世代不变(self):
        装载.装一批(跳跃夹具)
        前戳 = 读戳()
        前行 = {wk: 读窗(wk) for wk in (窗键_1200, 窗键_1201)}
        果 = 空窗补扫.补扫()
        self.assertEqual(果["打戳数"], 0, "已戳区间补扫不得写新戳")
        self.assertGreaterEqual(果["冻结校验"], 2)
        self.assertEqual(读戳(), 前戳, "戳世代/戳号冻结")
        for wk in (窗键_1200, 窗键_1201):
            self.assertEqual(读窗(wk), 前行[wk], f"{wk} 行集合冻结")

    def test_切换策略后补扫仍冻结_不暗改历史空窗(self):
        装载.装一批(跳跃夹具)  # 发射零窗打戳
        前行 = {wk: 读窗(wk) for wk in (窗键_1200, 窗键_1201)}
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")
        果 = 空窗补扫.补扫()
        self.assertEqual(果["打戳数"], 0)
        for wk in (窗键_1200, 窗键_1201):
            self.assertEqual(读窗(wk), 前行[wk], "切到跳过也不得删历史零窗行")
        self.assertTrue(空窗策略.全局校验()["valid"])

    def test_跳过戳_切到发射零窗后补扫不物化(self):
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")
        装载.装一批(跳跃夹具)
        self.assertIsNone(读窗(窗键_1200))
        空窗策略.切换策略(空策.发射零窗, 来源="测试")
        果 = 空窗补扫.补扫()
        self.assertEqual(果["打戳数"], 0, "已戳跳过区间不得因策略切换被重写")
        self.assertIsNone(读窗(窗键_1200), "戳=跳过不得再物化零窗行")


class 乙_未戳区间可补处置(unittest.TestCase):
    """反证：戳冻结只针对已戳窗键；未戳缺口补扫仍按现行策略新打戳。"""

    def setUp(self):
        清库重来()

    def test_先小跳后大跳_新缺口另打新戳_旧戳不变(self):
        装载.装一批({
            "批次编号": "批-小跳",
            "事件": [{
                "事件编号": "T1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:01:05Z", "处理时": "2026-11-22T12:01:06Z",
                "观众键": "观t", "点赞增量": 1, "送礼额": 0,
            }],
        })
        首戳 = 读戳()
        self.assertEqual(len(首戳), 1)
        self.assertEqual(json.loads(首戳[0]["窗键清单"]), [窗键_1200])

        # 水位继续跳，越过 12:01/12:02/12:03 三个新缺口
        装载.装一批({
            "批次编号": "批-续跳",
            "事件": [{
                "事件编号": "T2", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:04:05Z", "处理时": "2026-11-22T12:04:06Z",
                "观众键": "观t2", "点赞增量": 1, "送礼额": 0,
            }],
        })
        戳们 = 读戳()
        self.assertEqual(len(戳们), 2, "新缺口应另打新戳")
        self.assertEqual(戳们[0], 首戳[0], "旧戳冻结不变")
        新窗键 = set(json.loads(戳们[1]["窗键清单"]))
        self.assertTrue(新窗键.isdisjoint(json.loads(首戳[0]["窗键清单"])))
        self.assertEqual(len(戳窗键集()), 1 + len(新窗键), "戳窗键覆盖应为旧戳一窗 + 新缺口")
        self.assertTrue(空窗策略.全局校验()["valid"])


class 硬约束与漂移(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_禁止戳空(self):
        conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            with self.assertRaises(空戳.空窗策略戳错误):
                空戳.尝试打戳(conn, 房间键="房A", 策略码=空策.发射零窗, 空窗们=[])
            conn.rollback()
        finally:
            conn.close()
        self.assertEqual(读戳(), [])

    def test_零窗行无戳判invalid(self):
        装载.装一批(跳跃夹具)
        conn = 连接()
        try:
            conn.execute("DELETE FROM 空窗策略戳")
            conn.commit()
        finally:
            conn.close()
        校 = 空窗策略.全局校验()
        self.assertFalse(校["valid"])
        self.assertTrue(any("无戳" in p for p in 校["问题"]))
        self.assertFalse(贯验.跑贯验()["是否通过"])

    def test_戳跳过却物化零窗_判invalid_且补扫拒绝(self):
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")
        装载.装一批(跳跃夹具)
        # 人为塞入零窗行到已戳跳过区间
        conn = 连接()
        try:
            conn.execute(
                """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,
                   点赞合计,送礼合计,事件笔数,关闭处理时,版本,空窗,空窗策略快照)
                   VALUES (?,?,?,?,'已关闭',0,0,0,?,1,1,?)""",
                (窗键_1200, "房A", "2026-11-22T12:00:00Z", "2026-11-22T12:01:00Z",
                 此刻(), 空策.发射零窗),
            )
            conn.commit()
        finally:
            conn.close()
        校 = 空窗策略.全局校验()
        self.assertFalse(校["valid"])
        self.assertTrue(any("戳=跳过" in p for p in 校["问题"]))
        with self.assertRaises(空戳.空窗策略戳错误):
            空窗补扫.补扫()

    def test_戳发射零窗却缺行_补扫拒绝且整票回滚(self):
        装载.装一批(跳跃夹具)
        前戳 = 读戳()
        conn = 连接()
        try:
            conn.execute("DELETE FROM 热度窗 WHERE 窗键=?", (窗键_1200,))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(空戳.空窗策略戳错误):
            空窗补扫.补扫()
        self.assertEqual(读戳(), 前戳, "失败整票回滚：不得补写/改戳")
        self.assertIsNone(读窗(窗键_1200), "补扫不得擅自重建被删行（冻结区间只校验）")

    def test_失败闭_策略未定时不落半截戳(self):
        conn = 连接()
        try:
            conn.execute("UPDATE 站规 SET 值='' WHERE 键=?", (空策.策略键,))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(空策.策略未定错误):
            装载.装一批(跳跃夹具)
        self.assertEqual(读戳(), [], "策略未定失败闭不得留半截戳")
        conn = 连接()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM 热度窗").fetchone()[0], 0)
        finally:
            conn.close()


class 补扫与抬升抢锁(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_并发补扫与抬升_不得半截凭空插入零窗(self):
        错误 = []

        def 推(i):
            try:
                装载.装一批({
                    "批次编号": f"批-抢-{i}",
                    "事件": [{
                        "事件编号": f"R{i}", "房间键": "房A", "事件类型": "点赞",
                        "事件时": f"2026-11-22T12:03:0{i}Z",
                        "处理时": f"2026-11-22T12:03:1{i}Z",
                        "观众键": f"观{i}", "点赞增量": 1, "送礼额": 0,
                    }],
                })
            except Exception as e:
                错误.append(e)

        def 扫():
            try:
                空窗补扫.补扫()
            except Exception as e:
                错误.append(e)

        ts = [threading.Thread(target=推, args=(i,)) for i in range(4)]
        ts += [threading.Thread(target=扫) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(错误, [])

        # 每个被越过窗键恰有一条零窗行，且都有戳；无重复、无半截
        conn = 连接()
        try:
            零窗 = [r["窗键"] for r in conn.execute(
                "SELECT 窗键 FROM 热度窗 WHERE 空窗=1 ORDER BY 窗起事件时")]
            self.assertEqual(零窗, [窗键_1200, 窗键_1201, "房A|2026-11-22T12:02:00Z"])
            已戳 = 戳窗键集()
            self.assertEqual(set(零窗), 已戳)
        finally:
            conn.close()
        self.assertTrue(空戳.核证(连接())["valid"])
        self.assertTrue(贯验.跑贯验()["是否通过"])


class 只读核证与协同(unittest.TestCase):
    def setUp(self):
        清库重来()

    def test_核证接口载荷与冻结标志(self):
        装载.装一批(跳跃夹具)
        核 = 空戳.查策略戳(连接())
        self.assertEqual(核["口径"], "戳冻结区间")
        self.assertTrue(核["冻结"])
        self.assertFalse(核["可补扫改写"])
        self.assertTrue(核["核证"]["valid"])
        self.assertEqual(len(核["策略戳"]), 1)
        self.assertEqual(核["策略戳"][0]["策略码"], 空策.发射零窗)

    def test_跳过戳暴露跳过证明(self):
        空窗策略.切换策略(空策.跳过空窗, 来源="测试")
        装载.装一批(跳跃夹具)
        核 = 空戳.查策略戳(连接())
        p = 核["策略戳"][0]["跳过证明"]
        self.assertIsNotNone(p)
        self.assertEqual(p["窗键数"], 2)

    def test_按区间过滤(self):
        装载.装一批(跳跃夹具)
        全部 = 空戳.查策略戳(连接())
        区间 = 全部["策略戳"][0]["跨越区间"]
        筛 = 空戳.查策略戳(连接(), 区间)
        self.assertEqual(len(筛["策略戳"]), 1)
        self.assertEqual(空戳.查策略戳(连接(), "房A|不存在")["策略戳"], [])

    def test_热度页总览暴露戳数(self):
        装载.装一批(跳跃夹具)
        概 = 目录.总览()
        self.assertEqual(概["策略戳数"], 1)
        self.assertTrue(概["策略戳核证"])
        self.assertEqual(概["策略戳覆盖窗键"], 2)

    def test_贯验携带戳核证(self):
        装载.装一批(跳跃夹具)
        果 = 贯验.跑贯验()
        self.assertTrue(果["是否通过"], 果["问题"])
        self.assertIn("策略戳核证", 果)
        self.assertTrue(果["策略戳核证"]["valid"])
        self.assertIn("策略戳=1", 果["说明"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
