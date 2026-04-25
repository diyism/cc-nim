"""Platform-neutral voice note pipeline."""

from __future__ import annotations

from pathlib import Path

from .voice import PendingVoiceRegistry, VoiceTranscriptionService


class VoiceNotePipeline:
    """Coordinate pending voice state and transcription backend execution."""

    def __init__(
        self,
        *,
        registry: PendingVoiceRegistry | None = None,
        transcription: VoiceTranscriptionService | None = None,
    ) -> None:
        self._registry = registry or PendingVoiceRegistry()
        self._transcription = transcription or VoiceTranscriptionService()

    async def register_pending(
        self, chat_id: str, voice_msg_id: str, status_msg_id: str
    ) -> None:
        await self._registry.register(chat_id, voice_msg_id, status_msg_id)

    async def cancel_pending(
        self, chat_id: str, reply_id: str
    ) -> tuple[str, str] | None:
        return await self._registry.cancel(chat_id, reply_id)

    async def is_pending(self, chat_id: str, voice_msg_id: str) -> bool:
        return await self._registry.is_pending(chat_id, voice_msg_id)

    async def complete(
        self, chat_id: str, voice_msg_id: str, status_msg_id: str
    ) -> None:
        await self._registry.complete(chat_id, voice_msg_id, status_msg_id)

    async def transcribe(
        self,
        file_path: Path,
        mime_type: str,
        *,
        whisper_model: str,
        whisper_device: str,
    ) -> str:
        return await self._transcription.transcribe(
            file_path,
            mime_type,
            whisper_model=whisper_model,
            whisper_device=whisper_device,
        )
