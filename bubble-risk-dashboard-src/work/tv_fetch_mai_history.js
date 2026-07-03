const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "work", "raw", "tradingview");
fs.mkdirSync(OUT, { recursive: true });

function sessionId(prefix) {
  return prefix + "_" + Math.random().toString(36).slice(2, 14);
}

function packet(message) {
  const text = JSON.stringify(message);
  return `~m~${text.length}~m~${text}`;
}

function send(ws, method, params) {
  ws.send(packet({ m: method, p: params }));
}

function parsePackets(raw) {
  const out = [];
  let idx = 0;
  while (idx < raw.length) {
    const marker = raw.indexOf("~m~", idx);
    if (marker === -1) break;
    const lenStart = marker + 3;
    const lenEnd = raw.indexOf("~m~", lenStart);
    if (lenEnd === -1) break;
    const len = Number(raw.slice(lenStart, lenEnd));
    const bodyStart = lenEnd + 3;
    const body = raw.slice(bodyStart, bodyStart + len);
    idx = bodyStart + len;
    if (!body || body === "m~~h~") continue;
    try {
      out.push(JSON.parse(body));
    } catch (_) {}
  }
  return out;
}

function normalizeBars(series) {
  const rows = [];
  for (const point of series || []) {
    const v = point.v || [];
    const ts = Number(v[0]);
    const close = Number(v[4]);
    if (!Number.isFinite(ts) || !Number.isFinite(close)) continue;
    rows.push({
      date: new Date(ts * 1000).toISOString().slice(0, 10),
      value: Number(close.toFixed(6)),
      open: Number(Number(v[1]).toFixed(6)),
      high: Number(Number(v[2]).toFixed(6)),
      low: Number(Number(v[3]).toFixed(6)),
      close: Number(close.toFixed(6)),
      volume: Number.isFinite(Number(v[5])) ? Number(v[5]) : null,
    });
  }
  rows.sort((a, b) => a.date.localeCompare(b.date));
  return rows;
}

async function fetchHistory(symbol, bars = 10000) {
  const chartSession = sessionId("cs");
  const quoteSession = sessionId("qs");
  const url = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F&date=2026_07_03-12_00";
  const ws = new WebSocket(url);
  let settled = false;
  let timeoutHandle;

  return await new Promise((resolve, reject) => {
    timeoutHandle = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { ws.close(); } catch (_) {}
        reject(new Error("TradingView websocket timeout"));
      }
    }, 45000);

    ws.addEventListener("open", () => {
      send(ws, "set_auth_token", ["unauthorized_user_token"]);
      send(ws, "chart_create_session", [chartSession, ""]);
      send(ws, "quote_create_session", [quoteSession]);
      send(ws, "quote_set_fields", [quoteSession, "ch", "chp", "currency_code", "description", "exchange", "lp", "name", "short_name", "type", "update_mode"]);
      send(ws, "quote_add_symbols", [quoteSession, symbol, { flags: ["force_permission"] }]);
      send(ws, "quote_fast_symbols", [quoteSession, symbol]);
      const tvSymbol = JSON.stringify({ symbol, adjustment: "splits", session: "regular" });
      send(ws, "resolve_symbol", [chartSession, "sds_sym_1", "=" + tvSymbol]);
      send(ws, "create_series", [chartSession, "s1", "s1", "sds_sym_1", "1D", bars]);
    });

    ws.addEventListener("message", (event) => {
      const raw = typeof event.data === "string" ? event.data : "";
      if (raw.includes("~h~")) {
        ws.send(raw);
      }
      for (const msg of parsePackets(raw)) {
        if (msg.m === "series_error") {
          if (!settled) {
            settled = true;
            clearTimeout(timeoutHandle);
            try { ws.close(); } catch (_) {}
            reject(new Error(JSON.stringify(msg.p)));
          }
        }
        if (msg.m === "timescale_update") {
          const payload = msg.p && msg.p[1];
          const series = payload && payload.s1 && payload.s1.s;
          const rows = normalizeBars(series);
          if (rows.length > 10 && !settled) {
            settled = true;
            clearTimeout(timeoutHandle);
            try { ws.close(); } catch (_) {}
            resolve(rows);
          }
        }
      }
    });

    ws.addEventListener("error", (event) => {
      if (!settled) {
        settled = true;
        clearTimeout(timeoutHandle);
        reject(new Error("TradingView websocket error"));
      }
    });
  });
}

async function main() {
  const symbol = process.argv[2] || "SET:MAI";
  const bars = Number(process.argv[3] || 10000);
  const rows = await fetchHistory(symbol, bars);
  const payload = {
    source: "TradingView chart websocket",
    symbol,
    fetched_at: new Date().toISOString(),
    points: rows,
  };
  const file = path.join(OUT, `${symbol.replace(/[^A-Za-z0-9_.-]+/g, "_")}_daily.json`);
  fs.writeFileSync(file, JSON.stringify(payload, null, 2), "utf8");
  console.log(JSON.stringify({ status: "ok", symbol, points: rows.length, first: rows[0]?.date, last: rows.at(-1)?.date, file }, null, 2));
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
