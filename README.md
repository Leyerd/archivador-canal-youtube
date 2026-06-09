<div align="center">

# 🎬 Archivador de canal

**Descarga y organiza automáticamente todos los videos de un canal de YouTube.**
Multiplataforma (Linux · macOS · Windows), con la estética de YouTube y modo claro/oscuro.

</div>

---

## ✨ Características

- **Escanea un canal entero** pegando su enlace o `@usuario`.
- **Descarga real** con [yt-dlp](https://github.com/yt-dlp/yt-dlp): video (hasta 4K) o solo audio.
- **Organiza automáticamente** en `Destino/Nombre del canal/`, con prefijo de fecha `AAAA-MM-DD` opcional.
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

El lanzador crea un entorno virtual, instala `yt-dlp` y abre la app en tu navegador
(`http://127.0.0.1:8717`). Para cambiar el puerto: `./run.sh --port 9000`.

### Manual
```bash
pip install -r requirements.txt
python app.py
```

## 🖱️ Cómo funciona

1. Pega el **enlace** o el **`@usuario`** de tu canal y pulsa **Escanear canal**.
2. Marca los videos que quieras (o **Seleccionar todo**), ajusta calidad/formato/extras en el panel derecho.
3. Elige la **carpeta de destino** y si quieres **organizar por fecha**.
4. Pulsa **Descargar selección**. Puedes **pausar/reanudar** o **detener** en cualquier momento.

Los archivos quedan en:
```
Carpeta elegida/
└── Nombre del canal/
    ├── 2026-05-31 - Título del video [VIDEO_ID].mp4
    └── 2026-05-28 - Otro video [VIDEO_ID].mp4
```

### 🔐 Videos privados / tu propia cuenta
Para descargar videos **privados o no listados** de tu canal, identifícate con la
**cuenta de Google de ese canal**:

1. Inicia sesión en YouTube **en tu navegador** con la cuenta dueña del canal.
2. En el panel **Sesión · videos privados** selecciona ese navegador
   (Firefox, Chrome, Brave, Edge…). La app usará sus cookies.
3. Pega el **enlace del video privado/no listado** o el de una **lista privada**
   (la pestaña pública `/videos` de un canal no muestra los privados, así que para
   esos usa el enlace directo o una playlist).

> 💡 Si tu navegador **cifra las cookies** (común en Chrome reciente) y falla, usa el
> botón **«Usar archivo cookies.txt»**: expórtalas con una extensión tipo
> *Get cookies.txt* y selecciona el archivo. Cierra el navegador antes de descargar
> si ves errores de "base de datos bloqueada".

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

## 🛠️ Stack

- **Backend:** Python (biblioteca estándar) + `yt-dlp` + `ffmpeg`.
- **Frontend:** HTML/CSS/JS sin dependencias, servido localmente.

## 📄 Licencia

[MIT](LICENSE)
