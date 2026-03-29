import json
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from data_manager import DataManager


class StatisticsHandler(SimpleHTTPRequestHandler):
    data_manager: DataManager

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        if path == "/api/dates":
            dates = self.data_manager.get_available_dates()
            self._json_response(dates)
            return

        if path.startswith("/api/data/"):
            date_str = path.split("/")[-1]
            report = self.data_manager.get_report(date_str)
            self._json_response(report)
            return

        super().do_GET()

    def _json_response(self, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_server(dm: DataManager, serve_dir: Path, port: int = 8000) -> threading.Thread:
    StatisticsHandler.data_manager = dm  # type: ignore[assignment]
    handler = partial(StatisticsHandler, directory=str(serve_dir))

    server = HTTPServer(("", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="http-server")
    t.start()
    return t
