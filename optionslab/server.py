"""Local-only HTTP UI; no cloud upload, credentials, orders or external feeds."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

from . import __version__
from .portfolio import Portfolio, analyze, infer_leg_iv
from .strategies import build_template, default_portfolio, template_list

STATIC = Path(__file__).parent / "static"
MAX_BODY = 512 * 1024
CALCULATION_LOCK = threading.BoundedSemaphore(2)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "OptionsLab/" + __version__

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, json_bytes({"error": message}))

    def _valid_host(self) -> bool:
        # Prevent DNS-rebinding access to a user's loopback application.
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def do_GET(self) -> None:
        if not self._valid_host():
            self._error(403, "Solo se admite acceso local.")
            return
        route = urlsplit(self.path).path
        if route == "/api/health":
            self._send(200, json_bytes({"status": "ok", "version": __version__}))
        elif route == "/api/demo":
            self._send(200, json_bytes(default_portfolio()))
        elif route == "/api/templates":
            self._send(200, json_bytes(template_list()))
        elif route in {"/", "/index.html", "/app.js", "/style.css"}:
            filename = "index.html" if route == "/" else route[1:]
            content_type = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[filename]
            try:
                self._send(200, (STATIC / filename).read_bytes(), content_type)
            except FileNotFoundError:
                self._error(404, "Recurso de interfaz no instalado.")
        elif route == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._error(404, "Ruta no encontrada.")

    def do_POST(self) -> None:
        if not self._valid_host():
            self._error(403, "Solo se admite acceso local.")
            return
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self._error(403, "Origen externo no permitido.")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._error(415, "Se requiere Content-Type: application/json.")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "Content-Length no válido.")
            return
        if length <= 0 or length > MAX_BODY:
            self._error(413, "JSON vacío o demasiado grande (máximo 512 KiB).")
            return
        if not CALCULATION_LOCK.acquire(blocking=False):
            self._error(429, "Hay dos cálculos en curso; espera a que termine uno.")
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("JSON no admite NaN/Infinity.")))
            if not isinstance(data, dict):
                raise ValueError("El cuerpo JSON debe ser un objeto.")
            route = urlsplit(self.path).path
            if route == "/api/analyze":
                result = analyze(data.get("portfolio"), data.get("scenario"))
            elif route == "/api/validate":
                result = Portfolio.from_dict(data.get("portfolio")).to_dict()
            elif route == "/api/template":
                result = build_template(data.get("id"), data.get("portfolio"))
            elif route == "/api/iv":
                result = infer_leg_iv(data.get("portfolio"), data.get("leg_id"))
            else:
                self._error(404, "Ruta no encontrada.")
                return
            self._send(200, json_bytes(result))
        except (ValueError, TypeError, UnicodeDecodeError, KeyError) as exc:
            self._error(422, str(exc))
        except (ArithmeticError, OverflowError) as exc:
            self._error(422, f"No se pudo obtener una solución numérica válida: {exc}")
        except Exception:
            # Do not leak local paths, stack frames or arbitrary request data.
            self._error(500, "Error interno de cálculo. Revisa los datos y consulta la consola local.")
            raise
        finally:
            CALCULATION_LOCK.release()


def create_server(port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(port: int = 8765, open_browser: bool = True) -> None:
    with create_server(port) as server:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        print(f"OptionsLab {__version__} · {url} · Ctrl+C para salir.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
