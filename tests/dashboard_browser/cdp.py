"""A tiny Chrome DevTools driver (standard library only): start a headless Chrome with a throw-away profile, open a page,
evaluate JavaScript, wait for a page condition. No node, no selenium, no network (pages are local files).

    ch = Chrome()                 # raises ChromeMissing when Chrome is not installed
    ch.goto("file:///tmp/page.html")
    ch.wait_for("document.readyState === 'complete'", 10)
    ch.js("document.title")
    ch.close()
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


class ChromeMissing(RuntimeError):
    pass


def find_chrome() -> str | None:
    if os.environ.get("DP_NO_CHROME"):                       # lets the "Chrome is missing" path be tried on a machine that has it
        return None
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


class WS:
    def __init__(self, url):
        assert url.startswith("ws://")
        hp, path = url[5:].split("/", 1)
        host, port = hp.split(":")
        self.s = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hp}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, text):
        d = text.encode()
        n = len(d)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(d)))

    def _read(self, n):
        while len(self.buf) < n:
            c = self.s.recv(1 << 20)
            if not c:
                raise EOFError
            self.buf += c
        r, self.buf = self.buf[:n], self.buf[n:]
        return r

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._read(2)
            op = b1 & 0xF
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            p = self._read(n)
            if op in (1, 0, 2):
                msg += p
            if b1 & 0x80 and op in (1, 0, 2):
                return msg.decode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chrome:
    """One headless Chrome with its own temporary profile and a free debugging port."""

    def __init__(self, port: int | None = None, width: int = 1400, height: int = 900):
        exe = find_chrome()
        if not exe:
            raise ChromeMissing("Google Chrome was not found (set CHROME_BIN to its path)")
        self.port = port or free_port()
        self.ud = tempfile.mkdtemp(prefix="dp-chrome-")
        self.p = subprocess.Popen([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.ud}",
                                   "--no-first-run", "--no-default-browser-check", "--allow-file-access-from-files", *(["--no-sandbox"] if os.environ.get("CI") else []), f"--window-size={width},{height}", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=2).read()
                break
            except Exception:
                time.sleep(.1)
        else:
            self.close()
            raise RuntimeError("Chrome did not open its debugging port")
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
        t = [t for t in tabs if t["type"] == "page"][0]
        self.ws = WS(t["webSocketDebuggerUrl"])
        self.id = 0
        self.events = []
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")

    def cmd(self, method, **params):
        self.id += 1
        i = self.id
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == i:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})
            self.events.append(m)

    def pump(self, seconds: float = 0.0):
        """Read pending events (the socket has a long timeout, so only call this when something is expected or after a short sleep)."""
        end = time.time() + seconds
        self.ws.s.settimeout(0.05)
        try:
            while True:
                try:
                    self.events.append(json.loads(self.ws.recv()))
                except (socket.timeout, TimeoutError):
                    if time.time() >= end:
                        break
        finally:
            self.ws.s.settimeout(60)

    def goto(self, url: str, timeout: float = 60):
        if getattr(self, "_url", None) and self._url.split("#")[0] == url.split("#")[0] and url != "about:blank":
            self.goto("about:blank", timeout)                       # a change of the fragment alone is not a page load: leave the page first
        self._url = url
        self.events.clear()
        self.cmd("Page.navigate", url=url)
        end = time.time() + timeout
        while time.time() < end:
            if any(e.get("method") == "Page.loadEventFired" for e in self.events):
                return
            self.pump(0.1)
        raise TimeoutError(f"page did not load: {url}")

    def js(self, expr: str):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            return {"__error": json.dumps(r["exceptionDetails"])[:600]}
        return r["result"].get("value")

    def wait_for(self, expr: str, timeout: float = 20, every: float = 0.1) -> bool:
        """Poll a JavaScript expression until it is truthy; False on timeout (never an unbounded wait)."""
        end = time.time() + timeout
        while time.time() < end:
            v = self.js(expr)
            if v and not (isinstance(v, dict) and "__error" in v):
                return True
            time.sleep(every)
        return False

    def console_errors(self) -> list:
        """Uncaught exceptions and console.error calls since the last goto()."""
        self.pump(0.05)
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown":
                d = e["params"]["exceptionDetails"]
                out.append("exception: " + ((d.get("exception") or {}).get("description") or d.get("text", ""))[:300])
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] == "error":
                out.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:300])
        return out

    def shot(self, path: str, full: bool = False):
        r = self.cmd("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def viewport(self, w: int, h: int, mobile: bool = False, scale: int = 1):
        self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale, mobile=mobile)

    def close(self):
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass
        shutil.rmtree(self.ud, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
