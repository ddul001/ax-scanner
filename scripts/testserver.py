"""Server de test HTTPS pentru fixtures: servește pagina, endpoint-urile simulate (data-sim-path) și un endpoint MCP JSON-RPC minimal."""
from __future__ import annotations

import http.server
import json
import os
import re
import ssl
import subprocess
import threading
from typing import Any

SIM_RE = re.compile(r'<script type="([^"]+)" data-sim-path="([^"]+)"[^>]*>(.*?)</script>', re.S)
CONTENT_TYPES = {
    "text/plain": "text/plain; charset=utf-8",
    "text/markdown": "text/markdown; charset=utf-8",
    "application/xml": "application/xml",
    "application/json": "application/json",
    "application/linkset+json": "application/linkset+json",
}


def load(path: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """(pagina HTML, răspunsurile simulate): blocurile `<script data-sim-path>` devin cale -> (content-type, corp)."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    sims = {p: (CONTENT_TYPES.get(t, t), b.strip("\n")) for t, p, b in SIM_RE.findall(html)}
    return html, sims


def make_handler(page: str, sims: dict[str, tuple[str, str]]) -> type[http.server.BaseHTTPRequestHandler]:
    card = json.loads(sims["/.well-known/agent-card.json"][1]) if "/.well-known/agent-card.json" in sims else None
    declared: list[str] = []
    if card:
        for ext in card["capabilities"]["extensions"]:
            if ext["uri"].startswith("https://autoagentprotocol.org/extensions/aap/"):
                declared = ext["params"]["skills"]["inventory.search"]["capabilities"]["filters"]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def send(self, code: int, content_type: str, body: str) -> None:
            blob = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.end_headers()
            self.wfile.write(blob)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path in sims:
                return self.send(200, *sims[path])
            if path in ("/", "/index.html") or (not path.startswith("/.well-known") and not path.endswith((".txt", ".xml", ".json"))):
                return self.send(200, "text/html; charset=utf-8", page)
            return self.send(404, "text/plain", "not found")

        def do_POST(self) -> None:
            if not self.path.endswith("/mcp"):
                return self.send(405, "text/plain", "forms are not processed by the test server")
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            method, rid = req.get("method"), req.get("id")

            def ok(result: Any) -> None:
                return self.send(200, "application/json", json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}))

            if method == "initialize":
                return ok({"protocolVersion": req.get("params", {}).get("protocolVersion", "2025-11-25"),
                           "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture-mcp", "version": "1"}})
            if method == "server/discover":
                return ok({"supportedVersions": ["2026-07-28", "2025-11-25"],
                           "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture-mcp", "version": "1"}})
            if method == "tools/list":
                return ok(json.loads(sims["mcp:tools/list"][1]))
            if method == "tools/call":
                name = req["params"]["name"]
                args = req["params"].get("arguments", {})
                if name == "aap_lead_submit":
                    return ok({"isError": True, "content": [{"type": "text", "text": "refused by fixture: scanners never submit leads"}]})
                if name == "aap_inventory_search":
                    bad = [k for k in args.get("filters", {}) if k not in declared]
                    if bad and "mcp:error-unsupported-filter" in sims:
                        return ok({"isError": True, "structuredContent": json.loads(sims["mcp:error-unsupported-filter"][1])})
                key = "mcp:" + name
                if key in sims:
                    return ok({"structuredContent": json.loads(sims[key][1])})
                return ok({"isError": True, "content": [{"type": "text", "text": "unknown tool"}]})
            return self.send(200, "application/json", json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}))

    return Handler


def cert(dirp: str) -> tuple[str, str]:
    """Un certificat localhost autofsemnat (creat o dată cu openssl, refolosit după aceea). Întoarce (cert, cheie)."""
    crt, key = os.path.join(dirp, "cert.pem"), os.path.join(dirp, "key.pem")
    os.makedirs(dirp, exist_ok=True)
    if not os.path.exists(crt):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt,
                        "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, capture_output=True)
    return crt, key


def serve(path: str, port: int, dirp: str) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Pornește serverul fixture pe `port`, într-un thread de fundal. Întoarce (server, calea CA)."""
    page, sims = load(path)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(page, sims))
    crt, key = cert(dirp)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(crt, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, crt
