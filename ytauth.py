#!/usr/bin/env python3
"""Inicio de sesión con Google (OAuth 2.0 + PKCE) y acceso a la YouTube Data API v3.

Solo usa la biblioteca estándar de Python: no añade dependencias al proyecto.

Sirve para dos cosas:

1. Identificarte con la **cuenta de Google dueña del canal**, mediante el flujo
   de aplicación de escritorio (redirección al bucle local 127.0.0.1).
2. Listar **todos** los videos subidos a ese canal —incluidos los **privados**
   y **no listados**—, que es algo que la pestaña pública `/videos` no muestra.

Los datos se guardan en la carpeta de configuración del usuario:

    client.json   id y secreto del cliente OAuth (los crea el propio usuario)
    token.json    tokens de acceso/refresco de la sesión

Nota: el token de OAuth sirve para *listar* (Data API). La *descarga* del
archivo de video de un video **privado** sigue necesitando las cookies del
navegador, porque YouTube no expone los flujos multimedia por la API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/youtube/v3/"

# Solo lectura: la app nunca puede modificar ni borrar nada de tu canal.
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

LOGIN_TIMEOUT = 300  # segundos que esperamos a que autorices en el navegador


class AuthError(Exception):
    """Error de autenticación o de la Data API, con mensaje legible."""


# ─────────────────────────── Almacenamiento ───────────────────────────
def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
        d = base / "ArchivadorCanal"
    elif sys.platform == "darwin":
        d = Path.home() / "Library/Application Support/ArchivadorCanal"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        d = base / "archivador-canal"
    d.mkdir(parents=True, exist_ok=True)
    return d


CLIENT_FILE = "client.json"
TOKEN_FILE = "token.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:  # el token es sensible: permisos solo para el usuario
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_client() -> dict:
    return _read_json(config_dir() / CLIENT_FILE)


def save_client(client_id: str, client_secret: str) -> dict:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise AuthError(
            "El ID de cliente no parece válido: debe terminar en "
            "«.apps.googleusercontent.com»."
        )
    data = {"client_id": client_id, "client_secret": client_secret}
    _write_json(config_dir() / CLIENT_FILE, data)
    return data


def save_client_from_file(path: str) -> dict:
    """Acepta el `client_secret_*.json` que descargas de Google Cloud Console."""
    raw = _read_json(Path(path))
    node = raw.get("installed") or raw.get("web") or raw
    cid = node.get("client_id", "")
    csec = node.get("client_secret", "")
    if not cid:
        raise AuthError(
            "Ese archivo no contiene un client_id. Descarga el JSON del cliente "
            "OAuth («Aplicación de escritorio») desde Google Cloud Console."
        )
    return save_client(cid, csec)


def clear_client() -> None:
    (config_dir() / CLIENT_FILE).unlink(missing_ok=True)


def load_token() -> dict:
    return _read_json(config_dir() / TOKEN_FILE)


def save_token(tok: dict) -> None:
    _write_json(config_dir() / TOKEN_FILE, tok)


def logout() -> None:
    """Cierra la sesión local y revoca el permiso en Google si se puede."""
    tok = load_token()
    rt = tok.get("refresh_token")
    (config_dir() / TOKEN_FILE).unlink(missing_ok=True)
    if rt:
        try:
            _post_form(REVOKE_ENDPOINT, {"token": rt})
        except Exception:  # noqa: BLE001
            pass  # revocar es best-effort: la sesión local ya está borrada


# ─────────────────────────── HTTP helpers ───────────────────────────
def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise AuthError(_google_error(body)) from None
    except urllib.error.URLError as e:
        raise AuthError(f"Sin conexión con Google: {e.reason}") from None
    return json.loads(body) if body.strip() else {}


def _google_error(body: str) -> str:
    try:
        j = json.loads(body)
    except Exception:  # noqa: BLE001
        return body[:300]
    if isinstance(j.get("error"), dict):
        err = j["error"]
        msg = err.get("message") or "Error de la API de Google"
        reasons = {d.get("reason", "") for d in (err.get("errors") or [])}
        if "accessNotConfigured" in reasons or "has not been used" in msg:
            return (
                "La YouTube Data API v3 no está habilitada en tu proyecto de "
                "Google Cloud. Actívala y espera un par de minutos. Detalle: " + msg
            )
        if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
            return (
                "Se agotó la cuota diaria de la YouTube Data API de tu proyecto. "
                "Vuelve a intentarlo mañana o pide más cuota."
            )
        return msg
    desc = j.get("error_description") or j.get("error") or "Error de OAuth"
    if j.get("error") == "invalid_client":
        return (
            "Credenciales de cliente inválidas: revisa el ID y el secreto del "
            "cliente OAuth (tipo «Aplicación de escritorio»)."
        )
    if j.get("error") == "invalid_grant":
        return (
            "La sesión caducó o fue revocada (los proyectos en modo «Prueba» "
            "caducan a los 7 días). Vuelve a iniciar sesión."
        )
    return str(desc)


# ─────────────────────────── Flujo de login ───────────────────────────
class _LoginState:
    """Resultado compartido entre el hilo del login y el servidor de callback."""

    def __init__(self):
        self.code = None
        self.error = None
        self.state = secrets.token_urlsafe(24)
        self.done = threading.Event()


def _callback_handler(st: _LoginState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencio
            pass

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path not in ("/", "/oauth2callback"):
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            got_state = (q.get("state") or [""])[0]
            if got_state != st.state:
                st.error = "Respuesta de Google inesperada (state no coincide)."
            elif q.get("error"):
                code = (q.get("error") or [""])[0]
                st.error = (
                    "Cancelaste el permiso en Google."
                    if code == "access_denied"
                    else f"Google devolvió un error: {code}"
                )
            else:
                st.code = (q.get("code") or [""])[0]
                if not st.code:
                    st.error = "Google no devolvió el código de autorización."

            ok = st.code is not None
            title = "Sesión iniciada" if ok else "No se pudo iniciar sesión"
            msg = (
                "Ya puedes cerrar esta pestaña y volver al Archivador."
                if ok
                else (st.error or "Inténtalo de nuevo desde la app.")
            )
            html = f"""<!doctype html><html lang="es"><meta charset="utf-8">
