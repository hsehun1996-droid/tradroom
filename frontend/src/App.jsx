import React, { useEffect, useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api } from "./api";

const won = (v) => "₩" + Math.round(v).toLocaleString();
const pct = (v) => (v * 100).toFixed(1) + "%";

export default function App() {
  const [regime, setRegime] = useState(null);
  const [sectors, setSectors] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [bt, setBt] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    Promise.all([api.regime(), api.sectors(), api.candidates(20), api.backtest()])
      .then(([r, s, c, b]) => { setRegime(r); setSectors(s); setCandidates(c); setBt(b); })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="app"><div className="loading">⚠️ API 연결 실패: {err}<br/>백엔드를 먼저 실행하세요: <code>uvicorn tradroom.api.main:app</code></div></div>;
  if (!regime) return <div className="app"><div className="loading">불러오는 중…</div></div>;

  return (
    <div className="app">
      <div className="header">
        <h1>tradroom</h1>
        <span className="sub">한국 증시 퀀트 트레이딩 — 의사결정 지원</span>
      </div>
      <p className="tagline">
        위 → 아래로 거른다: 레짐 → 섹터 → 멀티팩터 점수 → 진입 타이밍 → 사이징/손절 → 청산·교체.
        목표는 <b>높은 승률이 아니라 양의 기대값 + 통제된 낙폭</b>.
      </p>

      <div className="grid cols-2">
        <RegimeCard regime={regime} />
        <SectorCard sectors={sectors} />
      </div>

      <div className="section">
        <CandidatesCard candidates={candidates} />
      </div>

      <div className="section">
        <PortfolioCard />
      </div>

      <div className="section">
        {bt && <BacktestCard bt={bt} />}
      </div>

      <p className="disclaimer">
        ⚠️ 이 도구는 점쟁이가 아니라 <b>의사결정 지원</b> 도구입니다. "지금 살만한 종목"은
        확률적으로 유리한 후보일 뿐 보장이 아니며, 최종 판단·주문은 사람이 합니다.
        과거 성과는 미래를 보장하지 않습니다. 기본 데이터는 합성 샘플이며,
        실제 운용 전 라이브 데이터·페이퍼 트레이딩으로 검증하세요.
      </p>
    </div>
  );
}

function RegimeCard({ regime }) {
  const cls = regime.label === "Risk-On" ? "on" : regime.label === "Risk-Off" ? "off" : "neutral";
  const ko = { "Risk-On": "위험 선호", "Neutral": "중립", "Risk-Off": "위험 회피" }[regime.label];
  return (
    <div className="card">
      <h2>🚦 매크로 레짐 <span className="hint">지금 주식을 사도 되는 국면인가</span></h2>
      <div className="regime">
        <div className={`light ${cls}`} />
        <div>
          <div className="label">{regime.label}</div>
          <div className="meta">{ko} · 점수 {regime.score >= 0 ? "+" : ""}{regime.score} · 허용 총노출 {(regime.exposure*100).toFixed(0)}%</div>
          <div className="meta">{regime.allow_new_entry ? "신규 매수 허용" : "신규 매수 중단 (방어)"}</div>
        </div>
      </div>
      <div className="components">
        {Object.entries(regime.components).map(([k, v]) => (
          <span key={k} className={`chip ${v > 0 ? "pos" : v < 0 ? "neg" : ""}`}>
            {label(k)} {v > 0 ? "+1" : v}
          </span>
        ))}
      </div>
    </div>
  );
}
const label = (k) => ({ trend: "추세", volatility: "변동성", fx: "환율", global_risk: "글로벌위험", supply: "수급" }[k] || k);

