#!/usr/bin/env python3
"""Open one incognito Chrome window per test account of a web app, already logged in (password + 2FA).

    python launcher.py setup             create or extend config.json (login URL + test accounts)
    python launcher.py open              open and log in one window per account (the desktop shortcut runs this)
    python launcher.py enroll <account>  turn on 2FA for an account that has none yet, saving its key
    python launcher.py page              write and open contas.html: logins, passwords and live 2FA codes
    python launcher.py shortcut          create the desktop shortcuts (Windows, macOS, Linux)

Every command takes --config <file> (default: config.json next to this script). One config per environment.
Passwords and 2FA keys live only in that file; nothing secret is ever printed.
"""
import argparse
import base64
import binascii
import getpass
import hashlib
import hmac
import html
import json
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import time
import unicodedata
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

try:
    from websocket import create_connection
except ImportError:  # setup/page work without it; open/enroll explain how to install it
    create_connection = None

HERE = os.path.dirname(os.path.abspath(__file__))
LOGIN_BUTTONS = ["Entrar", "Acessar", "Sign in", "Log in", "Login"]
CONFIRM_BUTTONS = ["Confirmar", "Verificar", "Continuar", "Enviar", "Confirm", "Verify", "Continue", "Submit"]
WIZARD_BUTTONS = ["Ok, vamos lá", "Próximo", "Concluir", "Ok, let's go", "Next", "Finish", "Done"]
KEY_RE = re.compile(r"(?m)^\s*([A-Z2-7]{4}(?:\s?[A-Z2-7]{4}){3,})\s*$")  # 2FA key as shown on the enrollment screen
RECOVERY_RE = re.compile(r"(?m)^\s*([a-z0-9]{4}(?:-[a-z0-9]{4}){3})\s*$")
INVALID_RE = re.compile(r"inválid|invalid", re.I)


# ---------- config ----------

def load(path):
    if not os.path.exists(path):
        sys.exit(f"Configuração não encontrada: {path}\nRode primeiro: python launcher.py setup")
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    c.setdefault("base_port", 9341)
    c.setdefault("accounts", [])
    if not c.get("login_url"):
        sys.exit(f"Falta \"login_url\" em {path}. Rode: python launcher.py setup")
    return c


def save(path, c):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def normalize_url(url):
    url = url.strip()
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if not parts.hostname or not (parts.scheme == "https" or (parts.scheme == "http" and local)):
        raise ValueError("use o endereço completo, começando com https:// (http:// só para localhost)")
    if parts.path in ("", "/"):  # "logged in" means leaving this path, so the root cannot be it
        raise ValueError("use o endereço da página de login em si (ex.: https://app.suaempresa.com/login)")
    return url


def normalize_key(key):
    key = key.replace(" ", "").upper()
    base64.b32decode(key + "=" * (-len(key) % 8))  # raises binascii.Error if it is not a 2FA key
    return key


def label(acc):
    return acc.get("label") or acc["login"]


def profiles_dir(cfg):
    return os.path.join(os.path.dirname(os.path.abspath(cfg)), "profiles")


# ---------- 2FA ----------

