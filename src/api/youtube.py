"""Endpoint para importar gravações a partir de URLs do YouTube."""

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user

from src.database import db
from src.models import Recording
from src.services.job_queue import job_queue
from src.utils.youtube_download import download_youtube_audio, is_youtube_url
from src.utils.file_hash import compute_file_sha256
from src.config.app_config import ASR_MIN_SPEAKERS, ASR_MAX_SPEAKERS

youtube_bp = Blueprint('youtube', __name__)
logger = logging.getLogger(__name__)


@youtube_bp.route('/api/recordings/from-youtube', methods=['POST'])
@login_required
def create_from_youtube():
    """
    Importa uma gravação a partir de um URL do YouTube.

    Body JSON:
        youtube_url  (str, obrigatório)  — URL do vídeo YouTube
        language     (str, opcional)     — código de língua, ex. "pt" (default: "pt")
        title        (str, opcional)     — título personalizado
        notes        (str, opcional)     — notas

    Returns:
        202 com o Recording criado, ou erro 4xx/5xx.
    """
    data = request.get_json(silent=True) or {}

    youtube_url = (data.get('youtube_url') or '').strip()
    if not youtube_url:
        return jsonify({'error': 'Campo obrigatório em falta: youtube_url'}), 400

    if not is_youtube_url(youtube_url):
        return jsonify({'error': 'URL inválido. Fornece um URL YouTube válido.'}), 400

    language = data.get('language', 'pt')
    user_title = (data.get('title') or '').strip() or None
    notes = data.get('notes')

    upload_folder = current_app.config.get('UPLOAD_FOLDER', '/tmp')

    try:
        logger.info(f"[youtube] Utilizador {current_user.id} a importar: {youtube_url}")
        result = download_youtube_audio(youtube_url, upload_folder)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        logger.error(f"[youtube] Falha no download: {e}")
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        logger.exception(f"[youtube] Erro inesperado no download: {e}")
        return jsonify({'error': 'Erro ao descarregar o vídeo. Tenta novamente.'}), 500

    file_hash = None
    duplicate_warning = None
    try:
        file_hash = compute_file_sha256(result['filepath'])
        existing = Recording.query.filter_by(
            user_id=current_user.id, file_hash=file_hash
        ).first()
        if existing:
            duplicate_warning = {
                'existing_recording_id': existing.id,
                'existing_title': existing.title,
                'existing_created_at': existing.created_at.isoformat() if existing.created_at else None,
            }
    except Exception as e:
        logger.warning(f"[youtube] Não foi possível calcular hash: {e}")

    recording = Recording(
        audio_path=result['filepath'],
        original_filename=result['original_filename'],
        title=user_title or result['title'],
        file_size=result['file_size'],
        status='PENDING',
        user_id=current_user.id,
        mime_type=result['mime_type'],
        notes=notes,
        processing_source='youtube',
        source_url=youtube_url,
        file_hash=file_hash,
    )
    db.session.add(recording)
    db.session.commit()

    job_params = {
        'language': language,
        'min_speakers': ASR_MIN_SPEAKERS,
        'max_speakers': ASR_MAX_SPEAKERS,
    }
    job_queue.enqueue(
        user_id=current_user.id,
        recording_id=recording.id,
        job_type='transcribe',
        params=job_params,
        is_new_upload=True,
    )

    response = recording.to_dict(viewer_user=current_user)
    if duplicate_warning:
        response['duplicate_warning'] = duplicate_warning

    logger.info(f"[youtube] Recording {recording.id} criado e enfileirado para transcrição")
    return jsonify(response), 202
