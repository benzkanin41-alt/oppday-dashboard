from __future__ import annotations

import base64
import json
import os
import random
import socket
import ssl
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "work" / "raw" / "tradingview"
RAW.mkdir(parents=True, exist_ok=True)


def tv_packet(message: dict) -> str:
    text = json.dumps(message, separators=(",", ":"))
    return f"~m~{len(text)}~m~{text}"


def parse_packets(raw: str) -> list[dict]:
    out = []
    idx = 0
    while idx < len(raw):
        marker = raw.find("~m~", idx)
        if marker < 0:
            break
        len_start = marker + 3
        len_end = raw.find("~m~", len_start)
        if len_end < 0:
            break
        try:
            size = int(raw[len_start:len_end])
        except ValueError:
            break
        body_start = len_end + 3
        body = raw[body_start:body_start + size]
        idx = body_start + size
        try:
            out.append(json.loads(body))
        except json.JSONDecodeError:
            pass
    return out


class MinimalWebSocket:
    def __init__(self, host: str, path: str):
        raw_sock = socket.create_connection((host, 443), timeout=30)
        self.sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: https://www.tradingview.com\r\n"
            "Referer: https://www.tradingview.com/\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response[:500].decode("utf-8", "replace"))

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_frame(self) -> tuple[int, bytes]:
        first = self._recv_exact(2)
        b1, b2 = first[0], first[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise RuntimeError("socket closed")
            data += chunk
        return data

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def send(ws: MinimalWebSocket, method: str, params: list) -> None:
    ws.send_text(tv_packet({"m": method, "p": params}))


def normalize(series: list[dict]) -> list[dict]:
    rows = []
    for point in series:
        values = point.get("v") or []
        if len(values) < 5:
            continue
        try:
            ts = int(values[0])
            close = float(values[4])
        except Exception:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                "value": round(close, 6),
                "open": round(float(values[1]), 6),
                "high": round(float(values[2]), 6),
                "low": round(float(values[3]), 6),
                "close": round(close, 6),
                "volume": float(values[5]) if len(values) > 5 and values[5] is not None else None,
            }
        )
    rows.sort(key=lambda row: row["date"])
    return rows


def fetch_history(symbol: str, bars: int) -> list[dict]:
    suffix = random.randrange(10_000_000, 99_999_999)
    chart_session = f"cs_{suffix}"
    quote_session = f"qs_{suffix}"
    ws = MinimalWebSocket("data.tradingview.com", "/socket.io/websocket?from=chart%2F&date=2026_07_03-12_00")
    try:
        send(ws, "set_auth_token", ["unauthorized_user_token"])
        send(ws, "chart_create_session", [chart_session, ""])
        send(ws, "quote_create_session", [quote_session])
        send(ws, "quote_set_fields", [quote_session, "ch", "chp", "currency_code", "description", "exchange", "lp", "name", "short_name", "type", "update_mode"])
        send(ws, "quote_add_symbols", [quote_session, symbol, {"flags": ["force_permission"]}])
        send(ws, "quote_fast_symbols", [quote_session, symbol])
        tv_symbol = json.dumps({"symbol": symbol, "adjustment": "splits", "session": "regular"}, separators=(",", ":"))
        send(ws, "resolve_symbol", [chart_session, "sds_sym_1", "=" + tv_symbol])
        send(ws, "create_series", [chart_session, "s1", "s1", "sds_sym_1", "1D", bars])
        started = datetime.now().timestamp()
        while datetime.now().timestamp() - started < 45:
            opcode, payload = ws.recv_frame()
            if opcode == 8:
                raise RuntimeError("TradingView closed websocket")
            if opcode == 9:
                # Ping: enough for this short-lived fetch to ignore; server will keep connection briefly.
                continue
            if opcode != 1:
                continue
            raw = payload.decode("utf-8", "replace")
            if "~h~" in raw:
                ws.send_text(raw)
            for msg in parse_packets(raw):
                if msg.get("m") == "series_error":
                    raise RuntimeError(json.dumps(msg.get("p"), ensure_ascii=False))
                if msg.get("m") == "timescale_update":
                    data = (msg.get("p") or [None, {}])[1]
                    series = (((data or {}).get("s1") or {}).get("s") or [])
                    rows = normalize(series)
                    if len(rows) > 10:
                        return rows
        raise TimeoutError("TradingView data timeout")
    finally:
        ws.close()


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "SET:MAI"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    rows = fetch_history(symbol, bars)
    payload = {
        "source": "TradingView chart websocket",
        "symbol": symbol,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "points": rows,
    }
    path = RAW / f"{symbol.replace(':', '_')}_daily.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "symbol": symbol, "points": len(rows), "first": rows[0]["date"], "last": rows[-1]["date"], "file": str(path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