<title>{title}</title>
<body style="margin:0;height:100vh;display:grid;place-items:center;
background:#0f0f0f;color:#f1f1f1;font:16px/1.6 system-ui,sans-serif">
<div style="text-align:center;max-width:420px;padding:32px">
<div style="font-size:46px">{'✓' if ok else '✕'}</div>
<h1 style="font-size:20px;margin:12px 0 6px">{title}</h1>
<p style="color:#aaa;margin:0">{msg}</p></div></body></html>"""
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            st.done.set()

    return Handler


def login(open_browser=True, timeout=LOGIN_TIMEOUT) -> dict:
    """Ejecuta el flujo completo (bloqueante) y guarda los tokens.

    Devuelve el token guardado. Lanza AuthError con un mensaje legible."""
    client = load_client()
    if not client.get("client_id"):
        raise AuthError(
            "Falta el cliente OAuth. Pega tu ID y secreto de cliente (o el "
            "archivo JSON de Google Cloud Console) antes de iniciar sesión."
        )

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    st = _LoginState()
    # Puerto efímero en el bucle local: los clientes de escritorio de Google
    # aceptan cualquier puerto de 127.0.0.1 como URI de redirección.
    try:
        srv = HTTPServer(("127.0.0.1", 0), _callback_handler(st))
    except OSError as e:
        raise AuthError(f"No se pudo abrir el puerto local del login: {e}") from None
    port = srv.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/oauth2callback"

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        params = {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": st.state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",   # queremos refresh_token
            "prompt": "consent",        # fuerza refresh_token también al re-loguear
        }
        url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)
        if open_browser:
            webbrowser.open(url)

        if not st.done.wait(timeout):
            raise AuthError(
                "Se agotó el tiempo de espera del login. Vuelve a intentarlo."
            )
        if st.error:
            raise AuthError(st.error)

        tok = _post_form(
            TOKEN_ENDPOINT,
            {
                "code": st.code,
                "client_id": client["client_id"],
                "client_secret": client.get("client_secret", ""),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
    finally:
        srv.shutdown()
        srv.server_close()

    if not tok.get("access_token"):
        raise AuthError("Google no devolvió un token de acceso.")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    save_token(tok)
    return tok


def access_token() -> str:
    """Devuelve un token válido, refrescándolo si hace falta."""
    tok = load_token()
    if not tok.get("access_token") and not tok.get("refresh_token"):
        raise AuthError("No has iniciado sesión con Google.")
    if tok.get("access_token") and time.time() < float(tok.get("expires_at", 0)):
        return tok["access_token"]

    rt = tok.get("refresh_token")
    if not rt:
        raise AuthError("La sesión caducó. Vuelve a iniciar sesión con Google.")
    client = load_client()
    fresh = _post_form(
        TOKEN_ENDPOINT,
        {
            "refresh_token": rt,
            "client_id": client.get("client_id", ""),
            "client_secret": client.get("client_secret", ""),
            "grant_type": "refresh_token",
        },
    )
    tok["access_token"] = fresh.get("access_token", "")
    tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 60
    if fresh.get("refresh_token"):
        tok["refresh_token"] = fresh["refresh_token"]
    save_token(tok)
    if not tok["access_token"]:
        raise AuthError("No se pudo refrescar la sesión. Inicia sesión de nuevo.")
    return tok["access_token"]


def signed_in() -> bool:
    tok = load_token()
    return bool(tok.get("refresh_token") or tok.get("access_token"))


# ─────────────────────────── Data API ───────────────────────────
def api(path: str, **params) -> dict:
    """GET a la YouTube Data API v3 con el token de la sesión."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(
        API_BASE + path + "?" + qs,
        headers={
            "Authorization": f"Bearer {access_token()}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise AuthError(_google_error(e.read().decode("utf-8", "replace"))) from None
    except urllib.error.URLError as e:
        raise AuthError(f"Sin conexión con la API de YouTube: {e.reason}") from None
    except socket.timeout:
        raise AuthError("La API de YouTube tardó demasiado en responder.") from None


_DUR = re.compile(
    r"P(?:(?P<d>\d+)D)?T?(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?"
)


def parse_duration(iso: str) -> int:
    """«PT1H2M3S» → segundos. Los directos sin fin devuelven 0."""
    m = _DUR.fullmatch((iso or "").strip())
    if not m:
        return 0
    g = {k: int(v or 0) for k, v in m.groupdict().items()}
    return g["d"] * 86400 + g["h"] * 3600 + g["m"] * 60 + g["s"]


def my_channel() -> dict:
    """Canal de la cuenta con la sesión iniciada."""
    data = api("channels", part="snippet,contentDetails,statistics", mine="true")
    items = data.get("items") or []
    if not items:
        raise AuthError(
            "Esa cuenta de Google no tiene ningún canal de YouTube. Inicia "
            "sesión con la cuenta dueña del canal."
        )
    it = items[0]
    sn = it.get("snippet") or {}
    return {
        "id": it.get("id", ""),
        "name": sn.get("title") or "Mi canal",
        "handle": (sn.get("customUrl") or "").strip() or it.get("id", ""),
        "thumb": ((sn.get("thumbnails") or {}).get("default") or {}).get("url", ""),
        "uploads": ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}).get(
            "uploads", ""
        ),
        "count": int((it.get("statistics") or {}).get("videoCount") or 0),
    }


