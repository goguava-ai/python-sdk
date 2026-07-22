import logging
import os
import contextlib

from typing import Literal
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from threading import Thread

logger = logging.getLogger("guava.health")

HealthState = Literal["starting", "live", "stopped"]

class HealthContext:
    def __init__(self):
        self._state: HealthState = "starting"

    def set_state(self, new_state: HealthState):
        self._state = new_state

    def ready(self):
        self.set_state("live")

    def stopped(self):
        self.set_state("stopped")

    def is_live(self) -> bool:
        return self._state == "live"
    
class MultiHealthContext:
    def __init__(self):
        self._ctxs: list[HealthContext] = []

    def create_ctx(self):
        ctx = HealthContext()
        self._ctxs.append(ctx)
        return ctx

    def is_live(self) -> bool:
        return len(self._ctxs) > 0 and all(ctx.is_live() for ctx in self._ctxs)


class HealthServer:
    def __init__(self, health_ctx: HealthContext | MultiHealthContext, host="0.0.0.0", port=4828):
        self._health_ctx = health_ctx
        self._host = host
        self._port = port
        self._server = None
        self._thread = None

    def __enter__(self):
        health_ctx = self._health_ctx

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/live":
                    if health_ctx.is_live():
                        self.send_response(200)
                    else:
                        self.send_response(503)

                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                logger.debug("[health server] " + format, *args)

        self._server = ThreadingHTTPServer(
            (self._host, self._port),
            RequestHandler,
        )
        self._thread = Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        logger.info("Health check server listening on http://%s:%d/live", self._host, self._port)

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        logger.info("Health check server shutting down.")
        assert self._server
        assert self._thread

        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

def get_health_server(health_ctx: HealthContext | MultiHealthContext) -> contextlib.AbstractContextManager[None]:
    if os.getenv("GUAVA_HEALTH_SERVER", "false").lower().strip() in ['yes', 'true', 'on']:
        return HealthServer(health_ctx)
    else:
        return contextlib.nullcontext()