def totp(secret, at=None):
    """RFC 6238 code (SHA-1, 6 digits, 30 s): what authenticator apps show."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() if at is None else at) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def fresh_totp(secret):
    left = 30 - int(time.time()) % 30
    if left < 8:  # too close to expiring: wait for the next code
        time.sleep(left + 1)
    return totp(secret)


# ---------- Chrome over CDP ----------

def find_chrome(c):
    if c.get("chrome"):
        return c["chrome"]
    env = os.path.expandvars
    mac = "Google Chrome.app/Contents/MacOS/Google Chrome"
    for p in (env(r"%ProgramW6432%\Google\Chrome\Application\chrome.exe"),  # 64-bit Program Files even from 32-bit Python
              env(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
              env(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
              env(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
              "/Applications/" + mac, os.path.expanduser("~/Applications/" + mac)):
        if os.path.isfile(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):  # Linux
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("Chrome não encontrado. Coloque o caminho do Chrome em \"chrome\" no config.json.")


# Local CDP endpoint: scheme and host are fixed, only the integer port varies.
def alive(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/version", timeout=2)  # nosemgrep: dynamic-urllib-use-detected
        return True
    except OSError:
        return False


def pages(port):
    return [p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json", timeout=3))  # nosemgrep: dynamic-urllib-use-detected
            if p["type"] == "page" and not p["url"].startswith(("chrome", "devtools"))]


def launch(chrome, cfg, i, port, url):
    # No --remote-allow-origins: our client sends no Origin header, so web pages cannot drive these windows.
    # Own session on macOS/Linux so closing the terminal that ran this does not close the windows.
    subprocess.Popen([chrome, "--incognito", f"--user-data-dir={os.path.join(profiles_dir(cfg), f'p{i}')}",
                      f"--remote-debugging-port={port}", f"--window-position={60 + i * 80},{40 + i * 60}",
                      "--window-size=1400,900", "--no-first-run", "--no-default-browser-check", url],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")


class Tab:
    def __init__(self, port, host):
        if create_connection is None:
            sys.exit("Falta a biblioteca websocket-client. Rode o instalador (ou: pip install -r requirements.txt).")
        target = None
        for k in range(30):  # a fresh window first shows about:blank; wait for the app's page
            try:
                ps = pages(port)
                mine = [p for p in ps if urlsplit(p["url"]).hostname == host]
                target = (mine or ps or [None])[0]
                if mine or (target and k >= 15):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        if not target:
            raise RuntimeError(f"nenhuma aba aberta na porta {port}")
        self.ws = create_connection(target["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self.n = 0

    def cdp(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.n:
                return r.get("result", r)

    def ev(self, js):
        return self.cdp("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True).get("result", {}).get("value")

    def close(self):
        self.ws.close()


# Login forms and 2FA boxes may render inside shadow DOM: walk every shadow root.
DEEP = "(()=>{const o=[];const w=r=>r.querySelectorAll('*').forEach(e=>{o.push(e);if(e.shadowRoot)w(e.shadowRoot)});w(document);return o})()"
VISIBLE_INPUTS = f"{DEEP}.filter(e=>e.tagName==='INPUT'&&e.getBoundingClientRect().width>0)"
TEXT_INPUTS = f"{VISIBLE_INPUTS}.filter(e=>e.type!=='password')"
INPUT_TYPES = f"{VISIBLE_INPUTS}.map(e=>e.type)"
CLEAR = (f"(()=>{{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
         f"{VISIBLE_INPUTS}.forEach(e=>{{if(e.value){{s.call(e,'');e.dispatchEvent(new Event('input',{{bubbles:true,composed:true}}))}}}});return 1}})()")
PAGE_TEXT = ("(()=>{const o=[];const w=r=>{const it=document.createTreeWalker(r,NodeFilter.SHOW_TEXT);let n;"
             "while(n=it.nextNode()){const p=n.parentElement,t=n.textContent.trim();"  # visible text only, never inline script source
             "if(t&&p&&!/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(p.tagName)&&p.getClientRects().length)o.push(t)}"
             "r.querySelectorAll('*').forEach(e=>{if(e.shadowRoot)w(e.shadowRoot)})};w(document.body);return o.join('\\n')})()")
CLICK = ("((labels)=>{const b=%s.find(e=>(e.tagName==='BUTTON'||e.tagName==='A'||e.getAttribute('role')==='button')"
         "&&e.getBoundingClientRect().width>0&&labels.includes((e.innerText||e.textContent||'').replace(/\\s+/g,' ').trim()));"
         "if(b){b.click();return true}return false})(%s)")
PIN_TITLE = """((n)=>{if(window.__pin===n&&document.title===n)return 'ok';window.__pin=n;
const d=Object.getOwnPropertyDescriptor(Document.prototype,'title');
Object.defineProperty(document,'title',{configurable:true,get(){return d.get.call(document)},set(v){d.set.call(document,window.__pin)}});
d.set.call(document,n);
if(!window.__pinObs){window.__pinObs=new MutationObserver(()=>{if(d.get.call(document)!==window.__pin)d.set.call(document,window.__pin)});
window.__pinObs.observe(document.head,{subtree:true,childList:true,characterData:true})}return 'set'})(%s)"""


def click(t, labels):
    return t.ev(CLICK % (DEEP, json.dumps(labels)))


def focus(t, js_list, index):
    t.ev(f"{js_list}.at({index})?.focus()")


def type_credentials(t, acc):
    t.ev(CLEAR)
    focus(t, TEXT_INPUTS, 0)
    t.cdp("Input.insertText", text=acc["login"])
    focus(t, f"{VISIBLE_INPUTS}.filter(e=>e.type==='password')", 0)
    t.cdp("Input.insertText", text=acc["password"])
    click(t, LOGIN_BUTTONS)


def type_code(t, code):
    """The 2FA field is 6 boxes that ignore raw key events: insertText one digit per focused box."""
    n = t.ev(f"{TEXT_INPUTS}.length") or 0
    t.ev(CLEAR)
    if n >= 6:
        for j, ch in enumerate(code):
            focus(t, TEXT_INPUTS, n - 6 + j)
            t.cdp("Input.insertText", text=ch)
            time.sleep(0.12)
    else:
        focus(t, TEXT_INPUTS, -1)
        t.cdp("Input.insertText", text=code)


def is_logged_in(href, login_url):
    """Logged in = still on the app's site but no longer on the login page (2FA steps stay under its path)."""
    h, l = urlsplit(href), urlsplit(login_url)
    return (h.scheme, h.netloc) == (l.scheme, l.netloc) and not h.path.startswith(l.path.rstrip("/"))


