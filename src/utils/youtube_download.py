"""Utilitário para descarregar áudio de URLs do YouTube via yt-dlp."""

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


YOUTUBE_URL_RE = re.compile(
    r'^(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)'
    r'[A-Za-z0-9_\-]{11}'
)


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_RE.match(url.strip()))


def download_youtube_audio(url: str, upload_folder: str) -> dict:
    """
    Descarrega o melhor stream de áudio do YouTube e converte para WAV.

    Args:
        url: URL do vídeo YouTube.
        upload_folder: Pasta de destino (UPLOAD_FOLDER da app).

    Returns:
        Dict com keys: filepath, title, file_size, mime_type, original_filename.

    Raises:
        ValueError: Se o URL não for um URL YouTube válido.
        RuntimeError: Se o yt-dlp não conseguir descarregar ou não gerar WAV.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp não está instalado. Adiciona 'yt-dlp' ao requirements.txt.")

    if not is_youtube_url(url):
        raise ValueError(f"URL inválido ou não suportado: {url}")

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    work_dir = Path(upload_folder) / f"yt_{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(work_dir / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    logger.info(f"[youtube_download] A descarregar: {url}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        raw_title = info.get("title") or "YouTube Video"

    wavs = sorted(work_dir.glob("*.wav"))
    if not wavs:
        raise RuntimeError("yt-dlp não gerou ficheiro WAV. Verifica se o ffmpeg está instalado.")

    wav_path = wavs[0]
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', raw_title)[:200]
    final_filename = f"{timestamp}_{safe_title}.wav"
    final_path = Path(upload_folder) / final_filename
    wav_path.rename(final_path)

    # Limpar pasta temporária
    try:
        work_dir.rmdir()
    except OSError:
        pass

    file_size = final_path.stat().st_size
    logger.info(f"[youtube_download] Concluído → {final_filename} ({file_size // 1024} KB)")

    return {
        "filepath": str(final_path),
        "title": raw_title,
        "file_size": file_size,
        "mime_type": "audio/wav",
        "original_filename": final_filename,
    }
