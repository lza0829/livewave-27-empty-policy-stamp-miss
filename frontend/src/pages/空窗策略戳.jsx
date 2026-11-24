import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 空窗策略戳() {
  const [数据, 设数据] = useState(null);
  const [区间, 设区间] = useState("");
  const [err, 设错] = useState("");
  const 刷 = async () => {
    设错("");
    try {
      const q = 区间.trim() ? `?区间=${encodeURIComponent(区间.trim())}` : "";
      设数据(await 取(`/核证/空窗策略戳${q}`));
    } catch (e) {
      设错(String(e.message || e));
    }
  };
  useEffect(() => { 刷(); }, []);
  const 核 = 数据?.核证;
  return (
    <div>
      <h1 className="题">空窗策略戳核证</h1>
      <p className="述">
        空窗处置成功<strong>同票</strong>写策略戳（策略码 / 跨越区间 / 窗键清单或跳过证明 / 戳号）。
        架构：<strong>{数据?.口径 || "戳冻结区间"}</strong>——已戳区间禁止再次创建或删除空窗行，补扫只能校验戳。
        本页只读，不改写任何行。
      </p>

      <div className="行">
        <input
          className="码"
          style={{ flex: 1, padding: "0.45rem 0.6rem" }}
          value={区间}
          onChange={(e) => 设区间(e.target.value)}
          placeholder="按跨越区间过滤，如 房A|2026-11-22T12:00:00Z~2026-11-22T12:02:00Z"
        />
        <button className="水" onClick={刷}>刷新</button>
      </div>
      {err && <pre className="码">{err}</pre>}

      {核 && (
        <div className="段">
          <div className="段题">核证结论</div>
          <div className="行" style={{ gap: "0.7rem", flexWrap: "wrap" }}>
            <span className={`徽章 ${核.valid ? "通" : "败"}`}>{核.valid ? "对齐" : "撕裂"}</span>
            <span className="讯" style={{ margin: 0 }}>
              戳数 {核.戳数} · 冻结区间 {核.冻结区间数} · 覆盖窗键 {核.窗键覆盖数} ·
              {核.冻结 ? "区间已冻结" : "未冻结"} · {核.可补扫改写 ? "可补扫改写" : "补扫只校验"}
            </span>
          </div>
          {!!核.问题?.length && (
            <ul className="讯">{核.问题.map((p, i) => <li key={i}>{p}</li>)}</ul>
          )}
        </div>
      )}

      <div className="段">
        <div className="段题">策略戳清单</div>
        {!数据?.策略戳?.length ? (
          <div className="空态">暂无策略戳。先推「空窗水位跳跃样例」。</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>编号</th><th>戳号</th><th>策略码</th><th>跨越区间</th>
                <th>窗键清单 / 跳过证明</th><th>世代</th><th>时刻</th>
              </tr>
            </thead>
            <tbody>
              {数据.策略戳.map((t) => (
                <tr key={t.编号}>
                  <td>{t.编号}</td>
                  <td className="码">{t.戳号}</td>
                  <td>{t.策略码}</td>
                  <td className="码">{t.跨越区间}</td>
                  <td className="码">
                    {t.跳过证明
                      ? `跳过证明：${t.跳过证明.窗键数} 键 ${JSON.stringify(t.跳过证明.窗键)}`
                      : JSON.stringify(t.窗键清单)}
                  </td>
                  <td>{t.世代}</td>
                  <td className="码">{t.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
