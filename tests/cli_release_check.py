#!/usr/bin/env python3
"""Execute the real installer and native CLI against a disposable HTTPS origin.

Usage: python3 tests/cli_release_check.py /absolute/path/to/native/vibestack
This tests release bytes, not a mocked curl or a cross-compiled executable.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


def run(binary: Path) -> None:
    version = json.loads((ROOT / "release-manifest.json").read_text())["version"]
    payload = binary.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert subprocess.check_output([str(binary), "version"], text=True).strip() == version
    with tempfile.TemporaryDirectory(prefix="vibestack-release-check-") as directory:
        root = Path(directory)
        config = root / "openssl.conf"
        config.write_text("[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n"
                          "[dn]\nCN=localhost\n[ext]\nsubjectAltName=IP:127.0.0.1\n"
                          "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,digitalSignature,keyEncipherment\n")
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-days", "1", "-config", str(config), "-keyout", str(key),
                        "-out", str(cert)], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                mode = self.path.split("/")[1]
                if mode in ("redirect", "redirect-loop"):
                    self.send_response(307)
                    target = "http://127.0.0.1/forbidden" if mode == "redirect" else self.path
                    self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if mode == "missing":
                    self.send_error(404)
                    return
                checksum = self.path.endswith(".sha256")
                data = (digest + "  asset\n").encode() if checksum else payload
                if mode == "bad-checksum" and checksum:
                    data = ("0" * 64 + "  asset\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(67108865 if mode == "too-large" else len(data)))
                self.end_headers()
                try:
                    if mode == "interrupted":
                        self.wfile.write(data[:512])
                        self.wfile.flush()
                    elif mode != "too-large":
                        self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        install = root / "bin"
        target = install / "vibestack"
        env = {**os.environ, "CURL_CA_BUNDLE": str(cert), "VIBESTACK_INSTALL_DIR": str(install)}

        def invoke(mode: str, *args: str):
            env["VIBESTACK_RELEASE_BASE"] = f"https://127.0.0.1:{server.server_port}/{mode}"
            return subprocess.run(["sh", str(ROOT / "cli.sh"), *args], env=env,
                                  capture_output=True, text=True, timeout=45)

        try:
            for scenario in ("fresh", "upgrade"):
                if scenario == "upgrade":
                    previous = root / "previous"
                    previous.write_bytes(b"previous-installation")
                    previous.replace(target)
                result = invoke("valid")
                assert result.returncode == 0, result.stderr
                assert target.read_bytes() == payload
                assert subprocess.check_output([str(target), "version"], text=True).strip() == version
                print(f"PASS native {scenario}: real HTTPS installer and CLI {version}")
            for mode in ("bad-checksum", "missing", "redirect", "redirect-loop", "interrupted", "too-large"):
                result = invoke(mode)
                assert result.returncode != 0, mode
                assert target.read_bytes() == payload, f"existing CLI changed: {mode}"
                assert not list(install.glob(".vibestack.*")), f"staged file leaked: {mode}"
                print(f"PASS preserved existing CLI: {mode}")
            for version_arg in ("../escape", "", "1.2", "v"):
                assert invoke("valid", "--version", version_arg).returncode != 0
                assert target.read_bytes() == payload
            target.unlink()
            target.mkdir()
            assert invoke("valid").returncode != 0
            assert not list(target.iterdir()), "installer wrote inside occupied directory"
            print("PASS invalid version and occupied destination")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        raise SystemExit("Provide the absolute path to the native release binary")
    run(Path(sys.argv[1]))
