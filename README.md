<div align="center">

# 🎬 Archivador de canal

**Descarga y organiza automáticamente todos los videos de un canal de YouTube.**
Multiplataforma (Linux · macOS · Windows), con la estética de YouTube y modo claro/oscuro.

</div>

---

## ✨ Características

- **Entra con tu cuenta de Google** y lista **todos** los videos de tu canal:
  públicos, **no listados** y **privados** (la pestaña pública no los muestra).
- **Escanea un canal entero** pegando su enlace o `@usuario`.
- **Descarga real** con [yt-dlp](https://github.com/yt-dlp/yt-dlp): video (hasta 4K) o solo audio.
- **Organiza automáticamente** en `Destino/Nombre del canal/`, con prefijo de fecha `AAAA-MM-DD` opcional.
- **No repite descargas**: detecta lo ya bajado (registro + archivos en disco) y lo omite.
- **Elige dónde guardar** con un selector de carpeta nativo del sistema.
- **Extras**: subtítulos (todos los idiomas), miniatura + metadatos y capítulos incrustados.
- **Descargas simultáneas** configurables (1–8) con barra de progreso por video y global.
- **Tu propia cuenta**: usa las cookies de tu navegador para acceder a videos privados o no listados.
- **Interfaz** idéntica en los tres sistemas (se ejecuta en el navegador) con **modo oscuro**.

## 🚀 Uso rápido

**Requisito previo:** [Python 3.8+](https://www.python.org/) y, recomendado, [ffmpeg](https://ffmpeg.org/) en el PATH (para fusionar video+audio, subtítulos y miniaturas).

### Linux / macOS
```bash
./run.sh
```

### Windows
Doble clic en **`run.bat`** (o ejecútalo desde la terminal).

El lanzador crea un entorno virtual, instala `yt-dlp` y abre la app **en Chrome**
(`http://127.0.0.1:8717`), ocupando la ventana completa del navegador.

| Quiero… | Opción |
|---|---|
| Otro puerto | `--port 9000` |
| El navegador del sistema | `--browser default` |
| Otro navegador concreto | `--browser firefox` o `--browser "C:\ruta\navegador.exe"` |
| No abrir nada | `--no-browser` |

> 💡 Conviene usar el navegador donde tienes iniciada tu sesión de YouTube: la app
> lo reutiliza para el permiso de Google y para las cookies de los videos privados.

### ffmpeg

Sin ffmpeg la app funciona, pero YouTube solo entrega un archivo ya combinado
(normalmente 360p) y los subtítulos quedan en archivos sueltos. Para calidad
completa:

```
winget install Gyan.FFmpeg        # Windows
brew install ffmpeg               # macOS
sudo apt install ffmpeg           # Debian/Ubuntu
```

En Windows el `PATH` solo se refresca en ventanas nuevas, así que la app también
busca ffmpeg en las rutas habituales de instalación: no hace falta reiniciar nada.

### Manual
```bash
pip install -r requirements.txt
python app.py
```

## 🖱️ Cómo funciona

1. **Inicia sesión con Google** (panel derecho) y pulsa **Cargar todos mis videos**.
   Aparecerán también los **no listados** y **privados**, con su etiqueta.
   *(O bien, sin sesión: pega el enlace o `@usuario` de cualquier canal y pulsa
   **Escanear canal** para ver solo sus videos públicos.)*
2. Marca los videos que quieras (o **Seleccionar todo**), ajusta calidad/formato/extras en el panel derecho.
3. Elige la **carpeta de destino** (selector nativo o escribiendo la ruta) y si quieres **organizar por fecha**.
4. Pulsa **Descargar selección**. Puedes **pausar/reanudar** o **detener** en cualquier momento.

Los archivos quedan en:
```
Carpeta elegida/
└── Nombre del canal/
    ├── 2026-05-31 - Título del video [VIDEO_ID].mp4
    └── 2026-05-28 - Otro video [VIDEO_ID].mp4
```

### 🔐 Entrar con tu cuenta de Google (ver los videos ocultos)

La pestaña pública `/videos` de un canal **no muestra** los privados. Para verlos
todos, la app usa la **YouTube Data API v3** con tu propia cuenta. Google exige que
cada usuario use sus **propias credenciales OAuth**, así que hay que crearlas una
vez (es gratis y toma unos minutos):

1. Entra en [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto.
2. **APIs y servicios → Biblioteca**: activa la **YouTube Data API v3**.
3. **Pantalla de consentimiento**: tipo **Externo**; añade tu propio correo como
   **usuario de prueba**.
4. **Credenciales → Crear credenciales → ID de cliente de OAuth** → tipo
   **Aplicación de escritorio**.
5. En la app, panel **Cuenta de Google → Configurar acceso**: pega el **ID** y el
   **secreto**, o pulsa **Cargar client_secret.json** con el archivo descargado.
6. Pulsa **Iniciar sesión con Google**, autoriza en el navegador y luego
   **Cargar todos mis videos**.

> ❗ Si Google responde **«Acceso bloqueado · Error 401: invalid_client»** o
> *«The OAuth client was not found»*, el ID guardado no corresponde a ningún
> cliente real. Pulsa **quitar** junto al ID mostrado y pega el de tu proyecto.

Permisos que se piden: **solo lectura** (`youtube.readonly`). La app nunca puede
modificar ni borrar nada de tu canal. Los tokens se guardan solo en tu equipo
(`%APPDATA%\ArchivadorCanal` en Windows, `~/.config/archivador-canal` en Linux,
`~/Library/Application Support/ArchivadorCanal` en macOS) y se borran con **Salir**.

> ⏳ Mientras el proyecto esté en modo **«Prueba»**, Google caduca la sesión cada
> **7 días**: basta con volver a pulsar *Iniciar sesión*.

### 📥 Descargar los privados

Ojo con esta distinción, porque son dos permisos distintos:

| | Listar | Descargar |
|---|---|---|
| Públicos y **no listados** | sesión de Google (o escaneo público) | directo, sin nada más |
| **Privados** | sesión de Google | **hacen falta cookies del navegador** |

La API de Google deja *listar* tus privados, pero no expone sus flujos de video,
así que para bajarlos:

1. Inicia sesión en YouTube **en tu navegador** con la cuenta dueña del canal.
2. En el panel **Sesión del navegador** selecciona ese navegador
   (Firefox, Chrome, Brave, Edge…). La app usará sus cookies.

> 💡 Si tu navegador **cifra las cookies** (común en Chrome reciente) y falla, usa el
> botón **«Usar archivo cookies.txt»**: expórtalas con una extensión tipo
> *Get cookies.txt* y selecciona el archivo. Cierra el navegador antes de descargar
> si ves errores de "base de datos bloqueada".

### ♻️ Sin descargas duplicadas
Con **«Omitir ya descargados»** activado (por defecto), al escanear se marcan como
*ya descargado* los videos que ya tienes y no se vuelven a bajar. Lo detecta de dos
formas, así que funciona aunque cambies de equipo o borres el registro:

1. Un **registro** `.descargados.txt` dentro de la carpeta del canal (lo mantiene yt-dlp).
2. Un **rastreo de la carpeta** de destino: reconoce los archivos por el `[ID]` del
   nombre, así que basta con que el archivo exista.

Desactiva el interruptor si quieres **re-descargar** algo (sobrescribe lo existente).

## 🖥️ Instalar como app de escritorio (con icono)

Tras la primera ejecución (que prepara el entorno), puedes añadir un lanzador con icono:

| Sistema | Comando |
|---|---|
| **Linux** (Hyprland, GNOME, KDE…) | `./packaging/instalar-linux.sh` — aparece «Archivador de canal» en tu menú. Desinstalar: `./packaging/instalar-linux.sh --uninstall` |
| **Windows** | `powershell -ExecutionPolicy Bypass -File packaging\crear-acceso-windows.ps1` — crea accesos en Escritorio y menú Inicio |
| **macOS** | `./packaging/crear-app-macos.sh` — genera `Archivador de canal.app` en `/Applications` |

El icono está en `assets/` (SVG + PNG + `.ico` + `.icns`).

## ⚖️ Aviso legal

Pensado para **archivar contenido propio** o con permiso. Respeta los Términos de
Servicio de YouTube y los derechos de autor. El uso de esta herramienta es tu
responsabilidad.

## 🩹 Problemas resueltos

Si vienes de una versión anterior, esto es lo que fallaba:

- **La app no arrancaba en Windows.** La consola `cp1252` reventaba con los
  símbolos del mensaje de inicio (`UnicodeEncodeError`). Ahora la salida se fuerza
  a UTF-8 y `run.bat` fija la página de códigos.
- **Las descargas se caían con «429 Too Many Requests».** Los subtítulos se pedían
  en *todos* los idiomas (~200 pistas auto-traducidas por video). Ahora se piden
  idiomas concretos (`es,en` por defecto, configurable) y un fallo de subtítulos
  ya no arrastra al video: se reintenta sin ellos.
- **Cortes aleatorios de YouTube (403).** Ocurren de forma intermitente en las URLs
  de los flujos. Ahora se reintenta hasta 4 veces con espera creciente y volviendo
  a extraer la URL, que es lo único que lo cura.
- **Sin `ffmpeg` fallaba todo.** Ahora se detecta: se descarga el mejor archivo ya
  combinado, los subtítulos quedan aparte y la interfaz lo avisa.
- **Los archivos salían como `NA - Título`** cuando el escaneo no traía la fecha.
- **La interfaz se congelaba** durante el escaneo de canales grandes: ahora corre
  en segundo plano y muestra el avance.
- **No se podían ver los privados**, que es justo lo que hace la sesión de Google.

## 🛠️ Stack

- **Backend:** Python (biblioteca estándar) + `yt-dlp` + `ffmpeg`.
- **Frontend:** HTML/CSS/JS sin dependencias, servido localmente.
- **Sesión Google:** OAuth 2.0 con PKCE y YouTube Data API v3, implementados en
  `ytauth.py` **sin dependencias externas** (solo `urllib`/`http.server`).

## 📄 Licencia

[MIT](LICENSE)
