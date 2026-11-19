"""Helpers for the end-to-end CI job (same commands on Windows, macOS and Linux).
    python tests/ci.py close <port>                    close the Chrome window debugging on <port>
    python tests/ci.py wait-log <run.log> <n> <secs>   wait until <n> accounts report OK, fail on FALHOU/timeout
    python tests/ci.py events <events.log>             assert the mock app saw the expected logins
    python tests/ci.py shot <port> <png>               screenshot of the window on <port>, plus its title
"""
import base64
import json
import sys
import time
import urllib.request

from websocket import create_connection


def cdp_browser(port):
    v = json.load(urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/version", timeout=5))
    return create_connection(v["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)


cmd = sys.argv[1]
if cmd == "close":
    ws = cdp_browser(sys.argv[2])
    ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
    time.sleep(3)
    print("closed", sys.argv[2])
elif cmd == "wait-log":
    path, n, end = sys.argv[2], int(sys.argv[3]), time.time() + int(sys.argv[4])
    text = ""
    while time.time() < end:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            text = ""
        if text.count("-> OK") >= n or "FALHOU" in text or "Traceback" in text:
            break
        time.sleep(3)
    print(text or "(run.log vazio)")
    sys.exit(0 if text.count("-> OK") >= n and "FALHOU" not in text else 1)
elif cmd == "events":
    ev = open(sys.argv[2], encoding="utf-8").read().split("\n")
    print("\n".join(ev))
    ok = "ENROLLED bia" in ev and ev.count("LOGIN_OK ana") >= 1 and ev.count("LOGIN_OK bia") >= 2
    sys.exit(0 if ok else 1)
elif cmd == "shot":
    page = [p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{int(sys.argv[2])}/json", timeout=5)) if p["type"] == "page"][0]
    ws = create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == 1:
            break
    open(sys.argv[3], "wb").write(base64.b64decode(r["result"]["data"]))
    print(sys.argv[2], "title:", page["title"], "url:", page["url"])
