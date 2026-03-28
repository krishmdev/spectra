"""Server-side voice capture — records from Mac mic and transcribes with faster-whisper."""
from __future__ import annotations

import io
import threading
import wave

import speech_recognition as sr


class VoiceListener:
    """Capture audio from the Mac's microphone and transcribe locally."""

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self._whisper_model = None
        self._model_lock = threading.Lock()

    def _get_model(self):
        """Lazy-load the faster-whisper model (first call downloads ~75MB)."""
        if self._whisper_model is None:
            with self._model_lock:
                if self._whisper_model is None:
                    from faster_whisper import WhisperModel
                    self._whisper_model = WhisperModel(
                        'tiny',
                        device='cpu',
                        compute_type='int8',
                    )
        return self._whisper_model

    def listen_and_transcribe(
        self,
        timeout: float = 30.0,
        phrase_time_limit: float = 60.0,
    ) -> dict:
        """Record from the default microphone until silence, then transcribe.

        ``timeout`` is how long to wait for speech to *start* (SpeechRecognition).
        ``phrase_time_limit`` caps the length of one utterance. Server passes
        values from ``VOICE_TIMEOUT`` / ``VOICE_PHRASE_LIMIT`` when used from ws_server.

        Returns:
            {"success": True, "transcript": "..."} or
            {"success": False, "error": "..."}
        """
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except sr.WaitTimeoutError:
            return {'success': False, 'error': 'No speech detected — timed out'}
        except OSError as e:
            return {'success': False, 'error': f'Microphone error: {e}'}

        # Convert to WAV bytes for faster-whisper
        try:
            wav_bytes = audio.get_wav_data()
            wav_io = io.BytesIO(wav_bytes)

            model = self._get_model()
            segments, _ = model.transcribe(wav_io, language='en', beam_size=1)
            transcript = ' '.join(seg.text.strip() for seg in segments).strip()

            if not transcript:
                return {'success': False, 'error': 'Could not understand audio'}
            return {'success': True, 'transcript': transcript}

        except Exception as e:
            return {'success': False, 'error': f'Transcription error: {e}'}


# Singleton — reuses model across calls
_listener: VoiceListener | None = None


def get_listener() -> VoiceListener:
    global _listener
    if _listener is None:
        _listener = VoiceListener()
    return _listener
