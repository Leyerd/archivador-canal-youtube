#!/usr/bin/env python3
"""
Archivador de canal — descargador y organizador de videos de YouTube.

Backend multiplataforma (Linux / macOS / Windows). Sirve la interfaz web
(index.html, misma estética que la maqueta) y realiza las descargas reales
con yt-dlp. La UI se abre sola en el navegador.

Uso:
    python3 app.py
    python3 app.py --port 8717 --no-browser

Dependencias: yt-dlp (Python module) y ffmpeg en el PATH.
"""

import argparse
import json
import os
import re
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

# ─────────────────────────── yt-dlp ───────────────────────────
try:
    import yt_dlp
except ImportError:
    print("\n  ✗ Falta yt-dlp.  Instálalo con:  pip install yt-dlp\n", file=sys.stderr)
    sys.exit(1)


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
        self.channel = None          # {name, handle, avatar}
        self.videos = {}             # id -> dict
        self.order = []              # orden de escaneo
        self.running = False
        self.paused = False
        self.stop_flag = False
        self.dest = default_dest()
        self.options = {
            "mode": "video",
            "quality": 1080,
            "subs": True,
            "meta": True,
            "chapters": False,
            "concurrency": 3,
            "cookies_browser": "",   # "", "firefox", "chrome", "brave", ...
            "by_date": True,
        }
        self.executor = None

    def snapshot(self):
        with self.lock:
            return {
                "channel": self.channel,
                "videos": [self.videos[i] for i in self.order if i in self.videos],
                "running": self.running,
                "paused": self.paused,
                "dest": self.dest,
                "options": self.options,
            }


STORE = Store()


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


def scan_channel(text: str) -> dict:
    url = build_channel_url(text)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
    }
    cb = STORE.options.get("cookies_browser")
    if cb:
        ydl_opts["cookiesfrombrowser"] = (cb,)

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
    initials = "".join(w[0] for w in re.findall(r"\w+", name)[:2]).upper() or "MC"

    videos = {}
    order = []
    for idx, e in enumerate(flat):
        vid = e.get("id") or f"v{idx}"
        duration = int(e.get("duration") or 0)
        date = e.get("upload_date")  # YYYYMMDD o None
        videos[vid] = {
            "id": vid,
            "url": e.get("url") or e.get("webpage_url") or f"https://youtu.be/{vid}",
            "title": e.get("title") or "(sin título)",
            "duration": duration,
            "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date and len(date) == 8 else "",
            "status": "queued",
            "prog": 0.0,
            "rate": 0.0,
            "size": int(e.get("filesize") or e.get("filesize_approx") or 0),
            "sel": True,
        }
        order.append(vid)

    with STORE.lock:
        STORE.channel = {"name": name, "handle": handle, "avatar": initials}
        STORE.videos = videos
        STORE.order = order

    return STORE.snapshot()


# ─────────────────────────── Descarga ───────────────────────────
def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip() or "Canal"


def make_progress_hook(vid: str):
    def hook(d):
        if STORE.stop_flag:
            raise yt_dlp.utils.DownloadCancelled()
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


def ydl_opts_for(vid: str) -> dict:
    o = STORE.options
    ch = STORE.channel["name"] if STORE.channel else "Canal"
    base = Path(STORE.dest) / safe_name(ch)
    if o["by_date"]:
        tmpl = str(base / "%(upload_date>%Y-%m-%d)s - %(title)s [%(id)s].%(ext)s")
    else:
        tmpl = str(base / "%(title)s [%(id)s].%(ext)s")

    opts = {
        "outtmpl": tmpl,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noprogress": True,
        "progress_hooks": [make_progress_hook(vid)],
        "writethumbnail": o["meta"],
        "postprocessors": [],
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
    }
    if o.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (o["cookies_browser"],)

    if o["mode"] == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"].append(
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
        )
    else:
        q = o["quality"]
        opts["format"] = f"bv*[height<={q}]+ba/b[height<={q}]/b"
        opts["merge_output_format"] = "mp4"

    if o["subs"]:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["all"]
        opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    if o["meta"]:
        opts["postprocessors"].append(
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": o["chapters"]}
        )
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
    elif o["chapters"]:
        opts["postprocessors"].append({"key": "FFmpegMetadata", "add_chapters": True})

    return opts


def download_one(vid: str):
    while STORE.paused and not STORE.stop_flag:
        time.sleep(0.3)
    if STORE.stop_flag:
        return
    with STORE.lock:
        v = STORE.videos.get(vid)
        if not v or not v["sel"] or v["status"] not in ("queued",):
            return
        url = v["url"]
        v["status"] = "downloading"
        v["prog"] = 0.0
    try:
        with yt_dlp.YoutubeDL(ydl_opts_for(vid)) as ydl:
            ydl.download([url])
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v:
                v["status"] = "done"
                v["prog"] = 100.0
                v["rate"] = 0.0
                v["sel"] = False
    except yt_dlp.utils.DownloadCancelled:
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v and v["status"] != "done":
                v["status"] = "queued"
                v["prog"] = 0.0
    except Exception as e:  # noqa: BLE001
        with STORE.lock:
            v = STORE.videos.get(vid)
            if v:
                v["status"] = "error"
                v["error"] = str(e)[:200]
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

    with ThreadPoolExecutor(max_workers=conc) as ex:
        futures = [ex.submit(download_one, i) for i in ids]
        for f in futures:
            f.result()

    with STORE.lock:
        STORE.running = False
        STORE.paused = False


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

    def do_POST(self):
        try:
            if self.path == "/api/scan":
                data = self._read_json()
                ch = (data.get("channel") or "").strip()
                opts = data.get("options") or {}
                with STORE.lock:
                    if "cookies_browser" in opts:
                        STORE.options["cookies_browser"] = opts["cookies_browser"]
                if not ch:
                    return self._send(400, {"error": "Falta el canal"})
                snap = scan_channel(ch)
                self._send(200, snap)

            elif self.path == "/api/options":
                data = self._read_json()
                with STORE.lock:
                    STORE.options.update({k: v for k, v in data.items() if k in STORE.options})
                    if "dest" in data and data["dest"]:
                        STORE.dest = data["dest"]
                self._send(200, {"ok": True, "options": STORE.options, "dest": STORE.dest})

            elif self.path == "/api/download":
                data = self._read_json()
                ids = data.get("ids") or []
                if STORE.running:
                    return self._send(409, {"error": "Ya hay descargas en curso"})
                if not ids:
                    return self._send(400, {"error": "Sin selección"})
                threading.Thread(target=run_downloads, args=(ids,), daemon=True).start()
                self._send(200, {"ok": True})

            elif self.path == "/api/pick-folder":
                chosen = pick_folder_native(STORE.dest)
                if chosen:
                    with STORE.lock:
                        STORE.dest = chosen
                self._send(200, {"dest": STORE.dest, "picked": bool(chosen)})

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
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description="Archivador de canal de YouTube")
    ap.add_argument("--port", type=int, default=8717)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"\n  ▶ Archivador de canal en  {url}")
    print(f"  ▶ Destino por defecto:    {STORE.dest}")
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
