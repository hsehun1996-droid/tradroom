const BASE = "/api";

async function get(path) {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export const api = {
  health: () => get("/health"),
  regime: () => get("/regime"),
  sectors: () => get("/sectors"),
  candidates: (top = 20) => get(`/candidates?top=${top}`),
  backtest: () => get("/backtest"),
  portfolio: async (holdings, totalEquity) => {
    const r = await fetch(`${BASE}/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings, total_equity: totalEquity }),
    });
    if (!r.ok) throw new Error(`portfolio ${r.status}`);
    return r.json();
  },
};
