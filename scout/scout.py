#!/usr/bin/env python3
"""Lightweight CGI server replacing scout.go. Passes stdin/stdout to CGI scripts."""
import json, os, subprocess, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

CGI_BASE = Path("/home/scout/projects/sandbox/scout/cgi-bin")
PORT = 8080

class CGIMCPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[scout] {fmt % args}\n")

    def _handle_cgi(self):
        tool_path = self.path.partition("?")[0].removeprefix("/cgi-bin/")
        script = CGI_BASE / tool_path
        if not script.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "tool not found"}).encode())
            return
        os.chmod(script, 0o755)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b"{}"
        try:
            r = subprocess.run(
                [str(script)], input=body, capture_output=True, timeout=60,
                env={**os.environ, "REQUEST_METHOD": self.command,
                     "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                     "CONTENT_LENGTH": str(content_len)}
            )
        except subprocess.TimeoutExpired:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "cgi timeout"}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(r.stdout)
        if r.stderr:
            sys.stderr.write(f"[scout stderr] {r.stderr.decode()}\n")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "service": "scout"}).encode())
        elif self.path.startswith("/cgi-bin/"):
            self._handle_cgi()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/cgi-bin/"):
            self._handle_cgi()
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), CGIMCPHandler)
    sys.stderr.write(f"[scout] CGI MCP server on :{PORT}\n")
    server.serve_forever()