function SectorCard({ sectors }) {
  const max = Math.max(...sectors.map((s) => s.rs_score), 1);
  return (
    <div className="card">
      <h2>🎯 주도 섹터 (RS 로테이션) <span className="hint">강한 곳에서 더 강한 종목</span></h2>
      <table>
        <thead><tr><th>섹터</th><th className="num">3M</th><th className="num">6M</th><th>RS</th><th></th></tr></thead>
        <tbody>
          {sectors.map((s) => (
            <tr key={s.sector}>
              <td>{s.sector} {s.active && <span className="badge active">활성</span>}</td>
              <td className={"num " + (s.ret_short >= 0 ? "pos" : "neg")}>{pct(s.ret_short)}</td>
              <td className={"num " + (s.ret_long >= 0 ? "pos" : "neg")}>{pct(s.ret_long)}</td>
              <td style={{ width: 90 }}><div className="bar"><span style={{ width: `${(s.rs_score/max)*100}%` }} /></div></td>
              <td className="num">{s.rs_score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidatesCard({ candidates }) {
  return (
    <div className="card">
      <h2>🟢 매수 후보 <span className="hint">게이트 통과 + 종합점수 상위 · BUY NOW / WATCH</span></h2>
      <table>
        <thead><tr>
          <th>판정</th><th>종목</th><th>섹터</th><th className="num">점수</th>
          <th className="num">추세</th><th className="num">상대강도</th><th className="num">퀄리티</th>
          <th className="num">수급</th><th className="num">밸류</th><th>사이징 / 사유</th>
        </tr></thead>
        <tbody>
          {candidates.length === 0 && <tr><td colSpan={10} className="muted">후보 없음 (레짐 방어 또는 게이트 미통과)</td></tr>}
          {candidates.map((c) => (
            <tr key={c.ticker}>
              <td><span className={`badge ${c.timing === "BUY_NOW" ? "buy" : "watch"}`}>{c.timing === "BUY_NOW" ? "BUY" : "WATCH"}</span></td>
              <td>{c.name}<br/><span className="muted">{c.ticker}</span></td>
              <td>{c.sector}</td>
              <td className="num"><b>{c.score.toFixed(0)}</b></td>
              <td className="num">{c.factors.trend}</td>
              <td className="num">{c.factors.relative_strength}</td>
              <td className="num">{c.factors.quality}</td>
              <td className="num">{c.factors.supply}</td>
              <td className="num">{c.factors.valuation}</td>
              <td className="muted">
                {c.plan ? `${c.plan.shares}주 ~${won(c.plan.target_value)} · 손절 ${won(c.plan.stop_price)} (${pct(c.plan.stop_pct)})` : c.timing_reason}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioCard() {
  const [rows, setRows] = useState([{ ticker: "", shares: "", avg_price: "" }]);
  const [equity, setEquity] = useState(100000000);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const update = (i, k, v) => setRows((r) => r.map((row, j) => (j === i ? { ...row, [k]: v } : row)));
  const add = () => setRows((r) => [...r, { ticker: "", shares: "", avg_price: "" }]);

  const run = async () => {
    setBusy(true);
    try {
      const holdings = rows.filter((r) => r.ticker).map((r) => ({
        ticker: r.ticker.trim(), shares: Number(r.shares) || 0, avg_price: Number(r.avg_price) || 0,
      }));
      setResult(await api.portfolio(holdings, Number(equity)));
    } finally { setBusy(false); }
  };

  const icon = { HOLD: "hold", TRIM: "trim", SELL: "sell" };
  const ko = { HOLD: "보유", TRIM: "축소", SELL: "매도" };

  return (
    <div className="card">
      <h2>📊 내 포트폴리오 진단 <span className="hint">보유/축소/매도/교체 — Layer 7</span></h2>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="muted">총자산</span>
        <input type="number" value={equity} onChange={(e) => setEquity(e.target.value)} style={{ width: 160 }} />
      </div>
      <table>
        <thead><tr><th>종목코드</th><th>수량</th><th>평균단가</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input value={r.ticker} placeholder="000105" onChange={(e) => update(i, "ticker", e.target.value)} style={{ width: 110 }} /></td>
              <td><input type="number" value={r.shares} onChange={(e) => update(i, "shares", e.target.value)} style={{ width: 90 }} /></td>
              <td><input type="number" value={r.avg_price} onChange={(e) => update(i, "avg_price", e.target.value)} style={{ width: 110 }} /></td>
              <td></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="ghost" onClick={add}>+ 종목 추가</button>
        <button onClick={run} disabled={busy}>{busy ? "진단 중…" : "진단 실행"}</button>
        <span className="muted">샘플 데이터의 종목코드는 candidates 표를 참고하세요.</span>
      </div>

      {result && (
        <div className="section">
          {result.holdings.length > 0 ? (
            <table>
              <thead><tr><th>판정</th><th>종목</th><th className="num">점수</th><th className="num">손익</th><th>훼손 신호</th></tr></thead>
              <tbody>
                {result.holdings.map((h) => (
                  <tr key={h.ticker}>
                    <td><span className={`badge ${icon[h.action]}`}>{ko[h.action]}</span></td>
                    <td>{h.name} <span className="muted">{h.ticker}</span></td>
                    <td className="num">{h.score.toFixed(0)}</td>
                    <td className={"num " + (h.pnl_pct >= 0 ? "pos" : "neg")}>{h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct}%</td>
                    <td className="muted">{h.triggers.join(", ") || "없음"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted">보유 종목을 입력하고 진단을 실행하세요.</p>}

          {result.rotations.length > 0 && (
            <div className="section">
              <b>🔄 교체 추천</b>
              {result.rotations.map((r, i) => (
                <div className="rotate" key={i}>
                  <b className="neg">{r.sell_name}</b> → <b className="pos">{r.buy_name}</b>
                  <div className="muted">{r.reason}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BacktestCard({ bt }) {
  const m = bt.metrics;
  const data = bt.equity.map((e, i) => ({ date: e.date, equity: e.value, dd: bt.drawdown[i]?.value ?? 0 }));
  return (
    <div className="card">
      <h2>📈 백테스트 <span className="hint">비용·슬리피지·유동성·look-ahead 반영 · ★성패의 90%★</span></h2>
      <div className="metrics-grid" style={{ marginBottom: 16 }}>
        <Metric k="CAGR" v={pct(m.cagr)} good={m.cagr > 0} />
        <Metric k="MDD (최대낙폭)" v={pct(m.mdd)} bad />
        <Metric k="샤프" v={m.sharpe} good={m.sharpe > 1} />
        <Metric k="소르티노" v={m.sortino} good={m.sortino > 1} />
        <Metric k="손익비" v={m.payoff_ratio} good={m.payoff_ratio > 1.5} />
        <Metric k="승률 (참고)" v={m.win_rate != null ? pct(m.win_rate) : "—"} />
        <Metric k="거래수" v={m.n_trades ?? "—"} />
        <Metric k="회전율(/년)" v={m.turnover} />
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ left: 10, right: 10, top: 10 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6c5ce7" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#6c5ce7" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fill: "#8b97ad", fontSize: 11 }} minTickGap={60} />
          <YAxis tick={{ fill: "#8b97ad", fontSize: 11 }} width={70}
                 tickFormatter={(v) => (v / 1e8).toFixed(2) + "억"} domain={["auto", "auto"]} />
          <Tooltip contentStyle={{ background: "#141925", border: "1px solid #232c3d", borderRadius: 8 }}
                   formatter={(v) => won(v)} labelStyle={{ color: "#8b97ad" }} />
          <Area type="monotone" dataKey="equity" stroke="#6c5ce7" fill="url(#eq)" strokeWidth={2} name="자산" />
        </AreaChart>
      </ResponsiveContainer>
      <p className="muted" style={{ marginTop: 4 }}>
        추세추종의 전형: 승률은 낮아도(≈40%) 손익비가 커서 양의 기대값. 안정성은 "안 지는 것"이 아니라 "질 때 적게 지는 것".
      </p>
    </div>
  );
}

function Metric({ k, v, good, bad }) {
  return (
    <div className="metric">
      <div className="k">{k}</div>
      <div className={"v " + (good ? "good" : bad ? "bad" : "")}>{v}</div>
    </div>
  );
}
