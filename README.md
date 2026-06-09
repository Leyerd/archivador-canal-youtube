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
En **Sesión / cookies** elige tu navegador (Firefox, Chrome, Brave…). yt-dlp usará sus
cookies para acceder a videos privados o no listados de la cuenta con la que tengas
sesión iniciada en ese navegador. Cierra el navegador antes de descargar si te da
errores de base de datos bloqueada.

## ⚖️ Aviso legal

Pensado para **archivar contenido propio** o con permiso. Respeta los Términos de
Servicio de YouTube y los derechos de autor. El uso de esta herramienta es tu
responsabilidad.

## 🛠️ Stack

- **Backend:** Python (biblioteca estándar) + `yt-dlp` + `ffmpeg`.
- **Frontend:** HTML/CSS/JS sin dependencias, servido localmente.

## 📄 Licencia

[MIT](LICENSE)
