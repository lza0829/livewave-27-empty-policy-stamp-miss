import React, { useEffect, useState } from "react";
import { 取, 递 } from "../api.js";

export default function 空窗策略页() {
  const [策, 设策] = useState(null);
  const [校, 设校] = useState(null);
  const [窗键入, 设窗键入] = useState("房A|2026-11-22T12:00:00Z");
  const [查果, 设查果] = useState(null);
  const [讯, 设讯] = useState("");

  const 刷 = async () => {
    设策(await 取("/空窗策略"));
    设校(await 取("/空窗策略/校验"));
  };
  useEffect(() => { 刷(); }, []);

  const 切 = async (策略) => {
    设讯("");
    const r = await 递("/空窗策略/切换", { 策略 });
    设讯(r.已切换 ? `已切换：${r.前值 || "（空）"} → ${r.策略}（只影响此后发射，历史零窗不暗改）` : r.说明);
    await 刷();
  };

  const 查 = async () => {
    const k = encodeURIComponent(窗键入.trim());
    设查果(await 取(`/空窗策略/窗键?窗键=${k}`));
  };

  if (!策) return <p className="讯">加载中…</p>;
  return (
    <div>
      <h1 className="题">空窗发射策略</h1>
      <p className="述">
        水位越过某窗窗止而该窗无事件时，按全局唯一策略处理。两种口径对「是否存在该窗关闭行」可区分：
        <strong>发射零窗</strong>——无事件也关闭并留零赞/零送/零笔数发射行（空窗=1，带策略快照）；
        <strong>跳过空窗</strong>——不创建窗行，水位推进不失败，且严禁物化零窗行冒充发射。
      </p>

      <div className="段">
        <div className="段题">当前全局策略（只读）</div>
        <div className="行" style={{ gap: "0.7rem", alignItems: "center" }}>
          <span className={`徽章 ${策.已定 ? "通" : "败"}`}>
            {策.策略 || "策略未定（失败闭：禁止发射）"}
          </span>
          <span className="讯" style={{ margin: 0 }}>站规原值：{策.站规原值 || "（空）"}</span>
        </div>
        <div className="行">
          {策.合法取值.map((v) => (
            <button
              key={v}
              className={`次 ${策.策略 === v ? "亮片" : ""}`}
              onClick={() => 切(v)}
            >
              切换为{v}
            </button>
          ))}
          <button className="次" onClick={刷}>刷新</button>
        </div>
        {讯 && <div className="提示条">{讯}</div>}
      </div>

      <div className="段">
        <div className="段题">只读查窗键：存在性 / 关闭态 / valid</div>
        <div className="行">
          <input
            className="码"
            style={{ flex: 1, padding: "0.45rem 0.6rem" }}
            value={窗键入}
            onChange={(e) => 设窗键入(e.target.value)}
            placeholder="房间键|窗起事件时，如 房A|2026-11-22T12:00:00Z"
          />
          <button className="水" onClick={查}>查窗键</button>
        </div>
        {查果 && (
          <table>
            <tbody>
              <tr><td>当前策略</td><td className="码">{查果.策略 || "未定"}</td></tr>
              <tr><td>窗键存在</td><td>{查果.窗键存在 ? "是" : "否（无窗行）"}</td></tr>
              <tr><td>关闭态</td><td>{查果.关闭态 ?? "—"}（已关闭：{查果.已关闭 ? "是" : "否"}）</td></tr>
              <tr><td>空窗行</td><td>{查果.空窗 ? `是，快照=${查果.空窗策略快照}` : "否"}</td></tr>
              <tr><td>窗止已被水位越过</td><td>{查果.窗止已越过 ? "是" : "否"}</td></tr>
              <tr>
                <td>valid</td>
                <td><span className={`徽章 ${查果.valid ? "通" : "败"}`}>{查果.valid ? "合法" : "撕裂"}</span></td>
              </tr>
              <tr><td>依据</td><td className="讯">{查果.依据}</td></tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <div className="段题">全局完整性校验（关窗扫描可证）</div>
        {校 && (
          <>
            <div className="行" style={{ gap: "0.7rem" }}>
              <span className={`徽章 ${校.valid ? "通" : "败"}`}>{校.valid ? "对齐" : "撕裂"}</span>
              <span className="讯" style={{ margin: 0 }}>
                空窗行 {校.空窗行数}（其中切换前历史零窗 {校.其中历史零窗}）· 越过无行缺口 {校.越过无行缺口数}
              </span>
            </div>
            {!!校.问题.length && (
              <ul className="讯">{校.问题.map((p, i) => <li key={i}>{p}</li>)}</ul>
            )}
          </>
        )}
      </div>

      <div className="段">
        <div className="段题">策略切换履历</div>
        {!策.履历.length ? (
          <div className="空态">无履历</div>
        ) : (
          <table>
            <thead><tr><th>编号</th><th>时刻</th><th>切后策略</th><th>前值</th><th>来源</th></tr></thead>
            <tbody>
              {策.履历.map((r) => (
                <tr key={r.编号}>
                  <td>{r.编号}</td><td className="码">{r.时刻}</td>
                  <td>{r.策略}</td><td className="码">{r.前值 || "—"}</td><td>{r.来源}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
