"""Stdlib-only CDP WebSocket client for Obsidian eval (fallback when obsidian-cli hangs).

Requires Obsidian running with --remote-debugging-port (Kenan's machine: 9223).
Usage from execute_code:

    import sys; sys.path.insert(0, <this skill's scripts dir>)
    from cdp_eval import connect, eval_js
    s = connect()                      # first app://obsidian.md page target
    eval_js(s, "app.plugins.plugins['<id>'].manifest.version")

eval_js returns the JSON value directly. For async app ops, prefer fire-then-poll:
    eval_js(s, "app.plugins.disablePlugin('<id>')")   # returns promise, ignore
    time.sleep(1); eval_js(s, "!!app.plugins.plugins['<id>']")
(awaitPromise=True is flaky: 'Promise was collected'.)
"""
import base64, json, os, socket, struct, time, urllib.request


def _http_json(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def obsidian_page(port=9223):
    """Return the first page target whose URL is the Obsidian app."""
    for p in _http_json(f"http://127.0.0.1:{port}/json/list"):
        if p.get("type") == "page" and p.get("url", "").startswith("app://obsidian.md"):
            return p
    # Fallback: any page titled Obsidian
    for p in _http_json(f"http://127.0.0.1:{port}/json/list"):
        if p.get("type") == "page" and "Obsid" in p.get("title", ""):
            return p
    raise RuntimeError("no Obsidian page target")


class CDPSession:
    """Request/response CDP over a raw WebSocket. Event frames are skipped."""

    def __init__(self, ws_url):
        rest = ws_url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake EOF")
            resp += chunk
        if "101" not in resp.split(b"\r\n", 1)[0].decode():
            raise RuntimeError(f"handshake failed: {resp[:120]!r}")
        self._buf = b""
        self._id = 0

    def _send_frame(self, payload: bytes):
        header = bytearray([0x81])
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126); header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127); header += struct.pack(">Q", n)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket EOF")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_frame(self):
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            (n,) = struct.unpack(">H", self._recv_exact(2))
        elif n == 127:
            (n,) = struct.unpack(">Q", self._recv_exact(8))
        return opcode, self._recv_exact(n)

    def send(self, method, params=None):
        self._id += 1
        mid = self._id
        self._send_frame(json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise RuntimeError("connection closed")
            if opcode in (0x1, 0x2):
                data = json.loads(payload.decode())
                if data.get("id") == mid:
                    if "error" in data:
                        raise RuntimeError(f"CDP error: {data['error']}")
                    return data.get("result", {})


def connect(port=9223):
    return CDPSession(obsidian_page(port)["webSocketDebuggerUrl"])


def eval_js(session, expression, timeout_s=10):
    """Evaluate JS in the Obsidian renderer; return the by-value result."""
    r = session.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    if r.get("exceptionDetails"):
        ed = r["exceptionDetails"]
        raise RuntimeError(f"JS error: {ed.get('exception', {}).get('description') or ed.get('text')}")
    return r.get("result", {}).get("value")


def click(session, x, y, button="left"):
    """Synthetic click through the browser input pipeline (isTrusted path)."""
    for typ in ("mousePressed", "mouseReleased"):
        session.send("Input.dispatchMouseEvent", {"type": typ, "x": x, "y": y, "button": button, "clickCount": 1})