def log_in(t, acc, url, budget=180):
    """Password + 2FA until the URL leaves /login. Budget covers a slow Cloudflare check on a cold window."""
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    typed = used = 0
    end = time.time() + budget
    while time.time() < end:
        href = t.ev("location.href") or ""
        if is_logged_in(href, url):
            return True
        if not href.startswith(origin) and not href.startswith("about:blank"):
            t.cdp("Page.navigate", url=url)
            time.sleep(5)
            continue
        types = t.ev(INPUT_TYPES) or []
        if "password" in types:
            if time.time() - typed > 20:  # form visible (first time, or bounced back): type it again
                type_credentials(t, acc)
                typed = time.time()
        elif types:  # 2FA step
            if not acc.get("totp_secret"):
                print(f"  {acc['login']}: pede código 2FA, mas a chave não está salva. Rode: enroll \"{acc['login']}\"", flush=True)
                return False
            if INVALID_RE.search(t.ev(PAGE_TEXT) or ""):  # one bad code kills the 2FA attempt: start over
                t.cdp("Page.navigate", url=url)
                typed = 0
                time.sleep(5)
                continue
            while int(time.time()) // 30 == used:  # never resubmit a code from the same 30 s window
                time.sleep(1)
            code = fresh_totp(acc["totp_secret"])
            used = int(time.time()) // 30
            type_code(t, code)
            time.sleep(4)  # the 6 boxes usually submit by themselves; click only if still here
            if not is_logged_in(t.ev("location.href") or "", url) and not click(t, LOGIN_BUTTONS):
                click(t, CONFIRM_BUTTONS)
            time.sleep(5)
        time.sleep(3)
    return False


# ---------- commands ----------

def cmd_setup(cfg):
    c = {"login_url": "", "base_port": 9341, "accounts": []}
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as f:
            c.update(json.load(f))
    print(f"Configuração: {cfg}\n")
    while True:
        cur = c.get("login_url", "")
        url = input(f"Endereço da página de login (ex.: https://app.suaempresa.com/login){f' [{cur}]' if cur else ''}: ").strip() or cur
        try:
            c["login_url"] = normalize_url(url)
            break
        except ValueError as e:
            print(f"  Endereço inválido: {e}")
    if c["accounts"]:
        print("\nContas já salvas: " + ", ".join(label(a) for a in c["accounts"]))
    print("\nAdicione as contas de teste (uma por vez). Login já existente é atualizado.")
    while True:
        login = input("\nLogin da conta (Enter para terminar): ").strip()
        if not login:
            break
        pw = getpass.getpass("Senha (não aparece enquanto digita): ") if sys.stdin.isatty() else input("Senha: ")
        name = input(f"Nome da janela [{login}]: ").strip() or login
        while True:
            key = input("Chave do 2FA (Enter se a conta ainda não tem 2FA ou você não tem a chave): ").strip()
            try:
                key = normalize_key(key) if key else ""
                break
            except (binascii.Error, ValueError):
                print("  Isso não parece uma chave 2FA (letras A-Z e números 2-7). Tente de novo.")
        acc = next((a for a in c["accounts"] if a["login"] == login), None)
        if acc is None:
            acc = {"login": login}
            c["accounts"].append(acc)
        acc.update(password=pw, label=name)
        if key:
            acc["totp_secret"] = key
    save(cfg, c)
    print(f"\nSalvo: {len(c['accounts'])} conta(s) em {cfg}")
    missing = [a["login"] for a in c["accounts"] if not a.get("totp_secret")]
    if missing:
        print("Sem chave 2FA: " + ", ".join(missing) + '. Se a conta pedir 2FA, rode: python launcher.py enroll "<login>"')
    print("Próximo passo: python launcher.py open   (ou o atalho na área de trabalho)")