def _uploads_ids(uploads_playlist: str, progress=None) -> list:
    """IDs de la lista «subidas» del canal (incluye no listados y privados)."""
    ids, page = [], None
    while True:
        data = api(
            "playlistItems",
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page,
        )
        for it in data.get("items") or []:
            vid = ((it.get("contentDetails") or {})).get("videoId")
            if vid:
                ids.append(vid)
        if progress:
            progress(f"Leyendo tu canal… {len(ids)} videos")
        page = data.get("nextPageToken")
        if not page:
            return ids


def _search_mine_ids(progress=None, seen=0) -> list:
    """Refuerzo: búsqueda «forMine», la vía documentada para ver TODO lo subido.

    Algunas cuentas no devuelven los privados en la lista de subidas; esta
    llamada sí los incluye. Cuesta más cuota, por eso se usa como complemento."""
    ids, page = [], None
    while True:
        data = api(
            "search",
            part="id",
            forMine="true",
            type="video",
            maxResults=50,
            order="date",
            pageToken=page,
        )
        for it in data.get("items") or []:
            vid = (it.get("id") or {}).get("videoId")
            if vid:
                ids.append(vid)
        if progress:
            progress(f"Buscando videos ocultos… {max(seen, len(ids))} videos")
        page = data.get("nextPageToken")
        if not page:
            return ids


def _details(ids: list, progress=None) -> list:
    """Metadatos completos en lotes de 50."""
    out = []
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        data = api(
            "videos",
            part="snippet,contentDetails,status,statistics,liveStreamingDetails",
            id=",".join(batch),
            maxResults=50,
        )
        for it in data.get("items") or []:
            sn = it.get("snippet") or {}
            th = sn.get("thumbnails") or {}
            thumb = (
                (th.get("medium") or th.get("high") or th.get("default") or {})
            ).get("url", "")
            published = (sn.get("publishedAt") or "")[:10]
            out.append(
                {
                    "id": it.get("id", ""),
                    "url": f"https://www.youtube.com/watch?v={it.get('id','')}",
                    "title": sn.get("title") or "(sin título)",
                    "duration": parse_duration(
                        (it.get("contentDetails") or {}).get("duration", "")
                    ),
                    "date": published,
                    "privacy": (it.get("status") or {}).get("privacyStatus", "public"),
                    "thumb": thumb,
                }
            )
        if progress:
            progress(f"Leyendo detalles… {len(out)}/{len(ids)}")
    return out


def list_all_videos(progress=None) -> tuple:
    """(canal, videos) con TODO lo subido: público, no listado y privado."""
    ch = my_channel()
    ids = []
    if ch.get("uploads"):
        ids = _uploads_ids(ch["uploads"], progress)
    try:
        extra = _search_mine_ids(progress, seen=len(ids))
    except AuthError:
        extra = []  # sin cuota o sin permiso: seguimos con la lista de subidas
    seen, merged = set(), []
    for vid in ids + extra:
        if vid not in seen:
            seen.add(vid)
            merged.append(vid)
    videos = _details(merged, progress)
    # más recientes primero (la API ya viene casi ordenada, pero lo aseguramos)
    videos.sort(key=lambda v: v["date"], reverse=True)
    return ch, videos


def status() -> dict:
    """Resumen para la interfaz."""
    client = load_client()
    st = {
        "has_client": bool(client.get("client_id")),
        "client_id": client.get("client_id", ""),
        "signed_in": signed_in(),
        "account": None,
        "error": "",
    }
    if st["signed_in"]:
        try:
            ch = my_channel()
            st["account"] = {"name": ch["name"], "handle": ch["handle"], "thumb": ch["thumb"]}
        except AuthError as e:
            st["error"] = str(e)
    return st
