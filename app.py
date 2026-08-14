#!/usr/bin/env python3
"""
Archivador de canal — descargador y organizador de videos de YouTube.

Backend multiplataforma (Linux / macOS / Windows). Sirve la interfaz web
(index.html, misma estética que la maqueta) y realiza las descargas reales
con yt-dlp. La UI se abre sola en el navegador.

Dos formas de listar videos:

  · **Con tu cuenta de Google** (recomendado): inicia sesión y la app usa la
    YouTube Data API para listar **todos** los videos de tu canal, incluidos
    los **privados** y **no listados**.
  · **Sin sesión**: pega el enlace o @usuario de cualquier canal y se lee su
    pestaña pública de videos con yt-dlp.

Uso:
    python3 app.py
    python3 app.py --port 8717 --no-browser

Dependencias: yt-dlp (módulo de Python) y ffmpeg en el PATH (recomendado).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"

# La consola de Windows suele ser cp1252 y reventaba con los símbolos del banner
# (UnicodeEncodeError al arrancar). Forzamos UTF-8 tolerante en la salida.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # streams redirigidos o sin soporte
        pass

# ─────────────────────────── yt-dlp ───────────────────────────
try:
    import yt_dlp
except ImportError:
    print("\n  ✗ Falta yt-dlp.  Instálalo con:  pip install yt-dlp\n", file=sys.stderr)
    sys.exit(1)

# Sesión con Google / YouTube Data API (módulo local, sin dependencias extra)
import ytauth
from ytauth import AuthError

# Cancelar descargas: el nombre de la excepción cambió entre versiones
CANCELLED = getattr(yt_dlp.utils, "DownloadCancelled", None) or KeyboardInterrupt


def has_ffmpeg() -> bool:
    """ffmpeg hace falta para fusionar video+audio, subtítulos y miniaturas."""
    return bool(shutil.which("ffmpeg"))


FFMPEG = has_ffmpeg()


def pick_folder_native(initial: str) -> str:
    """Abre un diálogo nativo de carpeta (tkinter) en un subproceso aislado.

    Se ejecuta en un proceso aparte para no chocar con el hilo del servidor;
    devuelve la ruta elegida o "" si el usuario cancela / no hay GUI."""
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "import sys\n"
        "p = filedialog.askdirectory(initialdir=sys.argv[1] if len(sys.argv)>1 else '.', "
        "title='Elige dónde guardar los videos')\n"
        "print(p or '')\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", script, initial or str(Path.home())],
            capture_output=True, text=True, timeout=180,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def pick_file_native(initial: str, title: str) -> str:
    """Abre un diálogo nativo para elegir un archivo (p. ej. cookies.txt)."""
    script = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askopenfilename(initialdir=sys.argv[1], title=sys.argv[2])\n"
        "print(p or '')\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", script, initial or str(Path.home()), title],
            capture_output=True, text=True, timeout=180,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def default_dest() -> str:
    home = Path.home()
    for name in ("Videos", "Vídeos", "Movies"):
        cand = home / name
        if cand.exists():
            return str(cand / "Respaldo Canal")
    return str(home / "Respaldo Canal")


# ─────────────────────────── Estado ───────────────────────────
class Store:
    """Estado compartido y protegido entre los hilos de descarga."""

    def __init__(self):
        self.lock = threading.Lock()
        self.channel = None          # {name, handle, avatar, thumb}
        self.videos = {}             # id -> dict
        self.order = []              # orden de escaneo
        self.running = False
        self.paused = False
        self.stop_flag = False
        self.dest = default_dest()
        self.scan = {"running": False, "msg": "", "error": ""}
        self.auth = {"has_client": False, "signed_in": False, "account": None,
                     "busy": False, "error": ""}
        self.options = {
            "mode": "video",
            "quality": 1080,
            "subs": True,
            "subs_langs": "es,en",   # pedir «all» dispara el 429 de YouTube
            "meta": True,
            "chapters": False,
            "concurrency": 3,
            "cookies_browser": "",   # "", "firefox", "chrome", "brave", ...
            "cookies_file": "",      # ruta a un cookies.txt exportado del navegador
            "by_date": True,
            "skip_existing": True,   # no volver a descargar lo ya archivado
        }

    def snapshot(self):
        with self.lock:
            return {
                "channel": self.channel,
                "videos": [self.videos[i] for i in self.order if i in self.videos],
                "running": self.running,
                "paused": self.paused,
                "dest": self.dest,
                "options": dict(self.options),
                "scan": dict(self.scan),
                "auth": dict(self.auth),
                "ffmpeg": FFMPEG,
            }


STORE = Store()


def scan_progress(msg: str):
    with STORE.lock:
        STORE.scan["msg"] = msg


def refresh_auth(network=True):
    """Actualiza la caché del estado de sesión (la UI la lee del snapshot)."""
    try:
        st = ytauth.status() if network else {
            "has_client": bool(ytauth.load_client().get("client_id")),
            "client_id": ytauth.load_client().get("client_id", ""),
            "signed_in": ytauth.signed_in(),
            "account": None,
            "error": "",
        }
    except Exception as e:  # noqa: BLE001
        st = {"has_client": bool(ytauth.load_client().get("client_id")),
              "signed_in": ytauth.signed_in(), "account": None, "error": str(e)}
    with STORE.lock:
        STORE.auth.update(st)
        STORE.auth["busy"] = False
    return dict(STORE.auth)


# ─────────────────────────── Escaneo ───────────────────────────
def build_channel_url(text: str) -> str:
    text = text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        url = text
    elif text.startswith("@"):
        url = f"https://www.youtube.com/{text}"
    else:
        url = f"https://www.youtube.com/@{text}"
    # apuntar a la pestaña de videos para listar el contenido
    if "/videos" not in url and "/playlist" not in url and "watch?v" not in url:
        url = url.rstrip("/") + "/videos"
    return url


def initials_of(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"\w+", name)[:2]).upper() or "MC"


def store_videos(channel: dict, videos: list):
    """Guarda el resultado de un escaneo y marca lo que ya está en disco."""
    if STORE.options.get("skip_existing", True):
        have = downloaded_ids(channel["name"])
    else:
        have = set()
    vmap, order = {}, []
    for v in videos:
        v.setdefault("status", "queued")
        v.setdefault("prog", 0.0)
        v.setdefault("rate", 0.0)
        v.setdefault("size", 0)
        v.setdefault("privacy", "public")
        v.setdefault("thumb", "")
        v["sel"] = True
        if v["id"] in have:
            v["status"] = "archived"
            v["sel"] = False
        vmap[v["id"]] = v
        order.append(v["id"])
    with STORE.lock:
        STORE.channel = channel
        STORE.videos = vmap
        STORE.order = order


def scan_mine():
    """Lista TODOS los videos del canal de la sesión (incluye ocultos)."""
    scan_progress("Conectando con tu canal…")
    ch, videos = ytauth.list_all_videos(scan_progress)
    channel = {
        "name": ch["name"],
        "handle": ch["handle"] if str(ch["handle"]).startswith("@") else "@" + str(ch["handle"]).lstrip("@"),
        "avatar": initials_of(ch["name"]),
        "thumb": ch.get("thumb", ""),
        "mine": True,
    }
    store_videos(channel, videos)


def scan_public(text: str):
    """Escaneo sin sesión: pestaña pública del canal, vía yt-dlp."""
    url = build_channel_url(text)
    scan_progress("Leyendo el canal…")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
    }
    apply_cookies(ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("No se pudo leer el canal. Revisa el enlace o el @usuario.")

    entries = info.get("entries") or []
    # algunos canales devuelven listas anidadas (tabs)
    flat = []
    for e in entries:
        if e is None:
            continue
        if e.get("entries"):
            flat.extend([x for x in e["entries"] if x])
        else:
            flat.append(e)

    name = info.get("channel") or info.get("uploader") or info.get("title") or "Mi Canal"
    handle = info.get("uploader_id") or info.get("channel_id") or text.strip()

    videos = []
    for idx, e in enumerate(flat):
        vid = e.get("id") or f"v{idx}"
        date = e.get("upload_date")  # YYYYMMDD o None (suele faltar en modo plano)
        videos.append({
            "id": vid,
            "url": e.get("url") or e.get("webpage_url") or f"https://youtu.be/{vid}",
            "title": e.get("title") or "(sin título)",
            "duration": int(e.get("duration") or 0),
            "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date and len(date) == 8 else "",
            "size": int(e.get("filesize") or e.get("filesize_approx") or 0),
            "privacy": e.get("availability") or "public",
            "thumb": (e.get("thumbnails") or [{}])[-1].get("url", "") if e.get("thumbnails") else "",
        })

    store_videos({"name": name, "handle": str(handle), "avatar": initials_of(name),
                  "thumb": "", "mine": False}, videos)


def run_scan(kind: str, text: str = ""):
    with STORE.lock:
        STORE.scan = {"running": True, "msg": "Preparando…", "error": ""}
    try:
        if kind == "mine":
            scan_mine()
        else:
            scan_public(text)
        with STORE.lock:
            STORE.scan = {"running": False, "msg": "", "error": ""}
    except Exception as e:  # noqa: BLE001
        with STORE.lock:
            STORE.scan = {"running": False, "msg": "", "error": str(e)}


# ─────────────────────────── Descarga ───────────────────────────
def apply_cookies(opts: dict) -> dict:
    """Aplica la sesión del navegador para acceder a videos privados.

    Prioridad: archivo cookies.txt explícito > cookies del navegador donde el
    usuario inició sesión con la cuenta de Google del canal."""
    o = STORE.options
    cf = (o.get("cookies_file") or "").strip()
    if cf and os.path.exists(cf):
        opts["cookiefile"] = cf
    elif o.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (o["cookies_browser"],)
    return opts


def has_session() -> bool:
    """¿Hay cookies configuradas? (necesarias para descargar videos privados)"""
    o = STORE.options
    cf = (o.get("cookies_file") or "").strip()
    return bool((cf and os.path.exists(cf)) or o.get("cookies_browser"))


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip() or "Canal"


ARCHIVE_NAME = ".descargados.txt"


def channel_dir(channel_name: str) -> Path:
    return Path(STORE.dest) / safe_name(channel_name)


def downloaded_ids(channel_name: str) -> set:
    """IDs ya descargados: combina el registro de yt-dlp y los archivos en disco.

    Detecta por el sufijo «[ID]» que la plantilla de salida añade al nombre, así
    funciona aunque se haya borrado el registro o movido la app."""
    ids = set()
    base = channel_dir(channel_name)
    arch = base / ARCHIVE_NAME
    if arch.exists():
        for line in arch.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line:
                ids.add(line.split()[-1])  # formato: "youtube <id>"
    if base.exists():
        media = (".mp4", ".mkv", ".webm", ".m4a", ".mp3", ".opus", ".flac", ".wav")
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in media:
                m = re.search(r"\[([A-Za-z0-9_-]{6,})\]", p.name)
                if m:
                    ids.add(m.group(1))
    return ids


def make_progress_hook(vid: str):
    def hook(d):
        if STORE.stop_flag:
            raise CANCELLED()
        with STORE.lock:
            v = STORE.videos.get(vid)
            if not v:
                return
            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                v["status"] = "downloading"
                v["prog"] = (done / total * 100) if total else v["prog"]
                v["rate"] = (d.get("speed") or 0) / (1024 * 1024)
                if total:
                    v["size"] = total
            elif st == "finished":
                # terminó la descarga; aún puede haber post-proceso (merge/ffmpeg)
                v["prog"] = 99.0
                v["rate"] = 0.0
                v["status"] = "processing"
    return hook


def sub_langs() -> list:
    """Idiomas de subtítulos pedidos, saneados.

    Pedir «all» con subtítulos automáticos hace que yt-dlp solicite ~200 pistas
    auto-traducidas: YouTube responde 429 y se cae la descarga entera. Por eso
    se piden idiomas concretos (y nunca el chat en directo)."""
    raw = (STORE.options.get("subs_langs") or "").strip()
    langs = [x.strip() for x in re.split(r"[,\s]+", raw) if x.strip()]
    if not langs:
        langs = ["es", "en"]
    if "all" in langs:                       # el usuario lo pidió explícitamente
        return ["all", "-live_chat"]
    out = []
    for lg in langs:
        out.append(lg)
        if not lg.endswith(".*") and "-" not in lg:
            out.append(f"{lg}-.*")           # variantes regionales (es-419, en-US…)
    out.append("-live_chat")
    return out


def ydl_opts_for(vid: str, with_subs=True) -> dict:
    o = STORE.options
    ch = STORE.channel["name"] if STORE.channel else "Canal"
    base = channel_dir(ch)
    # El prefijo de fecha se arma aquí (no con %(upload_date)s) porque en el
    # escaneo plano ese campo llega vacío y yt-dlp escribiría «NA - ...».
    v = STORE.videos.get(vid) or {}
    prefix = ""
    if o["by_date"]:
        date = (v.get("date") or "").strip()
        prefix = f"{date} - " if date else "%(upload_date>%Y-%m-%d)s - "
    tmpl = str(base / (prefix + "%(title)s [%(id)s].%(ext)s"))

    opts = {
        "outtmpl": tmpl,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noprogress": True,
        "progress_hooks": [make_progress_hook(vid)],
        "postprocessors": [],
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": sys.platform.startswith("win"),
    }
    apply_cookies(opts)

    if o.get("skip_existing", True):
        base.mkdir(parents=True, exist_ok=True)
        opts["download_archive"] = str(base / ARCHIVE_NAME)
    else:
        opts["overwrites"] = True   # forzar re-descarga si el usuario lo pide

    if o["mode"] == "audio":
        opts["format"] = "bestaudio/best"
        if FFMPEG:
            opts["postprocessors"].append(
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
            )
    else:
        q = o["quality"]
        if FFMPEG:
            # pistas separadas + fusión (mejor calidad); necesita ffmpeg
            opts["format"] = f"bv*[height<={q}]+ba/b[height<={q}]/b"
            opts["merge_output_format"] = "mp4"
        else:
            # sin ffmpeg solo sirve un archivo ya combinado
            opts["format"] = f"b[height<={q}]/b"

    if o["subs"] and with_subs:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = sub_langs()
        opts["sleep_interval_subtitles"] = 1   # evita el 429 de YouTube
        if FFMPEG:
            opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})
        # sin ffmpeg quedan como archivos .vtt junto al video

    if o["meta"]:
        opts["writethumbnail"] = True
        if FFMPEG:
            opts["postprocessors"].append(
                {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": o["chapters"]}
            )
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
    elif o["chapters"] and FFMPEG:
        opts["postprocessors"].append({"key": "FFmpegMetadata", "add_chapters": True})

    return opts


PRIVATE_HINT = (
    "Video privado: para descargarlo necesitas las cookies del navegador donde "
    "iniciaste sesión con esta cuenta (panel «Sesión del navegador»)."
)


# YouTube devuelve 403/429 de forma intermitente en las URLs de los flujos. La
# URL caduca con el intento, así que reintentar exige volver a extraer: por eso
# se crea un YoutubeDL nuevo en cada pasada.
TRANSIENT = ("403", "429", "unable to download video data", "timed out",
             "temporary failure", "connection reset", "read operation")
BACKOFF = (5, 15, 30, 60)   # los cortes de YouTube vienen a ráfagas: hay que esperar


def is_transient(err: str) -> bool:
    e = err.lower()
    return any(t in e for t in TRANSIENT)


def attempt_download(vid: str, url: str):
    """Descarga con reintentos y, si los subtítulos fallan, sin ellos."""
    with_subs = True
    last = None
    for i in range(len(BACKOFF) + 1):
        if STORE.stop_flag:
            raise CANCELLED()
        try:
            with yt_dlp.YoutubeDL(ydl_opts_for(vid, with_subs=with_subs)) as ydl:
                ydl.download([url])
            return
        except CANCELLED:
            raise
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            last = e
            # Un tropiezo con los subtítulos no debe costarnos el video.
            if with_subs and "subtitle" in msg.lower():
                with_subs = False
                with STORE.lock:
                    v = STORE.videos.get(vid)
                    if v:
                        v["note"] = "sin subtítulos"
                continue
            if not is_transient(msg) or i >= len(BACKOFF):
                raise
            with STORE.lock:
                v = STORE.videos.get(vid)
                if v:
                    v["status"] = "downloading"
                    v["prog"] = 0.0
                    v["rate"] = 0.0
                    v["note"] = f"reintentando ({i + 1}/{len(BACKOFF)})"
            waited = 0.0
            while waited < BACKOFF[i] and not STORE.stop_flag:
                time.sleep(0.3)
                waited += 0.3
    if last:
        raise last


def download_one(vid: str):
    while STORE.paused and not STORE.stop_flag:
        time.sleep(0.3)
    if STORE.stop_flag:
        return
    with STORE.lock:
        v = STORE.videos.get(vid)
        if not v or not v["sel"] or v["status"] != "queued":
            return
        url = v["url"]
        private = v.get("privacy") == "private"
        v["status"] = "downloading"
        v["prog"] = 0.0

    # Los privados no se pueden bajar solo con el token de OAuth: avisamos antes
    # de gastar una petición contra YouTube.
    if private and not has_session():
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v:
                v["status"] = "error"
                v["error"] = PRIVATE_HINT
                v["rate"] = 0.0
        return

    try:
        attempt_download(vid, url)
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v:
                v["status"] = "done"
                v["prog"] = 100.0
                v["rate"] = 0.0
                v["sel"] = False
                v.pop("note", None)
    except CANCELLED:
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v and v["status"] != "done":
                v["status"] = "queued"
                v["prog"] = 0.0
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if private and ("Private video" in msg or "Sign in" in msg):
            msg = PRIVATE_HINT
        elif "ffmpeg" in msg.lower():
            msg = "Falta ffmpeg en el sistema: instálalo para fusionar video y audio."
        elif is_transient(msg):
            msg = ("YouTube está limitando las descargas desde tu conexión "
                   "(403/429). Espera unos minutos y vuelve a pulsar Descargar: "
                   "lo ya bajado no se repite.")
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v:
                v["status"] = "error"
                v["error"] = msg[:300]
                v["rate"] = 0.0


def run_downloads(ids):
    with STORE.lock:
        STORE.running = True
        STORE.paused = False
        STORE.stop_flag = False
        conc = max(1, int(STORE.options["concurrency"]))
        for i in ids:
            v = STORE.videos.get(i)
            if v and v["status"] in ("queued", "error"):
                v["sel"] = True
                v["status"] = "queued"
                v.pop("error", None)
                v.pop("note", None)

    try:
        with ThreadPoolExecutor(max_workers=conc) as ex:
            futures = [ex.submit(download_one, i) for i in ids]
            for f in futures:
                f.result()
    finally:
        with STORE.lock:
            STORE.running = False
            STORE.paused = False
            STORE.stop_flag = False


# ─────────────────────────── HTTP ───────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            if INDEX.exists():
                self._send(200, INDEX.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            else:
                self._send(500, "index.html no encontrado", "text/plain")
        elif self.path == "/api/state":
            self._send(200, STORE.snapshot())
        else:
            self._send(404, {"error": "not found"})

    # ── Sesión con Google ──
    def _auth_route(self, path, data):
        if path == "/api/auth/status":
            return self._send(200, refresh_auth(network=True))

        if path == "/api/auth/client":
            ytauth.save_client(data.get("client_id", ""), data.get("client_secret", ""))
            return self._send(200, refresh_auth(network=False))

        if path == "/api/auth/client-file":
            chosen = pick_file_native(str(Path.home()), "Elige el JSON del cliente OAuth")
            if not chosen:
                return self._send(200, {**STORE.auth, "picked": False})
            ytauth.save_client_from_file(chosen)
            return self._send(200, {**refresh_auth(network=False), "picked": True})

        if path == "/api/auth/login":
            if STORE.auth.get("busy"):
                return self._send(409, {"error": "Ya hay un inicio de sesión en curso"})
            if not ytauth.load_client().get("client_id"):
                return self._send(400, {"error": "Configura antes tu cliente OAuth de Google."})

            def worker():
                try:
                    ytauth.login()
                    refresh_auth(network=True)
                except AuthError as e:
                    with STORE.lock:
                        STORE.auth["busy"] = False
                        STORE.auth["error"] = str(e)
                except Exception as e:  # noqa: BLE001
                    with STORE.lock:
                        STORE.auth["busy"] = False
                        STORE.auth["error"] = str(e)

            with STORE.lock:
                STORE.auth["busy"] = True
                STORE.auth["error"] = ""
            threading.Thread(target=worker, daemon=True).start()
            return self._send(200, {"ok": True})

        if path == "/api/auth/logout":
            ytauth.logout()
            with STORE.lock:
                STORE.channel = None
                STORE.videos = {}
                STORE.order = []
            return self._send(200, refresh_auth(network=False))

        return None

    def do_POST(self):
        try:
            data = self._read_json()

            if self.path.startswith("/api/auth/"):
                if self._auth_route(self.path, data) is None:
                    self._send(404, {"error": "not found"})
                return

            if self.path == "/api/scan-mine":
                if STORE.scan["running"]:
                    return self._send(409, {"error": "Ya hay un escaneo en curso"})
                if not ytauth.signed_in():
                    return self._send(401, {"error": "Inicia sesión con Google primero."})
                threading.Thread(target=run_scan, args=("mine",), daemon=True).start()
                self._send(200, {"ok": True})

            elif self.path == "/api/scan":
                ch = (data.get("channel") or "").strip()
                opts = data.get("options") or {}
                with STORE.lock:
                    for k in ("cookies_browser", "cookies_file"):
                        if k in opts:
                            STORE.options[k] = opts[k]
                if not ch:
                    return self._send(400, {"error": "Falta el canal"})
                if STORE.scan["running"]:
                    return self._send(409, {"error": "Ya hay un escaneo en curso"})
                threading.Thread(target=run_scan, args=("public", ch), daemon=True).start()
                self._send(200, {"ok": True})

            elif self.path == "/api/options":
                with STORE.lock:
                    STORE.options.update({k: v for k, v in data.items() if k in STORE.options})
                    if data.get("dest"):
                        STORE.dest = data["dest"]
                self._send(200, {"ok": True, "options": STORE.options, "dest": STORE.dest})

            elif self.path == "/api/dest":
                # ruta escrita a mano (alternativa al selector nativo)
                p = (data.get("dest") or "").strip()
                if not p:
                    return self._send(400, {"error": "Ruta vacía"})
                try:
                    Path(p).expanduser().mkdir(parents=True, exist_ok=True)
                except (OSError, ValueError) as e:
                    return self._send(400, {"error": f"No se puede usar esa ruta: {e}"})
                with STORE.lock:
                    STORE.dest = str(Path(p).expanduser())
                self._send(200, {"dest": STORE.dest})

            elif self.path == "/api/download":
                ids = data.get("ids") or []
                if STORE.running:
                    return self._send(409, {"error": "Ya hay descargas en curso"})
                if not ids:
                    return self._send(400, {"error": "Sin selección"})
                try:
                    Path(STORE.dest).mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    return self._send(400, {"error": f"No se puede escribir en el destino: {e}"})
                threading.Thread(target=run_downloads, args=(ids,), daemon=True).start()
                self._send(200, {"ok": True})

            elif self.path == "/api/pick-folder":
                chosen = pick_folder_native(STORE.dest)
                if chosen:
                    with STORE.lock:
                        STORE.dest = chosen
                self._send(200, {"dest": STORE.dest, "picked": bool(chosen)})

            elif self.path == "/api/pick-cookies":
                chosen = pick_file_native(str(Path.home()), "Elige tu archivo cookies.txt")
                if chosen:
                    with STORE.lock:
                        STORE.options["cookies_file"] = chosen
                self._send(200, {"cookies_file": STORE.options["cookies_file"], "picked": bool(chosen)})

            elif self.path == "/api/pause":
                with STORE.lock:
                    STORE.paused = not STORE.paused
                self._send(200, {"paused": STORE.paused})

            elif self.path == "/api/stop":
                with STORE.lock:
                    STORE.stop_flag = True
                    STORE.paused = False
                self._send(200, {"ok": True})

            else:
                self._send(404, {"error": "not found"})
        except AuthError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description="Archivador de canal de YouTube")
    ap.add_argument("--port", type=int, default=8717)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    refresh_auth(network=False)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"\n  ▶ Archivador de canal en  {url}")
    print(f"  ▶ Destino por defecto:    {STORE.dest}")
    if not FFMPEG:
        print("  ⚠ ffmpeg no está en el PATH: se descargará el mejor archivo ya")
        print("    combinado (calidad limitada) y los subtítulos irán aparte.")
    print("  ▶ Ctrl+C para salir.\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrando…")
        srv.shutdown()


if __name__ == "__main__":
    main()
