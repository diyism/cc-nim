"""Voice note transcription for messaging platforms.

Uses local faster-whisper for free, offline transcription.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol, cast

from loguru import logger

# Max file size in bytes (25 MB)
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024

# Lazy-loaded models: (model_name, device) -> model
_model_cache: dict[tuple[str, str], Any] = {}


class _WhisperModelLike(Protocol):
    def transcribe(
        self, audio: str, beam_size: int = 5
    ) -> tuple[Iterator[Any], Any]: ...


def _get_local_model(whisper_model: str, device: str) -> _WhisperModelLike:
    """Lazy-load faster-whisper model. Raises ImportError if not installed."""
    global _model_cache
    resolved = device if device in ("cpu", "cuda") else "auto"
    cache_key = (whisper_model, resolved)
    if cache_key not in _model_cache:
        try:
            from config.settings import get_settings

            token = get_settings().hf_token
            if token:
                os.environ["HF_TOKEN"] = token
            import importlib

            faster_whisper = importlib.import_module("faster_whisper")
            WhisperModel = faster_whisper.WhisperModel
            if resolved == "auto":
                # Try CUDA; fail fast if CUDA unavailable (no CPU fallback)
                _model_cache[cache_key] = WhisperModel(whisper_model, device="cuda")
            elif resolved == "cpu":
                _model_cache[cache_key] = WhisperModel(
                    whisper_model, device="cpu", compute_type="float32"
                )
            else:
                _model_cache[cache_key] = WhisperModel(whisper_model, device=resolved)
        except ImportError as e:
            raise ImportError(
                "Voice notes require the voice extra. Install with: uv sync --extra voice"
            ) from e
    return cast(_WhisperModelLike, _model_cache[cache_key])


def transcribe_audio(
    file_path: Path,
    mime_type: str,
    *,
    whisper_model: str = "base",
    whisper_device: str = "cpu",
) -> str:
    """
    Transcribe audio file to text using local faster-whisper.

    Args:
        file_path: Path to audio file (OGG, MP3, MP4, WAV, M4A supported)
        mime_type: MIME type of the audio (e.g. "audio/ogg")
        whisper_model: Model size: "tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo"
        whisper_device: "cpu" | "cuda" | "auto" (auto = try CUDA, fail fast; no fallback)

    Returns:
        Transcribed text

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file too large
        ImportError: If faster-whisper not installed
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    size = file_path.stat().st_size
    if size > MAX_AUDIO_SIZE_BYTES:
        raise ValueError(
            f"Audio file too large ({size} bytes). Max {MAX_AUDIO_SIZE_BYTES} bytes."
        )

    return _transcribe_local(file_path, whisper_model, whisper_device)


def _transcribe_local(file_path: Path, whisper_model: str, whisper_device: str) -> str:
    """Transcribe using local faster-whisper. Fails fast on device errors (no fallback)."""
    model: _WhisperModelLike = _get_local_model(whisper_model, whisper_device)
    segments, _info = model.transcribe(str(file_path), beam_size=5)
    parts = [s.text for s in segments if s.text]
    result = " ".join(parts).strip()
    logger.debug(f"Local transcription: {len(result)} chars")
    return result or "(no speech detected)"