def cmd_open(cfg):
    c = load(cfg)
    if not c["accounts"]:
        sys.exit("Nenhuma conta na configuração. Rode: python launcher.py setup")
    url, base = c["login_url"], c["base_port"]
    host = urlsplit(url).hostname
    chrome = find_chrome(c)
    for i, _ in enumerate(c["accounts"]):
        if not alive(base + i):  # a window already open for this account is reused, not duplicated
            launch(chrome, cfg, i, base + i, url)
    failed = 0
    for i, acc in enumerate(c["accounts"]):
        t0 = time.time()
        t = Tab(base + i, host)
        ok = log_in(t, acc, url)
        if not ok and acc.get("totp_secret"):  # a cold window can leave us on a stale target: reattach once
            t.close()
            t = Tab(base + i, host)
            t.cdp("Page.navigate", url=url)
            time.sleep(5)
            ok = log_in(t, acc, url)
        if ok:
            t.ev(PIN_TITLE % json.dumps(label(acc)))
        failed += not ok
        print(time.strftime("%H:%M:%S"), label(acc), "->", "OK" if ok else "FALHOU", f"({time.time() - t0:.0f}s)", flush=True)
        t.close()
    start_keeper(cfg)
    return failed


def start_keeper(cfg):
    """Background process that keeps each window titled with its account name (apps rewrite it on every screen)."""
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    args = [pyw if os.path.isfile(pyw) else py, os.path.abspath(__file__), "--config", os.path.abspath(cfg), "keep"]
    if os.name == "nt":
        subprocess.Popen(args, creationflags=0x00000008 | 0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_keep(cfg):
    c = load(cfg)
    lock = socket.socket()
    try:  # single keeper per config: the port just below the windows' range works as a lock
        lock.bind(("127.0.0.1", c["base_port"] - 1))
    except OSError:
        return
    while True:
        c = load(cfg)  # re-read so accounts added later are covered too
        host = urlsplit(c["login_url"]).hostname
        open_windows = 0
        for i, acc in enumerate(c["accounts"]):
            try:
                ps = pages(c["base_port"] + i)
            except (OSError, ValueError):
                continue
            open_windows += 1
            for p in ps:
                if urlsplit(p["url"]).hostname == host and p.get("title") != label(acc):
                    try:
                        ws = create_connection(p["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
                        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": PIN_TITLE % json.dumps(label(acc))}}))
                        ws.recv()
                        ws.close()
                    except Exception:  # tab closing or navigating: next round retries
                        pass
        if not open_windows:
            return
        time.sleep(5)


def find_account(c, which):
    if which.isdigit() and 1 <= int(which) <= len(c["accounts"]):
        return int(which) - 1
    for i, a in enumerate(c["accounts"]):
        if which in (a["login"], label(a)):
            return i
    sys.exit(f"Conta \"{which}\" não encontrada. Use o login ou o número (1 a {len(c['accounts'])}).")


def cmd_enroll(cfg, which):
    """Walk the first-login 2FA wizard: save the key it shows, confirm with the first code, save recovery codes."""
    c = load(cfg)
    i = find_account(c, which)
    acc, url, port = c["accounts"][i], c["login_url"], c["base_port"] + i
    if not alive(port):
        launch(find_chrome(c), cfg, i, port, url)
    t = Tab(port, urlsplit(url).hostname)
    typed = used = 0
    done = False
    end = time.time() + 300
    while time.time() < end:
        href = t.ev("location.href") or ""
        if is_logged_in(href, url):
            done = True
            break
        text = t.ev(PAGE_TEXT) or ""
        m = KEY_RE.search(text)
        if m and acc.get("totp_secret") != normalize_key(m.group(1)):
            acc["totp_secret"] = normalize_key(m.group(1))
            save(cfg, c)
            print("Chave 2FA salva.", flush=True)
        codes = RECOVERY_RE.findall(text)
        if codes and codes != acc.get("recovery_codes"):
            acc["recovery_codes"] = codes
            save(cfg, c)
            print(f"{len(codes)} códigos de recuperação salvos.", flush=True)
        types = t.ev(INPUT_TYPES) or []
        if "password" in types:
            if time.time() - typed > 20:
                type_credentials(t, acc)
                typed = time.time()
        elif types:  # code field
            if not acc.get("totp_secret"):
                sys.exit("Esta conta já tem 2FA ativo, mas a chave não está salva. Peça a quem administra o ambiente para "
                         "resetar o 2FA dela e rode enroll de novo, ou cole a chave pelo setup.")
            if int(time.time()) // 30 != used:
                code = fresh_totp(acc["totp_secret"])
                used = int(time.time()) // 30
                type_code(t, code)
                time.sleep(2)
                click(t, WIZARD_BUTTONS + CONFIRM_BUTTONS + LOGIN_BUTTONS)
        else:
            click(t, WIZARD_BUTTONS)
        time.sleep(3)
    t.close()
    if done and acc.get("totp_secret"):
        print(f"{label(acc)}: 2FA pronto e conta logada.")
    elif done:
        print(f"{label(acc)}: entrou sem pedir 2FA (o ambiente não exige 2FA para esta conta).")
    else:
        sys.exit(f"{label(acc)}: não terminou em 5 min. Termine o passo na janela aberta e rode enroll de novo.")


PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Contas de teste</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#1d2330}
h1{font-size:20px;margin:0 0 4px}p{margin:4px 0 14px;color:#555}
table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px #0001}
th,td{padding:10px 12px;border-bottom:1px solid #e6e8ec;text-align:left;vertical-align:top;font-size:14px}
th{background:#eef0f4;font-weight:600}
.code{font:600 22px Consolas,monospace;letter-spacing:2px}.mono{font-family:Consolas,monospace}
button{font-size:12px;margin-left:6px;cursor:pointer}.bar{height:4px;background:#2b6cb0;margin-top:4px}
.rec{font-family:Consolas,monospace;font-size:12px;color:#444}
.warn{background:#fff6e0;border:1px solid #f0d58c;padding:8px 12px;margin-bottom:14px}
</style></head><body>
<h1>Contas de teste</h1>
<p>Entrar em: <a href="@URL@">@URL@</a>. O código 2FA muda a cada 30 s e é calculado aqui mesmo, sem internet.</p>
<div class="warn">Arquivo local com senhas. Não envie para ninguém e não guarde em pasta sincronizada.</div>
<table><tr><th>Conta</th><th>Login</th><th>Senha</th><th>Código 2FA</th><th>Códigos de recuperação</th></tr>@ROWS@</table>
<script>
const D=@DATA@;
function sha1(b){const H=[0x67452301,0xEFCDAB89,0x98BADCFE,0x10325476,0xC3D2E1F0];const l=b.length*8;const m=b.concat([0x80]);while(m.length%64!==56)m.push(0);for(let i=7;i>=0;i--)m.push(i>3?0:(l>>>(i*8))&255);
const w=new Array(80);for(let o=0;o<m.length;o+=64){for(let i=0;i<16;i++)w[i]=(m[o+4*i]<<24)|(m[o+4*i+1]<<16)|(m[o+4*i+2]<<8)|m[o+4*i+3];
for(let i=16;i<80;i++){const x=w[i-3]^w[i-8]^w[i-14]^w[i-16];w[i]=(x<<1)|(x>>>31)}let[a,b2,c,d,e]=H;
for(let i=0;i<80;i++){const f=i<20?(b2&c)|(~b2&d):i<40?b2^c^d:i<60?(b2&c)|(b2&d)|(c&d):b2^c^d;const k=i<20?0x5A827999:i<40?0x6ED9EBA1:i<60?0x8F1BBCDC:0xCA62C1D6;
const t=(((a<<5)|(a>>>27))+f+e+k+w[i])|0;e=d;d=c;c=(b2<<30)|(b2>>>2);b2=a;a=t}H[0]=(H[0]+a)|0;H[1]=(H[1]+b2)|0;H[2]=(H[2]+c)|0;H[3]=(H[3]+d)|0;H[4]=(H[4]+e)|0}
const r=[];H.forEach(h=>{for(let i=3;i>=0;i--)r.push((h>>>(i*8))&255)});return r}
function hmac(k,m){if(k.length>64)k=sha1(k);while(k.length<64)k.push(0);const ip=k.map(x=>x^0x36),op=k.map(x=>x^0x5c);return sha1(op.concat(sha1(ip.concat(m))))}
function b32(s){const A='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';let bits='';for(const ch of s.replace(/=+$/,'').toUpperCase())bits+=A.indexOf(ch).toString(2).padStart(5,'0');const o=[];for(let i=0;i+8<=bits.length;i+=8)o.push(parseInt(bits.slice(i,i+8),2));return o}
function totp(sec){const c=Math.floor(Date.now()/30000);const m=[];for(let i=7;i>=0;i--)m.push(i>3?0:(c>>>(i*8))&255);const h=hmac(b32(sec),m);const o=h[19]&15;
return String((((h[o]&127)<<24)|(h[o+1]<<16)|(h[o+2]<<8)|h[o+3])%1000000).padStart(6,'0')}
function tick(){const left=30-Math.floor(Date.now()/1000)%30;D.forEach((u,i)=>{const el=document.getElementById('c'+i);if(!el)return;el.textContent=totp(u.secret);
document.getElementById('b'+i).style.width=(left/30*100)+'%'})}
function cp(t){navigator.clipboard.writeText(t)}
tick();setInterval(tick,1000);
</script></body></html>"""


def cmd_page(cfg, open_it=True):
    c = load(cfg)
    e = html.escape
    rows = []
    for i, a in enumerate(c["accounts"]):
        pw = (f'<span class="mono">{e(a.get("password", ""))}</span><button onclick="cp(D[{i}].pw)">copiar</button>'
              if a.get("password") else "<i>sem senha salva</i>")
        code = (f'<span class="code" id="c{i}"></span><button onclick="cp(document.getElementById(\'c{i}\').textContent)">copiar</button>'
                f'<div class="bar" id="b{i}"></div>') if a.get("totp_secret") else "<i>sem chave 2FA</i>"
        rec = '<div class="rec">' + "<br>".join(e(x) for x in a.get("recovery_codes", [])) + "</div>" if a.get("recovery_codes") else "—"
        rows.append(f'<tr><td><b>{e(label(a))}</b></td><td class="mono">{e(a["login"])}<button onclick="cp(D[{i}].login)">copiar</button></td>'
                    f"<td>{pw}</td><td>{code}</td><td>{rec}</td></tr>")
    data = json.dumps([{"login": a["login"], "pw": a.get("password", ""), "secret": a.get("totp_secret", "")} for a in c["accounts"]])
    out = os.path.join(os.path.dirname(os.path.abspath(cfg)), "contas.html")
    page = (PAGE.replace("@URL@", e(c["login_url"])).replace("@ROWS@", "".join(rows))
            .replace("@DATA@", data.replace("</", "<\\/")))  # a password containing </script> cannot break out
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{len(rows)} conta(s) -> {out}")
    if open_it:
        webbrowser.open(Path(out).as_uri())


SHORTCUTS = (("Contas de teste", "open", "Abre uma janela anônima por conta de teste, já logada"),
             ("Senhas e códigos 2FA", "page", "Logins, senhas e código 2FA ao vivo das contas de teste"))


def cmd_shortcut(cfg):
    cfg = os.path.abspath(cfg)
    stem = os.path.splitext(os.path.basename(cfg))[0]
    suffix = "" if stem == "config" else f" ({stem})"
    chrome = find_chrome(load(cfg))
    entries = [(name + suffix, [sys.executable, os.path.abspath(__file__), "--config", cfg, "--log", cmd], desc)
               for name, cmd, desc in SHORTCUTS]
    if os.name == "nt":
        made = shortcut_windows(entries, chrome)
    elif sys.platform == "darwin":
        made = shortcut_macos(entries)
    else:
        made = shortcut_linux(entries)
    print("Atalhos criados:\n  " + "\n  ".join(made))


def shortcut_windows(entries, chrome):
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")  # no console window
    q = lambda v: "'" + v.replace("'", "''") + "'"  # PowerShell single-quoted literal
    script = "$sh=New-Object -ComObject WScript.Shell;$d=[Environment]::GetFolderPath('Desktop');$d;"
    for name, argv, desc in entries:
        args = subprocess.list2cmdline(argv[1:])
        script += (f"$s=$sh.CreateShortcut((Join-Path $d {q(name + '.lnk')}));$s.TargetPath={q(pyw if os.path.isfile(pyw) else argv[0])};"
                   f"$s.Arguments={q(args)};$s.WorkingDirectory={q(HERE)};$s.IconLocation={q(chrome + ',0')};$s.Description={q(desc)};$s.Save();")
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], capture_output=True)
    if r.returncode:  # PowerShell writes in the console code page: decode leniently
        sys.exit("Não consegui criar os atalhos: " + (r.stderr.decode(errors="replace").strip().splitlines() or ["erro desconhecido"])[-1])
    desktop = r.stdout.decode(errors="replace").strip().splitlines()[0]
    return [os.path.join(desktop, name + ".lnk") for name, _, _ in entries]


def shortcut_macos(entries):
    """A tiny AppleScript app on the Desktop: double-click runs the command in the background, no Terminal window."""
    made = []
    for name, argv, _ in entries:
        app = os.path.expanduser(f"~/Desktop/{name}.app")
        shell = shlex.join(argv) + " >/dev/null 2>&1 &"
        script = 'do shell script "' + shell.replace("\\", "\\\\").replace('"', '\\"') + '"'
        shutil.rmtree(app, ignore_errors=True)
        r = subprocess.run(["osacompile", "-o", app, "-e", script], capture_output=True, text=True)
        if r.returncode:
            sys.exit("Não consegui criar o atalho: " + r.stderr.strip())
        made.append(app)
    return made


def desktop_exec(argv):
    """Exec= value per the freedesktop Desktop Entry spec: quote each arg, then escape for the string type."""
    quoted = []
    for a in argv:
        for ch in ("\\", '"', "`", "$"):
            a = a.replace(ch, "\\" + ch)
        quoted.append('"' + a + '"')
    return " ".join(quoted).replace("\\", "\\\\").replace("%", "%%")


def shortcut_linux(entries):
    """.desktop launchers in the app menu and, when it exists, on the Desktop."""
    apps = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")
    os.makedirs(apps, exist_ok=True)
    try:
        desktop = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
    except OSError:
        desktop = os.path.expanduser("~/Desktop")
    made = []
    for name, argv, desc in entries:
        slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()).strip("-")
        body = (f"[Desktop Entry]\nType=Application\nName={name}\nComment={desc}\nExec={desktop_exec(argv)}\n"
                "Icon=web-browser\nTerminal=false\nCategories=Network;\n")
        targets = [os.path.join(apps, slug + ".desktop")]
        if desktop and os.path.isdir(desktop) and os.path.abspath(desktop) != os.path.expanduser("~"):
            targets.append(os.path.join(desktop, slug + ".desktop"))
        for path in targets:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            os.chmod(path, 0o700)  # launchers must be executable; only the owner needs it
            if shutil.which("gio"):  # GNOME only runs Desktop launchers marked as trusted
                subprocess.run(["gio", "set", path, "metadata::trusted", "true"], capture_output=True)
            made.append(path)
    return made


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"), help="arquivo de configuração (padrão: config.json)")
    ap.add_argument("--log", action="store_true", help="grava a saída em run.log, ao lado da configuração (usado pelos atalhos)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "open", "page", "shortcut", "keep"):
        sub.add_parser(name)
    sub.add_parser("enroll").add_argument("account", help="login, nome da janela ou número da conta (1, 2...)")
    a = ap.parse_args()
    if a.log or sys.stdout is None:  # desktop shortcuts have no console: log next to the config
        sys.stdout = sys.stderr = open(os.path.join(os.path.dirname(os.path.abspath(a.config)), "run.log"), "w", encoding="utf-8")
    if a.cmd == "setup":
        cmd_setup(a.config)
    elif a.cmd == "open":
        sys.exit(1 if cmd_open(a.config) else 0)
    elif a.cmd == "enroll":
        cmd_enroll(a.config, a.account)
    elif a.cmd == "page":
        cmd_page(a.config)
    elif a.cmd == "shortcut":
        cmd_shortcut(a.config)
    elif a.cmd == "keep":
        cmd_keep(a.config)


if __name__ == "__main__":
    main()
