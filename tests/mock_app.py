"""Stand-in web app for end-to-end tests: login form, 2FA (6 boxes) and a first-login 2FA wizard.

Forms live in shadow DOM and the 2FA boxes auto-submit, like real apps that made the launcher's tricks necessary.
    python tests/mock_app.py [port] [events.log]
Accounts: ana (2FA already on, key ANA_KEY) and bia (no 2FA yet: goes through the enrollment wizard).
Every completed login appends "LOGIN_OK <user>" to the events log.
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANA_KEY = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # gitleaks:allow - fake key for the mock app
USERS = {"ana": {"pw": "senha-ana", "secret": ANA_KEY}, "bia": {"pw": "senha-bia", "secret": None}}
SESSIONS = {}  # sid -> {"user", "stage": "password"|"2fa"|"enroll"|"in", "pending"}
LOG = sys.argv[2] if len(sys.argv) > 2 else "mock-events.log"


def totp(secret, t):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", int(t) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def code_ok(secret, code):
    now = time.time()
    return any(totp(secret, now + d) == code for d in (-30, 0, 30))


def event(text):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(text + "\n")


SHADOW = """<script>
class Box extends HTMLElement{constructor(){super();this.attachShadow({mode:'open'}).innerHTML=this.querySelector('template').innerHTML}}
customElements.define('x-box',Box);
const $=s=>document.querySelector('x-box').shadowRoot.querySelector(s), $$=s=>[...document.querySelector('x-box').shadowRoot.querySelectorAll(s)];
async function post(u,b){const r=await fetch(u,{method:'POST',body:JSON.stringify(b)});return r.json()}
function boxes(onFull){const bs=$$('.d');bs.forEach((b,i)=>b.addEventListener('input',()=>{if(b.value&&bs[i+1])bs[i+1].focus();
 const v=bs.map(x=>x.value).join('');if(v.length===6)onFull(v)}))}
</script>"""

SIX = "".join('<input class="d" type="number" style="width:2em">' for _ in range(6))

LOGIN = """<!doctype html><title>Mock - login</title><x-box><template>
<h2>Entrar</h2><input id="u" placeholder="Usuário"><input id="p" type="password" placeholder="Senha"><button id="b">Entrar</button><p id="m"></p>
</template></x-box>""" + SHADOW + """<script>
$('#b').onclick=async()=>{const r=await post('/api/login',{u:$('#u').value,p:$('#p').value});
 if(r.next)location.href=r.next;else $('#m').textContent='Usuário ou senha inválidos'}
</script>"""

TWOFA = """<!doctype html><title>Mock - 2FA</title><x-box><template>
<h2>Código do app autenticador</h2>""" + SIX + """<p id="m"></p></template></x-box>""" + SHADOW + """<script>
boxes(async v=>{const r=await post('/api/2fa',{code:v});if(r.next)location.href=r.next;else $('#m').textContent='Código inválido'})
</script>"""

ENROLL = """<!doctype html><title>Mock - ativar 2FA</title><x-box><template><div id="s"></div></template></x-box>""" + SHADOW + """<script>
const s=()=>$('#s');
function step1(){s().innerHTML='<h2>Proteja sua conta</h2><p>Vamos ativar a verificação em duas etapas.</p><button>Ok, vamos lá</button>';
 s().querySelector('button').onclick=step2}
async function step2(){const r=await post('/api/enroll/start',{});
 s().innerHTML='<p>Escaneie o QR code ou digite a chave:</p><p class="k"></p><button>Próximo</button>';
 s().querySelector('.k').textContent=r.key.match(/.{4}/g).join(' ');s().querySelector('button').onclick=step3}
function step3(){s().innerHTML='<p>Digite o código do app:</p>""" + SIX + """<p id="m"></p><button>Próximo</button>';
 s().querySelector('button').onclick=async()=>{const v=$$('.d').map(x=>x.value).join('');
  const r=await post('/api/enroll/verify',{code:v});if(r.codes)step4(r.codes);else $('#m').textContent='Código inválido'}}
function step4(codes){s().innerHTML='<p>Salve estes códigos de recuperação:</p>'+codes.map(c=>'<div>'+c+'</div>').join('')+'<button>Concluir</button>';
 s().querySelector('button').onclick=()=>location.href='/app/'}
step1()
</script>"""

APP = """<!doctype html><title>Mock - início</title><h1>Bem-vindo, %s</h1>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def session(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid" and v in SESSIONS:
                return v, SESSIONS[v]
        sid = secrets.token_hex(8)
        SESSIONS[sid] = {"stage": "password"}
        return sid, SESSIONS[sid]

    def send(self, code, body, sid, ctype="text/html; charset=utf-8", location=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Set-Cookie", f"sid={sid}; Path=/; HttpOnly; SameSite=Lax")
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        sid, s = self.session()
        path = self.path.split("?")[0]
        if path.startswith("/app"):
            if s["stage"] != "in":
                return self.send(302, "", sid, location="/login")
            return self.send(200, APP % s["user"], sid)
        pages = {"/login": LOGIN, "/login/2fa": TWOFA, "/login/enroll": ENROLL}
        stage_page = {"2fa": "/login/2fa", "enroll": "/login/enroll", "in": "/app/"}
        if path in pages:
            want = stage_page.get(s["stage"], "/login")
            if path != want and not (path == "/login" and s["stage"] == "password"):
                return self.send(302, "", sid, location=want)
            return self.send(200, pages[path], sid)
        self.send(302, "", sid, location="/login")

    def do_POST(self):
        sid, s = self.session()
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        reply = {}
        if self.path == "/api/login":
            u = USERS.get(body.get("u"))
            if u and u["pw"] == body.get("p"):
                s["user"] = body["u"]
                s["stage"] = "2fa" if u["secret"] else "enroll"
                reply = {"next": "/login/2fa" if u["secret"] else "/login/enroll"}
        elif self.path == "/api/2fa" and s["stage"] == "2fa":
            if code_ok(USERS[s["user"]]["secret"], body.get("code", "")):
                s["stage"] = "in"
                event("LOGIN_OK " + s["user"])
                reply = {"next": "/app/"}
        elif self.path == "/api/enroll/start" and s["stage"] == "enroll":
            s["pending"] = base64.b32encode(secrets.token_bytes(20)).decode()
            reply = {"key": s["pending"]}
        elif self.path == "/api/enroll/verify" and s["stage"] == "enroll" and s.get("pending"):
            if code_ok(s["pending"], body.get("code", "")):
                USERS[s["user"]]["secret"] = s["pending"]
                s["stage"] = "in"
                event("ENROLLED " + s["user"])
                event("LOGIN_OK " + s["user"])
                reply = {"codes": ["-".join(secrets.token_hex(2) for _ in range(4)) for _ in range(4)]}
        self.send(200, json.dumps(reply), sid, "application/json")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock app on http://127.0.0.1:{port}/login", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
