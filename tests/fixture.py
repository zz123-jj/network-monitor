"""Integration-only HTTPS endpoint; not included in the deployed service stack."""

import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


server = ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/fixtures/cert.pem", "/fixtures/key.pem")
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
