#!/usr/bin/python3 -B
import os,sys
import gettext

gettext.bindtextdomain('traduia', '/usr/share/locale')
gettext.textdomain('traduia')
_ = gettext.gettext

import socket
import webbrowser
import urllib.parse

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no envía datos realmente
            ip = s.getsockname()[0]
        return ip
    except Exception:
        return "127.0.0.1"


def open_web_with_ip(html_path, port=None):
    ip = get_local_ip()

    if port:
        url_ip = f"{ip}:{port}"
    else:
        url_ip = ip

    full_path = os.path.abspath(html_path)

    #params = urllib.parse.urlencode({"server": ip})
    #url = f"file://{full_path}?{params}"

    # Use '#' for use with xdg-open
    url = f"file://{full_path}#server={url_ip}"

    print(_("[INFO] Opening: {}").format(url))

    # Abrir a través del wrapper que garantiza un navegador por defecto
    # (en caso contrario xdg-open fallaría silenciosamente).
    try:
        subprocess.Popen(["/usr/bin/traduia-open-url", url])
    except Exception:
        webbrowser.open(url)

import json
import queue
import threading
import time
import subprocess
import signal
import fcntl
import psutil
import re
from collections import deque
from typing import Iterator, List, Tuple, Optional

import numpy as np
import sounddevice as sd
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import (
    StreamingResponse,
    JSONResponse,
    HTMLResponse,
    FileResponse,
)
from faster_whisper import WhisperModel
from transformers import MarianTokenizer, MarianMTModel
from pathlib import Path
dist_packages_paths=set()
for path in Path('/usr/lib').glob('python*/dist-packages'):
    if path.is_dir():
        dist_packages_paths.add(str(path))
for path in Path('/usr/local').rglob('dist-packages'):
    if path.is_dir():
        dist_packages_paths.add(str(path))

for path in list(dist_packages_paths):
    if path not in sys.path:
        sys.path.append(path)
try:
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
    from PySide6.QtGui import QIcon, QCursor
    from PySide6.QtCore import QThread, Signal, QTimer, QPoint
except:
    from PySide2.QtWidgets import QApplication, QSystemTrayIcon, QMenu
    from PySide2.QtGui import QIcon, QCursor
    from PySide2.QtCore import QThread, Signal, QTimer, QPoint

import uvicorn

# =========================================================
# ENVIRONMENT SETTINGS (runtime-adjustable knobs)
# Every tunable environment variable is read once, here.
# =========================================================

# ALICIA_INPUT_LANG: language of the teacher's speech: "es" (Spanish) or
# "ca" (Valencian). Any other value falls back to "es". Default: "es".
ENV_INPUT_LANG = (os.getenv("ALICIA_INPUT_LANG", "es") or "es").strip().split("|")[0].strip()

# ALICIA_VAD_THRESHOLD: VAD speech probability threshold [0.0-1.0].
# Higher values reject more ambient noise but may cut soft speech. Default: 0.65.
ENV_VAD_THRESHOLD = float(os.getenv("ALICIA_VAD_THRESHOLD", "0.65"))

# ALICIA_SILENCE_PEAK: minimum peak amplitude [0.0-1.0] for a chunk to be
# considered non-silence and sent to Whisper. Default: 0.0015.
ENV_SILENCE_PEAK = float(os.getenv("ALICIA_SILENCE_PEAK", "0.0015"))

# ALICIA_SILENCE_RMS: minimum RMS energy for a chunk to be considered voice
# (typical mic range: 0.002-0.008 depending on input gain). Default: 0.0040.
ENV_SILENCE_RMS = float(os.getenv("ALICIA_SILENCE_RMS", "0.0040"))

# ALICIA_MAX_NOSPEECH: discard transcribed segments whose no-speech probability
# is >= this value (typical of noise-only audio). Default: 0.55.
ENV_MAX_NOSPEECH = float(os.getenv("ALICIA_MAX_NOSPEECH", "0.55"))

# ALICIA_MIN_LOGPROB: discard transcribed segments whose average log-probability
# is below this value. More negative = more permissive. Out-of-vocabulary words
# (e.g. "LliureX") lower segment confidence, so do not set this too strict. Default: -0.9.
ENV_MIN_LOGPROB = float(os.getenv("ALICIA_MIN_LOGPROB", "-0.9"))

# ALICIA_DEBUG: set to "1" to log every discarded segment with its metrics. Default: "0".
ENV_DEBUG = os.getenv("ALICIA_DEBUG", "0") == "1"

# ALICIA_PULSE_SOURCE: PulseAudio microphone source to capture from (via parec).
# If empty, ALICIA_PULSE_MONITOR or the default PortAudio input is used instead.
ENV_PULSE_SOURCE = (os.getenv("ALICIA_PULSE_SOURCE") or "").strip()

# ALICIA_PULSE_MONITOR: PulseAudio monitor (speakers) device to capture from.
# Only used when ALICIA_PULSE_SOURCE is not set.
ENV_PULSE_MONITOR = (os.getenv("ALICIA_PULSE_MONITOR") or "").strip()

# ALICIA_HOTWORDS: extra hotwords (proper nouns, terms) concatenated after the
# built-in list. Comma-separated. Default: "" (only the built-in list).
ENV_HOTWORDS_EXTRA = (os.getenv("ALICIA_HOTWORDS") or "").strip()

# =========================================================
# CONFIG GENERAL
# =========================================================

RATE = 16000
CHANNELS = 1
BLOCK = RATE // 10  # ~100 ms

INPUT_LANG = ENV_INPUT_LANG
if INPUT_LANG not in ("es", "ca"):
    INPUT_LANG = "es"

# =========================================================
# USE_CT2: True = CTranslate2; False = MarianMT nativo (transformers)
#
# Resolución del modo de traducción:
#   - Marcadores explícitos: .use_ct2 (CT2) / .use_marian (Marian)
#     Un marcador único actúa como override (se valida contra el disco).
#     Ambos marcadores presentes => prioridad Marian.
#   - Sin marcadores: detección desde disco. Si ambos sets están
#     completos => prioridad Marian.
# =========================================================

MODEL_ROOT = Path('/opt/ai/traduia/models')
MARKER_CT2 = MODEL_ROOT / '.use_ct2'
MARKER_MARIAN = MODEL_ROOT / '.use_marian'

MARIAN_PAIRS = (
    "es-en", "es-fr", "es-de", "es-ru", "es-ar",
    "es-uk", "es-ro", "es-it", "ca-en", "ca-es",
)


def _set_complete(subdir: str, file_name: str) -> bool:
    """True si los 10 pares <subdir>/opus-mt-{pair}/<file_name> existen y no están vacíos."""
    for pair in MARIAN_PAIRS:
        f = MODEL_ROOT / subdir / f"opus-mt-{pair}" / file_name
        try:
            if not f.is_file() or f.stat().st_size == 0:
                return False
        except OSError:
            return False
    return True


def _resolve_use_ct2() -> bool:
    """Resuelve el modo de traducción y devuelve True si se usa CTranslate2."""
    m_ct2 = MARKER_CT2.exists()
    m_mar = MARKER_MARIAN.exists()
    d_ct2 = _set_complete("ct2", "model.bin")
    d_mar = _set_complete("marian", "pytorch_model.bin")

    if not d_ct2 and not d_mar and not m_ct2 and not m_mar:
        print(_("[ERROR] No translation models found on disk. Run install-models-traduia."))
        raise RuntimeError(_("No translation models found on disk. Run install-models-traduia."))

    # --- Override explícito por marcador único ---
    if m_ct2 and not m_mar:
        if not d_ct2:
            print(_("[WARN] CT2 marker present but CT2 models are not complete on disk."))
            if d_mar:
                print(_("[WARN] Falling back to Marian models."))
                print(_("[INFO] Translation mode: Marian (fallback from stale .use_ct2 marker)"))
                return False
            print(_("[ERROR] No complete model set found. Run install-models-traduia."))
            raise RuntimeError(_("No complete model set found on disk. Run install-models-traduia."))
        print(_("[INFO] Translation mode: CT2 (override via .use_ct2 marker)"))
        return True

    if m_mar and not m_ct2:
        if not d_mar:
            print(_("[WARN] Marian marker present but Marian models are not complete on disk."))
            if d_ct2:
                print(_("[WARN] Falling back to CT2 models."))
                print(_("[INFO] Translation mode: CT2 (fallback from stale .use_marian marker)"))
                return True
            print(_("[ERROR] No complete model set found. Run install-models-traduia."))
            raise RuntimeError(_("No complete model set found on disk. Run install-models-traduia."))
        print(_("[INFO] Translation mode: Marian (override via .use_marian marker)"))
        return False

    # --- Ambos marcadores: prioridad Marian ---
    if m_ct2 and m_mar:
        if not d_mar:
            if d_ct2:
                print(_("[WARN] Both markers present but Marian models are not complete; falling back to CT2."))
                print(_("[INFO] Translation mode: CT2 (fallback, Marian unavailable)"))
                return True
            print(_("[ERROR] No complete model set found. Run install-models-traduia."))
            raise RuntimeError(_("No complete model set found on disk. Run install-models-traduia."))
        print(_("[INFO] Translation mode: Marian (both markers present, Marian priority)"))
        return False

    # --- Sin marcadores: detección desde disco (Marian prioridad si ambos) ---
    if d_mar:
        if d_ct2:
            print(_("[INFO] Translation mode: Marian (detected from disk, Marian priority)"))
        else:
            print(_("[INFO] Translation mode: Marian (detected from disk)"))
        return False

    print(_("[INFO] Translation mode: CT2 (detected from disk)"))
    return True


USE_CT2 = _resolve_use_ct2()


# =========================================================
# DEFAULTS — Whisper (all parameters for WhisperModel & transcribe)
# =========================================================

# -- WhisperModel.__init__() --
DEFAULT_WHISPER_MODEL_NAME = "small"            # Model size/path: tiny, base, small, medium, large, large-v3, turbo, or HF ID.
DEFAULT_WHISPER_DEVICE = "auto"                  # Device: "cpu", "cuda", "auto".
DEFAULT_WHISPER_DEVICE_INDEX = 0                 # GPU device index. List for multiple GPUs.
DEFAULT_WHISPER_COMPUTE_TYPE = "default"         # Quantization: "default", "int8", "float16", "float32", "bfloat16", etc.
DEFAULT_WHISPER_CPU_THREADS = 0                  # CPU threads (0 = default / OMP_NUM_THREADS).
DEFAULT_WHISPER_NUM_WORKERS = 1                  # Parallel workers for generate() calls.
DEFAULT_WHISPER_DOWNLOAD_ROOT = None             # Custom model download directory (None = HF cache).
DEFAULT_WHISPER_LOCAL_FILES_ONLY = False         # Avoid downloading, use local cache only.
DEFAULT_WHISPER_REVISION = None                  # HF Hub revision (tag, branch, commit hash).
DEFAULT_WHISPER_USE_AUTH_TOKEN = None            # HF auth token or True to use cached token.

# -- WhisperModel.transcribe() --
DEFAULT_WHISPER_LANGUAGE = None                  # Language code (None = auto-detect; overridden by INPUT_LANG in code).
DEFAULT_WHISPER_TASK = "transcribe"              # Task: "transcribe" or "translate".
DEFAULT_WHISPER_LOG_PROGRESS = False             # Show progress bar during transcription.
DEFAULT_WHISPER_BEAM_SIZE = 5                    # Beam size (larger = better quality, slower).
DEFAULT_WHISPER_BEST_OF = 5                      # Candidates when sampling with non-zero temperature.
DEFAULT_WHISPER_PATIENCE = 1.0                   # Beam search patience factor.
DEFAULT_WHISPER_LENGTH_PENALTY = 1.0             # Exponential length penalty constant.
DEFAULT_WHISPER_REPETITION_PENALTY = 1.0         # Penalty for repeated tokens (>1 = penalise).
DEFAULT_WHISPER_NO_REPEAT_NGRAM_SIZE = 0         # Prevent n-gram repetitions (0 = disabled).
DEFAULT_WHISPER_TEMPERATURE = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]  # Sampling temperature(s); list = fallback on failure.
DEFAULT_WHISPER_COMPRESSION_RATIO_THRESHOLD = 2.4   # Max gzip compression ratio to accept segment.
DEFAULT_WHISPER_LOG_PROB_THRESHOLD = -1.0            # Min avg log-probability to accept segment.
DEFAULT_WHISPER_NO_SPEECH_THRESHOLD = 0.6            # Skip segment if no_speech_prob > this and log_prob < threshold.
DEFAULT_WHISPER_CONDITION_ON_PREVIOUS_TEXT = True    # Provide previous output as prompt for next window.
DEFAULT_WHISPER_PROMPT_RESET_ON_TEMPERATURE = 0.5    # Reset prompt cache above this temperature.
DEFAULT_WHISPER_INITIAL_PROMPT = None            # Text prompt for first window (overridden per-language in code).
DEFAULT_WHISPER_PREFIX = None                    # Text prefix forced at start of first window.
DEFAULT_WHISPER_SUPPRESS_BLANK = True            # Suppress blank outputs at start of sampling.
DEFAULT_WHISPER_SUPPRESS_TOKENS = [-1]           # Token IDs to suppress (-1 = default Whisper set).
DEFAULT_WHISPER_WITHOUT_TIMESTAMPS = False       # Only sample text tokens (no timestamps).
DEFAULT_WHISPER_MAX_INITIAL_TIMESTAMP = 1.0      # Initial timestamp cannot be later than this (seconds).
DEFAULT_WHISPER_WORD_TIMESTAMPS = False          # Extract word-level timestamps via cross-attention.
DEFAULT_WHISPER_PREPEND_PUNCTUATIONS = "\"'\"¿([{-"  # Merge these punct. symbols with next word.
DEFAULT_WHISPER_APPEND_PUNCTUATIONS = "\"\'.。，!！?？:：”)]}、"  # Merge these punct. with previous word.
DEFAULT_WHISPER_MULTILINGUAL = False             # Run language detection on every segment.
DEFAULT_WHISPER_VAD_FILTER = False               # Enable Silero VAD to filter non-speech.
DEFAULT_WHISPER_VAD_PARAMETERS = {               # VAD options (dict).
    "threshold": 0.65,                            #   Speech probability threshold.
    "neg_threshold": None,                       #   Silence threshold (None = auto max(threshold-0.15, 0.01)).
    "min_speech_duration_ms": 250,               #   Drop speech chunks shorter than this (ms).
    "max_speech_duration_s": float("inf"),       #   Split speech chunks longer than this (s).
    "min_silence_duration_ms": 500,             #   Silence duration to separate speech chunks (ms).
    "speech_pad_ms": 150,                        #   Pad each speech chunk on both sides (ms).
}
DEFAULT_WHISPER_MAX_NEW_TOKENS = None            # Max new tokens per chunk (None = model default).
DEFAULT_WHISPER_CHUNK_LENGTH = None              # Override feature-extractor chunk length (seconds).
DEFAULT_WHISPER_CLIP_TIMESTAMPS = "0"            # Clip timestamps (comma-separated or float list).
DEFAULT_WHISPER_HALLUCINATION_SILENCE_THRESHOLD = None  # Skip silent gaps longer than this (s).
DEFAULT_WHISPER_HOTWORDS = None                  # Hotwords / hint phrases (no effect if prefix is set).
DEFAULT_WHISPER_LANGUAGE_DETECTION_THRESHOLD = 0.5  # Language detection confidence threshold.
DEFAULT_WHISPER_LANGUAGE_DETECTION_SEGMENTS = 1      # Segments used for language detection.

if USE_CT2:
    import ctranslate2

    # =========================================================
    # DEFAULTS — CTranslate2 (all parameters for Translator & translate_batch)
    # =========================================================

    # -- ctranslate2.Translator.__init__() --
    DEFAULT_CT2_DEVICE = "cpu"                       # Device: "cpu", "cuda", "auto".
    DEFAULT_CT2_DEVICE_INDEX = 0                     # Device ID(s). List for multiple GPUs.
    DEFAULT_CT2_COMPUTE_TYPE = "default"             # Quantization: "default", "int8", "float16", etc.
    DEFAULT_CT2_INTER_THREADS = 1                    # Max number of parallel translations.
    DEFAULT_CT2_INTRA_THREADS = 0                    # OpenMP threads per translator (0 = default).
    DEFAULT_CT2_MAX_QUEUED_BATCHES = 0               # Max batches in queue (0 = auto, -1 = unlimited).
    DEFAULT_CT2_FLASH_ATTENTION = False              # Use Flash Attention 2 for self-attention layers.
    DEFAULT_CT2_TENSOR_PARALLEL = False              # Run with tensor parallelism across devices.

    # -- ctranslate2.Translator.translate_batch() --
    DEFAULT_CT2_BEAM_SIZE = 2                        # Beam size (1 = greedy).
    DEFAULT_CT2_PATIENCE = 1.0                       # Beam search patience factor.
    DEFAULT_CT2_NUM_HYPOTHESES = 1                   # Number of hypotheses to return.
    DEFAULT_CT2_LENGTH_PENALTY = 1.0                 # Exponential length penalty constant.
    DEFAULT_CT2_COVERAGE_PENALTY = 0.0               # Coverage penalty weight.
    DEFAULT_CT2_REPETITION_PENALTY = 1.0             # Penalty for repeated tokens (>1 = penalise).
    DEFAULT_CT2_NO_REPEAT_NGRAM_SIZE = 0             # Prevent n-gram repetitions (0 = disabled).
    DEFAULT_CT2_DISABLE_UNK = False                  # Disable generation of the unknown token.
    DEFAULT_CT2_SUPPRESS_SEQUENCES = None            # Suppress specific token sequences.
    DEFAULT_CT2_END_TOKEN = None                     # Stop decoding on these token(s) (None = model EOS).
    DEFAULT_CT2_RETURN_END_TOKEN = False             # Include the end token in the returned result.
    DEFAULT_CT2_PREFIX_BIAS_BETA = 0.0              # Bias translations towards the given prefix.
    DEFAULT_CT2_MAX_INPUT_LENGTH = 1024              # Truncate inputs after this many tokens (0 = disable).
    DEFAULT_CT2_MAX_DECODING_LENGTH = 256            # Maximum prediction length (tokens).
    DEFAULT_CT2_MIN_DECODING_LENGTH = 1              # Minimum prediction length (tokens).
    DEFAULT_CT2_USE_VMAP = False                     # Use vocabulary mapping file saved in the model.
    DEFAULT_CT2_RETURN_SCORES = False                # Include scores in the translation result.
    DEFAULT_CT2_RETURN_LOGITS_VOCAB = False          # Include log-probabilities of each token in the vocabulary.
    DEFAULT_CT2_RETURN_ATTENTION = False             # Include attention vectors in the result.
    DEFAULT_CT2_RETURN_ALTERNATIVES = False          # Return alternatives at first unconstrained decoding position.
    DEFAULT_CT2_MIN_ALTERNATIVE_EXPANSION_PROB = 0.0  # Min initial probability to expand an alternative.
    DEFAULT_CT2_SAMPLING_TOPK = 1                    # Randomly sample from top K candidates (1 = greedy).
    DEFAULT_CT2_SAMPLING_TOPP = 1.0                  # Nucleus sampling cumulative probability threshold.
    DEFAULT_CT2_SAMPLING_TEMPERATURE = 1.0           # Sampling temperature (>1 = more random, <1 = more greedy).
    DEFAULT_CT2_REPLACE_UNKNOWNS = False             # Replace <unk> with source token of highest attention.
    DEFAULT_CT2_MAX_BATCH_SIZE = 0                   # Max batch size (0 = auto, >0 = split into smaller batches).
    DEFAULT_CT2_BATCH_TYPE = "examples"              # Batching strategy: "examples" or "tokens".

# =========================================================
# OVERRIDE — Runtime overrides for Whisper & CTranslate2
# Modify values below to change behaviour without touching defaults.
# =========================================================

# -- Whisper overrides --
WHISPER_LOCAL_DIR = Path('/opt/ai/traduia/models/whisper-small')
if WHISPER_LOCAL_DIR.exists() and any(WHISPER_LOCAL_DIR.iterdir()):
    WHISPER_MODEL_NAME = str(WHISPER_LOCAL_DIR)
else:
    raise RuntimeError(f"Whisper model not found at {WHISPER_LOCAL_DIR}. Run install-models-traduia first.")
WHISPER_DEVICE = "cpu"                           # DEFAULT: "auto" — override for CPU-only
WHISPER_DEVICE_INDEX = DEFAULT_WHISPER_DEVICE_INDEX
WHISPER_COMPUTE_TYPE = "int8"                    # DEFAULT: "default" — override for int8 quant
WHISPER_CPU_THREADS = DEFAULT_WHISPER_CPU_THREADS
WHISPER_NUM_WORKERS = DEFAULT_WHISPER_NUM_WORKERS
WHISPER_DOWNLOAD_ROOT = DEFAULT_WHISPER_DOWNLOAD_ROOT
WHISPER_LOCAL_FILES_ONLY = DEFAULT_WHISPER_LOCAL_FILES_ONLY
WHISPER_REVISION = DEFAULT_WHISPER_REVISION
WHISPER_USE_AUTH_TOKEN = DEFAULT_WHISPER_USE_AUTH_TOKEN
WHISPER_LANGUAGE = DEFAULT_WHISPER_LANGUAGE
WHISPER_TASK = DEFAULT_WHISPER_TASK
WHISPER_LOG_PROGRESS = DEFAULT_WHISPER_LOG_PROGRESS
WHISPER_BEAM_SIZE = DEFAULT_WHISPER_BEAM_SIZE
WHISPER_BEST_OF = DEFAULT_WHISPER_BEST_OF
WHISPER_PATIENCE = DEFAULT_WHISPER_PATIENCE
WHISPER_LENGTH_PENALTY = DEFAULT_WHISPER_LENGTH_PENALTY
WHISPER_REPETITION_PENALTY = 1.3
WHISPER_NO_REPEAT_NGRAM_SIZE = 4
WHISPER_TEMPERATURE = DEFAULT_WHISPER_TEMPERATURE
WHISPER_COMPRESSION_RATIO_THRESHOLD = 1.5
WHISPER_LOG_PROB_THRESHOLD = -0.8
WHISPER_NO_SPEECH_THRESHOLD = DEFAULT_WHISPER_NO_SPEECH_THRESHOLD
WHISPER_CONDITION_ON_PREVIOUS_TEXT = False       # DEFAULT: True — reduce hallucination carry-over
WHISPER_PROMPT_RESET_ON_TEMPERATURE = DEFAULT_WHISPER_PROMPT_RESET_ON_TEMPERATURE
WHISPER_INITIAL_PROMPT = DEFAULT_WHISPER_INITIAL_PROMPT
WHISPER_PREFIX = DEFAULT_WHISPER_PREFIX
WHISPER_SUPPRESS_BLANK = DEFAULT_WHISPER_SUPPRESS_BLANK
WHISPER_SUPPRESS_TOKENS = DEFAULT_WHISPER_SUPPRESS_TOKENS
WHISPER_WITHOUT_TIMESTAMPS = DEFAULT_WHISPER_WITHOUT_TIMESTAMPS
WHISPER_MAX_INITIAL_TIMESTAMP = DEFAULT_WHISPER_MAX_INITIAL_TIMESTAMP
WHISPER_WORD_TIMESTAMPS = DEFAULT_WHISPER_WORD_TIMESTAMPS
WHISPER_PREPEND_PUNCTUATIONS = DEFAULT_WHISPER_PREPEND_PUNCTUATIONS
WHISPER_APPEND_PUNCTUATIONS = DEFAULT_WHISPER_APPEND_PUNCTUATIONS
WHISPER_MULTILINGUAL = DEFAULT_WHISPER_MULTILINGUAL
WHISPER_VAD_FILTER = True                        # DEFAULT: False — filter non-speech with Silero VAD
WHISPER_VAD_PARAMETERS = {                       # DEFAULT: min_silence=500, pad=150 — tighter for speech detection
    "threshold": ENV_VAD_THRESHOLD,
    "neg_threshold": DEFAULT_WHISPER_VAD_PARAMETERS["neg_threshold"],
    "min_speech_duration_ms": DEFAULT_WHISPER_VAD_PARAMETERS["min_speech_duration_ms"],
    "max_speech_duration_s": DEFAULT_WHISPER_VAD_PARAMETERS["max_speech_duration_s"],
    "min_silence_duration_ms": 300,
    "speech_pad_ms": 200,
}
WHISPER_MAX_NEW_TOKENS = DEFAULT_WHISPER_MAX_NEW_TOKENS
WHISPER_CHUNK_LENGTH = DEFAULT_WHISPER_CHUNK_LENGTH
WHISPER_CLIP_TIMESTAMPS = DEFAULT_WHISPER_CLIP_TIMESTAMPS
WHISPER_HALLUCINATION_SILENCE_THRESHOLD = DEFAULT_WHISPER_HALLUCINATION_SILENCE_THRESHOLD
WHISPER_HOTWORDS = "LliureX, TraduIA, AlicIA" + (", " + ENV_HOTWORDS_EXTRA if ENV_HOTWORDS_EXTRA else "")   # SOLO nombres propios (aplicable a es y ca) + ALICIA_HOTWORDS
WHISPER_LANGUAGE_DETECTION_THRESHOLD = DEFAULT_WHISPER_LANGUAGE_DETECTION_THRESHOLD
WHISPER_LANGUAGE_DETECTION_SEGMENTS = DEFAULT_WHISPER_LANGUAGE_DETECTION_SEGMENTS

if USE_CT2:
    # -- CTranslate2 overrides --
    CT2_DEVICE = DEFAULT_CT2_DEVICE
    CT2_DEVICE_INDEX = DEFAULT_CT2_DEVICE_INDEX
    CT2_COMPUTE_TYPE = DEFAULT_CT2_COMPUTE_TYPE
    CT2_INTER_THREADS = DEFAULT_CT2_INTER_THREADS
    CT2_INTRA_THREADS = DEFAULT_CT2_INTRA_THREADS
    CT2_MAX_QUEUED_BATCHES = DEFAULT_CT2_MAX_QUEUED_BATCHES
    CT2_FLASH_ATTENTION = DEFAULT_CT2_FLASH_ATTENTION
    CT2_TENSOR_PARALLEL = DEFAULT_CT2_TENSOR_PARALLEL
    CT2_BEAM_SIZE = 1                                # DEFAULT: 2 — slightly wider beam for better translations
    CT2_PATIENCE = DEFAULT_CT2_PATIENCE
    CT2_NUM_HYPOTHESES = DEFAULT_CT2_NUM_HYPOTHESES
    CT2_LENGTH_PENALTY = 0.2
    CT2_COVERAGE_PENALTY = 0.3
    CT2_REPETITION_PENALTY = 5.0                     # DEFAULT: 1.0 — mild penalty to reduce repetition
    CT2_NO_REPEAT_NGRAM_SIZE = 4
    CT2_DISABLE_UNK = DEFAULT_CT2_DISABLE_UNK
    CT2_SUPPRESS_SEQUENCES = DEFAULT_CT2_SUPPRESS_SEQUENCES
    CT2_END_TOKEN = DEFAULT_CT2_END_TOKEN
    CT2_RETURN_END_TOKEN = DEFAULT_CT2_RETURN_END_TOKEN
    CT2_PREFIX_BIAS_BETA = DEFAULT_CT2_PREFIX_BIAS_BETA
    CT2_MAX_INPUT_LENGTH = DEFAULT_CT2_MAX_INPUT_LENGTH
    CT2_MAX_DECODING_LENGTH = 80                    # DEFAULT: 256 — longer text support
    CT2_MIN_DECODING_LENGTH = DEFAULT_CT2_MIN_DECODING_LENGTH
    CT2_USE_VMAP = DEFAULT_CT2_USE_VMAP
    CT2_RETURN_SCORES = DEFAULT_CT2_RETURN_SCORES
    CT2_RETURN_LOGITS_VOCAB = DEFAULT_CT2_RETURN_LOGITS_VOCAB
    CT2_RETURN_ATTENTION = DEFAULT_CT2_RETURN_ATTENTION
    CT2_RETURN_ALTERNATIVES = DEFAULT_CT2_RETURN_ALTERNATIVES
    CT2_MIN_ALTERNATIVE_EXPANSION_PROB = DEFAULT_CT2_MIN_ALTERNATIVE_EXPANSION_PROB
    CT2_SAMPLING_TOPK = DEFAULT_CT2_SAMPLING_TOPK
    CT2_SAMPLING_TOPP = DEFAULT_CT2_SAMPLING_TOPP
    CT2_SAMPLING_TEMPERATURE = DEFAULT_CT2_SAMPLING_TEMPERATURE
    CT2_REPLACE_UNKNOWNS = DEFAULT_CT2_REPLACE_UNKNOWNS
    CT2_MAX_BATCH_SIZE = DEFAULT_CT2_MAX_BATCH_SIZE
    CT2_BATCH_TYPE = DEFAULT_CT2_BATCH_TYPE


# =========================================================
# MONITOR DE ACTIVIDAD (10 MINUTOS)
# =========================================================
MONITOR_WINDOW_MINS = 10
CHUNK_DURATION = 5.0  # Coincide con MIN_SECONDS en stt_worker
MAX_WINDOW_SIZE = int((MONITOR_WINDOW_MINS * 60) // CHUNK_DURATION)
activity_window: deque = deque(maxlen=MAX_WINDOW_SIZE)
INACTIVITY_RATIO = 0.1  # umbral de actividad (10%): systray, /activity y auto-shutdown

PROMPT_CA = (
   "Classe en un aula amb LliureX i TraduIA. Valencià, amb paraules com xiquet, faena, espill, hui, eixir, cotxera, llepolies, orxata, espenta, menut, celler, gerundi, conjugació, subjuntiu, pretèrit, sintaxi, verb, oració, paràgraf, literatura, Cervantes, Numància, Lorca, Quixot."
)
PROMPT_ES = (
   "Clase en un aula con LliureX y TraduIA. Español de España, con palabras como coche, ordenador, móvil, vámonos, trabajo, gafas, libreta, gerundio, conjugación, subjuntivo, pretérito, sintaxis, verbo, oración, párrafo, literatura, Cervantes, Numancia, Lorca, Quijote."
)

# BASE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path('/usr/lib/traduia')

if USE_CT2:
    MARIAN_CT2_BASE = Path('/opt/ai/traduia/models/ct2')
    def _marian_ct2_path(model_name: str) -> str:
        repo = model_name.split("/")[-1]
        return str(MARIAN_CT2_BASE / repo)
else:
    MARIAN_LOCAL_BASE = Path('/opt/ai/traduia/models/marian')
    def _marian_local_path(model_name: str) -> str:
        repo = model_name.split("/")[-1]
        return str(MARIAN_LOCAL_BASE / repo)

# =========================================================
# MARIAN: ES/CA -> EN/FR/DE/RU/AR/UK
# =========================================================

# ES -> X
MARIAN_ES_EN = "Helsinki-NLP/opus-mt-es-en"
MARIAN_ES_FR = "Helsinki-NLP/opus-mt-es-fr"
MARIAN_ES_DE = "Helsinki-NLP/opus-mt-es-de"
MARIAN_ES_RU = "Helsinki-NLP/opus-mt-es-ru"
MARIAN_ES_AR = "Helsinki-NLP/opus-mt-es-ar"
MARIAN_ES_UK = "Helsinki-NLP/opus-mt-es-uk"
MARIAN_ES_RO = "Helsinki-NLP/opus-mt-es-ro"
MARIAN_ES_IT = "Helsinki-NLP/opus-mt-es-it"

# CA -> EN/ES
MARIAN_CA_EN = "Helsinki-NLP/opus-mt-ca-en"
MARIAN_CA_ES = "Helsinki-NLP/opus-mt-ca-es"

# Caches (tok compartido, engine depende de USE_CT2)
_m_es_tok = {}
_m_ca_tok = {}

if USE_CT2:
    _m_es_ct2 = {}
    _m_ca_ct2 = {}
    _engine_cache_es = _m_es_ct2
    _engine_cache_ca = _m_ca_ct2
else:
    _m_es_model = {}
    _m_ca_model = {}
    _engine_cache_es = _m_es_model
    _engine_cache_ca = _m_ca_model


if USE_CT2:
    def _load_marian(model_name, cache_tok, cache_model):
        if model_name not in cache_tok or model_name not in cache_model:
            ct2_path = _marian_ct2_path(model_name)
            try:
                tok = MarianTokenizer.from_pretrained(ct2_path)
                translator = ctranslate2.Translator(
                    ct2_path,
                    device=CT2_DEVICE,
                    device_index=CT2_DEVICE_INDEX,
                    compute_type=CT2_COMPUTE_TYPE,
                    inter_threads=CT2_INTER_THREADS,
                    intra_threads=CT2_INTRA_THREADS,
                    max_queued_batches=CT2_MAX_QUEUED_BATCHES,
                    flash_attention=CT2_FLASH_ATTENTION,
                    tensor_parallel=CT2_TENSOR_PARALLEL,
                )
            except Exception as e:
                print(_("[WARN] Failed to load CT2 model {}: {}").format(ct2_path, e))
                raise
            cache_tok[model_name] = tok
            cache_model[model_name] = translator
        return cache_tok[model_name], cache_model[model_name]
else:
    def _load_marian(model_name, cache_tok, cache_model):
        if model_name not in cache_tok or model_name not in cache_model:
            local_path = _marian_local_path(model_name)
            try:
                tok = MarianTokenizer.from_pretrained(local_path, local_files_only=True)
                model = MarianMTModel.from_pretrained(local_path, local_files_only=True)
            except Exception as e:
                print(_("[WARN] Failed to load Marian model {}: {}").format(local_path, e))
                raise
            cache_tok[model_name] = tok
            cache_model[model_name] = model
        return cache_tok[model_name], cache_model[model_name]

def _detect_low_diversity(words, window=12, threshold=0.45):
    if len(words) < window:
        return -1
    for i in range(len(words) - window + 1):
        chunk = words[i:i+window]
        if len(set(chunk)) / len(chunk) < threshold:
            return i
    return -1

def sanitize_translation(source: str, translated: str) -> str:
    if not translated or not source:
        return translated or ""

    translated = re.sub(r'[\s.]{3,}$', '', translated).strip()

    src_words = len(source.split())
    trans_words = len(translated.split())

    if trans_words > 2.0 * src_words:
        limit = int(2.0 * src_words)
        words = translated.split()
        truncated = ' '.join(words[:limit])
        for sep in ['. ', ', ', '; ', ': ']:
            idx = truncated.rfind(sep)
            if idx > len(truncated) // 3:
                truncated = truncated[:idx + 1]
                break
        translated = truncated.strip()

    words = translated.lower().split()
    if len(words) >= 6:
        for n in (3, 4, 5):
            ngram_counts = {}
            first_repeat_pos = len(words)
            for i in range(len(words) - n + 1):
                ngram = tuple(words[i:i+n])
                if ngram in ngram_counts:
                    ngram_counts[ngram] += 1
                    if ngram_counts[ngram] >= 3:
                        first_repeat_pos = min(first_repeat_pos, i)
                else:
                    ngram_counts[ngram] = 1
            if first_repeat_pos < len(words):
                translated = ' '.join(translated.split()[:first_repeat_pos]).strip()
                break

    words = translated.lower().split()
    div_pos = _detect_low_diversity(words)
    if div_pos > 0:
        translated = ' '.join(translated.split()[:div_pos]).strip()

    translated = re.sub(r'(\.{2,}\s*){2,}', '', translated)
    translated = re.sub(r'\s*\.{3,}\s*$', '', translated)
    translated = re.sub(r'\s{2,}', ' ', translated).strip()

    if len(translated.split()) < 2:
        return ""

    return translated

if USE_CT2:
    def _translate_text(text, tok, engine):
        source_tokens = tok.tokenize(text)
        if not source_tokens:
            return ""
        results = engine.translate_batch(
            [source_tokens],
            beam_size=CT2_BEAM_SIZE,
            patience=CT2_PATIENCE,
            num_hypotheses=CT2_NUM_HYPOTHESES,
            length_penalty=CT2_LENGTH_PENALTY,
            coverage_penalty=CT2_COVERAGE_PENALTY,
            repetition_penalty=CT2_REPETITION_PENALTY,
            no_repeat_ngram_size=CT2_NO_REPEAT_NGRAM_SIZE,
            max_batch_size=CT2_MAX_BATCH_SIZE,
            batch_type=CT2_BATCH_TYPE,
            max_input_length=CT2_MAX_INPUT_LENGTH,
            max_decoding_length=CT2_MAX_DECODING_LENGTH,
            min_decoding_length=CT2_MIN_DECODING_LENGTH,
            sampling_topk=CT2_SAMPLING_TOPK,
            sampling_topp=CT2_SAMPLING_TOPP,
            sampling_temperature=CT2_SAMPLING_TEMPERATURE,
            return_scores=CT2_RETURN_SCORES,
            return_logits_vocab=CT2_RETURN_LOGITS_VOCAB,
            return_attention=CT2_RETURN_ATTENTION,
            return_alternatives=CT2_RETURN_ALTERNATIVES,
            min_alternative_expansion_prob=CT2_MIN_ALTERNATIVE_EXPANSION_PROB,
            suppress_sequences=CT2_SUPPRESS_SEQUENCES,
            end_token=CT2_END_TOKEN,
            return_end_token=CT2_RETURN_END_TOKEN,
            prefix_bias_beta=CT2_PREFIX_BIAS_BETA,
            use_vmap=CT2_USE_VMAP,
            replace_unknowns=CT2_REPLACE_UNKNOWNS,
        )
        translated = tok.decode(
            tok.convert_tokens_to_ids(results[0].hypotheses[0]),
            skip_special_tokens=True,
        )
        return sanitize_translation(text, translated)
else:
    def _translate_text(text, tok, engine):
        batch = tok([text], return_tensors="pt", padding=True, truncation=True)
        gen = engine.generate(**batch, max_length=512)
        out = tok.batch_decode(gen, skip_special_tokens=True)
        return out[0] if out else ""


def translate_from_es(text: str, target: str) -> str:
    mapping = {
        "en": MARIAN_ES_EN,
        "fr": MARIAN_ES_FR,
        "de": MARIAN_ES_DE,
        "ru": MARIAN_ES_RU,
        "ar": MARIAN_ES_AR,
        "uk": MARIAN_ES_UK,
        "ro": MARIAN_ES_RO,
        "it": MARIAN_ES_IT,
    }
    if target not in mapping:
        return f"[NO SOPORTADO ES->{target}]"
    tok, engine = _load_marian(mapping[target], _m_es_tok, _engine_cache_es)
    return _translate_text(text, tok, engine)


def translate_from_ca(text: str, target: str) -> str:
    """
    CA -> EN directo con opus-mt-ca-en.
    CA -> X (fr,de,ru,ar,uk,ro,it) vía CA->ES + ES->X.
    """
    txt = text.strip()
    if not txt:
        return ""

    if target == "en":
        tok, engine = _load_marian(MARIAN_CA_EN, _m_ca_tok, _engine_cache_ca)
        return _translate_text(txt, tok, engine)

    tok_ca_es, engine_ca_es = _load_marian(MARIAN_CA_ES, _m_ca_tok, _engine_cache_ca)
    text_es = _translate_text(txt, tok_ca_es, engine_ca_es)
    return translate_from_es(text_es, target) if text_es else ""


def translate_text(text: str, target: str) -> str:
    target = target.lower()
    if target not in ("en", "fr", "de", "ru", "ar", "uk", "ro", "it"):
        return f"[NO SOPORTADO -> {target}]"
    if INPUT_LANG == "es":
        return translate_from_es(text, target)
    else:
        return translate_from_ca(text, target)


# =========================================================
# I18N FOR WEB CLIENT
# =========================================================

def get_i18n_data():
    languages = ['en', 'es', 'ca']
    data = {}
    locale_dir = '/usr/share/locale'
    for lang in languages:
        try:
            if lang == 'en':
                _t = lambda x: x
            else:
                t = gettext.translation('traduia', locale_dir, languages=[lang])
                _t = t.gettext
        except Exception:
            _t = lambda x: x
        data[lang] = {
            'title': _t("LliureX - Real-time Transcription / Translation System"),
            'mainTitle': _t("LliureX - TraduIA"),
            'aliciaName': _t("AlicIA"),
            'labelMode': _t("Display Mode"),
            'labelLang': _t("Language"),
            'optOriginal': _t("View original (teacher's language)"),
            'optTranslate': _t("View translated"),
            'placeholder': _t("Here you will see the teacher's speech in your chosen language…"),
            'status': {
                'desconectado': _t("disconnected"),
                'conectando': _t("connecting..."),
                'conectado': _t("connected"),
                'error': _t("disconnected")
            },
            'errorTranslation': _t("[TRANSLATION ERROR]"),
            'errorConnection': _t("[ERROR] Could not connect to the server."),
            'langs': {
                'en': _t("English"), 'fr': _t("French"), 'de': _t("German"),
                'ru': _t("Russian"), 'ar': _t("Arabic"), 'uk': _t("Ukrainian"),
                'ro': _t("Romanian"), 'es': _t("Spanish"), 'ca': _t("Valencian"),
                'it': _t("Italian")
            }
        }
    data['va'] = data['ca']
    return data


# =========================================================
# LIMPIEZA SOLO PARA CASTELLANO: ¡Suscríbete!
# =========================================================

def clean_spanish_line(text: str) -> str:
    if not text:
        return text
    text = text.replace("¡Suscríbete!", "")
    text = " ".join(text.split())
    return text


# =========================================================
# HTML EMBEBIDO (cliente alumno)
# =========================================================

HTML_CLIENT = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LliureX - TraduIA</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/png" href="/alicia.png">
  <style>
    :root {
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell,
                   "Helvetica Neue", Arial, "Noto Sans", sans-serif;
      color-scheme: light;
    }
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #def7ff;
    }
    .shell {
      width: 100%;
      max-width: 900px;
      padding: 20px;
      box-sizing: border-box;
    }
    .card {
      background: #0f172a;
      border-radius: 20px;
      border: 1px solid rgba(148, 163, 184, 0.5);
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.35);
      padding: 18px 18px 16px 18px;
      color: #e5e7eb;
      height: 80vh;
      display: flex;
      flex-direction: column;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }
    .header-title {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .header-title h1 {
      margin: 0;
      font-size: 30px;
      font-weight: 600;
      font-family: "Noto Sans", "Ubuntu", "Arial", sans-serif;
    }
    .header-title span {
      font-size: 12px;
      color: #9ca3af;
    }
    .logo {
      width: 44px;
      height: 44px;
      border-radius: 999px;
      object-fit: contain;
      border: 1px solid rgba(148, 163, 184, 0.6);
      background: #020617;
      padding: 4px;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 12px;
      align-items: center;
      margin-bottom: 8px;
      font-family: "Noto Sans", "Ubuntu", "Arial", sans-serif;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 150px;
    }
    .field-label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #9ca3af;
    }
    select {
      padding: 6px 9px;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.6);
      background: rgba(15, 23, 42, 0.9);
      color: #e5e7eb;
      font-size: 13px;
      outline: none;
    }
    #mode, #mode option {
      font-family: "Noto Sans", "Ubuntu", "Arial", sans-serif;
      font-size: 14px;
    }
    select:focus {
      border-color: #38bdf8;
      box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.5);
    }
    .pill {
      display:inline-flex;
      align-items:center;
      gap:4px;
      padding:3px 9px;
      border-radius:999px;
      border:1px solid rgba(148, 163, 184, 0.5);
      font-size:11px;
      margin-left:0;
      color:#9ca3af;
      background:rgba(15, 23, 42, 0.9);
      white-space: nowrap;
      margin-left: auto;
    }
    .pill-dot {
      width:7px;
      height:7px;
      border-radius:999px;
      background:#6b7280;
    }
    .text-area-row {
      margin-top: 6px;
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    textarea {
      width: 100%;
      min-height: 320px;
      border-radius: 16px;
      border: 1px solid rgba(55, 65, 81, 0.9);
      padding: 10px 11px;
      resize: vertical;
      font-family: "Noto Sans", "Ubuntu", "Arial", sans-serif;
      font-size: 18px;
      line-height: 1.6;
      letter-spacing: 0.01em;
      background: radial-gradient(circle at top left, rgba(15, 23, 42, 0.9), #020617);
      color: #e5e7eb;
      outline: none;
      white-space: pre-wrap;
      box-sizing: border-box;
      flex: 1;
      min-height: 0;
      height: 100%;
      resize: none;
    }
    textarea::placeholder {
      color: #6b7280;
    }
    textarea:focus {
      border-color: #38bdf8;
      box-shadow:
        0 0 0 1px rgba(56, 189, 248, 0.5),
        0 18px 45px rgba(15, 23, 42, 0.8);
    }
    @media (max-width: 720px) {
      .card { padding: 14px; }
      .header-title h1 { font-size: 16px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="card">
      <div class="header">
        <div class="header-title">
          <h1 id="title-main">...</h1>
        </div>
        <div class="pill" id="status-pill">
          <span class="pill-dot" id="status-dot"></span>
          <span id="status-text">...</span>
        </div>
        <img src="/alicia.png" alt="..." id="alicia-logo" class="logo">
      </div>

      <div class="row">
        <div class="field">
          <span class="field-label" id="label-mode">...</span>
          <select id="mode">
            <option value="original">...</option>
            <option value="translate">...</option>
          </select>
        </div>

        <div class="field" id="lang-field">
          <span class="field-label" id="label-language">...</span>
          <select id="target"></select>
        </div>

      </div>

      <div class="text-area-row">
        <textarea
          id="out"
          placeholder="..."
          spellcheck="false"
        ></textarea>
      </div>
    </div>
  </div>

  <script>
    const SERVER = window.location.origin;

    const modeSel   = document.getElementById("mode");
    const targetSel = document.getElementById("target");
    const langField = document.getElementById("lang-field");
    const out       = document.getElementById("out");
    const pill      = document.getElementById("status-pill");
    const pillDot   = document.getElementById("status-dot");
    const pillText  = document.getElementById("status-text");

    const titleMain = document.getElementById("title-main");
    const subtitle  = document.getElementById("subtitle");
    const labelMode = document.getElementById("label-mode");
    const labelLang = document.getElementById("label-language");
    const aliciaLogo= document.getElementById("alicia-logo");

    let es = null;
    let INPUT_LANG = "es";
    let UI_LANG = "en";

    const i18n = {{I18N_DATA}};

    function getI18n() { return i18n[UI_LANG] || i18n['en']; }

    function setStatus(state) {
      const data = getI18n();
      const map = data.status;
      let key = state;
      if (!map[key]) key = "desconectado";
      pillText.textContent = map[key];

      if (state === "conectando") {
        pillDot.style.background = "#facc15";
        pill.style.borderColor = "rgba(250, 204, 21, 0.7)";
      } else if (state === "conectado") {
        pillDot.style.background = "#22c55e";
        pill.style.borderColor = "rgba(34, 197, 94, 0.7)";
      } else if (state === "error") {
        pillDot.style.background = "#ef4444";
        pill.style.borderColor = "rgba(239, 68, 68, 0.7)";
      } else {
        pillDot.style.background = "#6b7280";
        pill.style.borderColor = "rgba(148, 163, 184, 0.5)";
      }
    }

    function appendLine(text) {
      if (!text) return;
      out.value += text + "\n";
      out.scrollTop = out.scrollHeight;
    }

    async function translateLine(text, target) {
      try {
        const res = await fetch(SERVER + "/translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text, target_lang: target }),
        });
        if (!res.ok) {
          return getI18n().errorTranslation + " " + (await res.text());
        }
        const data = await res.json();
        return data.text || "";
      } catch (e) {
        return getI18n().errorTranslation + " " + e;
      }
    }

    function clearTargetOptions() {
      while (targetSel.firstChild) {
        targetSel.removeChild(targetSel.firstChild);
      }
    }

    function addOption(value, label, selected) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      if (selected) opt.selected = true;
      targetSel.appendChild(opt);
    }

    function configureTargetSelect() {
      const mode = modeSel.value;
      const data = getI18n();
      clearTargetOptions();

      // Mostrar selector de idioma solo cuando el modo es "ver traducido"
      if (langField) {
        langField.style.display = (mode === "original") ? "none" : "";
      }

      if (mode === "original") {
        addOption("", data.langs[INPUT_LANG] || INPUT_LANG, true);
        targetSel.disabled = true;
      } else {
        const languages = ["en", "fr", "de", "ru", "ar", "uk", "ro", "it"];
        languages.sort((a, b) => {
          const nameA = data.langs[a] || a;
          const nameB = data.langs[b] || b;
          return nameA.localeCompare(nameB, UI_LANG);
        });

        languages.forEach(t => {
          addOption(t, data.langs[t] || t, t === "en");
        });
        targetSel.disabled = false;
      }
    }

    function applyLocalization() {
      UI_LANG = (navigator.language || navigator.userLanguage || 'en').toLowerCase().substring(0,2);
      if(!i18n[UI_LANG]) UI_LANG='en';
      const d = i18n[UI_LANG];

      document.title = d.title;
      titleMain.textContent = d.mainTitle;
      aliciaLogo.alt = d.aliciaName;
      labelMode.textContent = d.labelMode;
      labelLang.textContent = d.labelLang;
      out.placeholder = d.placeholder;
      modeSel.options[0].textContent = d.optOriginal;
      modeSel.options[1].textContent = d.optTranslate;
      document.documentElement.lang = UI_LANG;
    }

    function connect() {
      if (es) {
        es.close();
        es = null;
      }
      out.value = "";
      setStatus("conectando");

      try {
        es = new EventSource(SERVER + "/stream");
      } catch (e) {
        appendLine(getI18n().errorConnection);
        setStatus("error");
        return;
      }

      es.onopen = () => setStatus("conectado");

      es.onmessage = async (e) => {
        if (!e.data) return;
        let obj;
        try {
          obj = JSON.parse(e.data);
        } catch (_) {
          return;
        }
        if (obj.type !== "line") return;

        const mode   = modeSel.value;
        const target = targetSel.value;
        const text   = obj.text || "";

        if (mode === "original") {
          appendLine(text);
          return;
        }

        const translated = await translateLine(text, target);
        appendLine(translated);
      };

      es.onerror = () => {
        setStatus("error");
        if (es) {
          es.close();
          es = null;
        }
        setTimeout(connect, 4000);
      };
    }

    async function init() {
      applyLocalization();
      setStatus("desconectado");
      try {
        const res = await fetch(SERVER + "/health");
        if (res.ok) {
          const data = await res.json();
          if (data && data.input_lang) {
            INPUT_LANG = data.input_lang;
          }
        }
      } catch (e) {
        INPUT_LANG = "es";
      }

      configureTargetSelect();
      modeSel.onchange = configureTargetSelect;

      connect();
    }

    init();
  </script>
</body>
</html>
"""

# =========================================================
# FASTAPI + SSE
# =========================================================


# Ctrl+C fix (SSE): marcar _stop_event ANTES de que Uvicorn espere a cerrar conexiones.
# Uvicorn instala sus propios handlers; encadenamos para no romper su shutdown.
def _install_signal_hooks():
    def _chain(sig, frame, prev):
        global _subscribers,_stop_event
        try:
            _stop_event.set()
            # Forzar cierre de SSE: enviamos un último mensaje para que el cliente cierre y el generador salga.
            try:
                data = sse_pack({"type": "shutdown"})
                with _sub_lock:
                    for q in list(_subscribers):
                        try:
                            q.put_nowait(data)
                        except Exception:
                            pass
            except Exception:
                pass
        finally:
            # Encadenar al handler previo (Uvicorn) si existe
            if callable(prev):
                return prev(sig, frame)
            # Si no hay handler callable, dejamos que Python gestione KeyboardInterrupt
            if sig == signal.SIGINT:
                raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        prev = signal.getsignal(sig)
        # Evitar re-instalar si ya es nuestro handler
        if getattr(prev, "__name__", "") == "_alicia_sig_handler":
            continue

        def _alicia_sig_handler(s, f, _prev=prev):
            return _chain(s, f, _prev)

        signal.signal(sig, _alicia_sig_handler)

def init_app():
    global app,_stt_started,_stop_event,_sub_lock,_stt_started
    app = FastAPI(title=_("LliureX STT/Real-time translation"),lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _subscribers: List["queue.Queue[bytes]"] = []
    _sub_lock = threading.Lock()
    _stt_started = False

    # ==== Ctrl+C fix: parada limpia del hilo STT ====
    _stop_event = threading.Event()
    _stt_thread: Optional[threading.Thread] = None
    _install_signal_hooks()
    return app,_stt_thread,_subscribers

def sse_pack(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")

def broadcast_line(text: str) -> None:
    global _subscribers
    payload = {"type": "line", "text": text, "src_lang": INPUT_LANG}
    data = sse_pack(payload)
    with _sub_lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                pass


# =========================================================
# STT (Whisper) HILO GLOBAL
# =========================================================

def stt_worker():
    print(_("[STT] Starting Whisper ({}) for input language: {}").format(WHISPER_MODEL_NAME, INPUT_LANG))
    try:
        model = WhisperModel(
            WHISPER_MODEL_NAME,
            device=WHISPER_DEVICE,
            device_index=WHISPER_DEVICE_INDEX,
            compute_type=WHISPER_COMPUTE_TYPE,
            cpu_threads=WHISPER_CPU_THREADS,
            num_workers=WHISPER_NUM_WORKERS,
            download_root=WHISPER_DOWNLOAD_ROOT,
            local_files_only=WHISPER_LOCAL_FILES_ONLY,
            revision=WHISPER_REVISION,
            use_auth_token=WHISPER_USE_AUTH_TOKEN,
        )
    except Exception as e:
        print(_("[WARN] Failed to load Whisper model {}: {}").format(WHISPER_MODEL_NAME, e))
        raise

    audio_q: "queue.Queue[np.ndarray]" = queue.Queue()

    def audio_cb(indata, frames, time_info, status):
        # Ctrl+C fix: al parar el servidor, abortamos el callback para cerrar el stream
        if _stop_event.is_set():
            raise sd.CallbackAbort
        if status:
            print("[AUDIO]", status)
        audio_q.put(indata.copy())

    buf: List[np.ndarray] = []

    MIN_SECONDS = 5.0
    MIN_SAMPLES = int(MIN_SECONDS * RATE)

    # =========================================================
    # FILTRO ANTI-ALUCINACIONES (AULA)
    # ---------------------------------------------------------
    # Whisper tiende a "inventar" texto cuando el audio no es silencio puro
    # pero tampoco es voz clara (ruido de aula, proyector, ventilación, etc.).
    # Para mitigarlo:
    #  - Gate por energía (RMS) además de pico.
    #  - Exigir "voz" antes de llamar a transcribe (más barato y más fiable).
    #  - Evitar arrastre de contexto (condition_on_previous_text=False).
    # =========================================================

    # Umbrales (ajusta si hace falta):
    # - SILENCE_PEAK: pico máximo por debajo del cual consideramos silencio.
    # - SILENCE_RMS : energía RMS por debajo del cual consideramos silencio/ruido bajo.
    # Valores razonables para micrófonos típicos en aula.
    # Umbrales ajustables por entorno; valores definidos en ENVIRONMENT SETTINGS
    # (inicio del fichero): ALICIA_SILENCE_PEAK, ALICIA_SILENCE_RMS,
    # ALICIA_MAX_NOSPEECH, ALICIA_MIN_LOGPROB y ALICIA_DEBUG.
    SILENCE_PEAK      = ENV_SILENCE_PEAK
    SILENCE_RMS       = ENV_SILENCE_RMS
    MAX_NOSPEECH_PROB = ENV_MAX_NOSPEECH
    MIN_AVG_LOGPROB   = ENV_MIN_LOGPROB
    DEBUG_STT         = ENV_DEBUG

    # Lista de patrones típicos de alucinación en silencio/ruido.
    # Se puede ampliar sin riesgo.
    HALLUCINATION_PATTERNS = [
        "amara.org",
        "thank you for watching",
        "thanks for watching",
        "subtitles",
        "subtitle",
        "untertitel",
        "zdf",
        "closed captions",
        "cc by",
        # ES: frases/patrones típicos por ruido
        "este es el canal de subtítulos en español de la iglesia de jesucristo de los últimos días",
        "este es el canal de subtitulos en espanol de la iglesia de jesucristo de los ultimos dias",
        "este es el canal de subtítulos en español de la iglesia de jesucristo de los santos de los últimos días",
        "este es el canal de subtitulos en espanol de la iglesia de jesucristo de los santos de los ultimos dias",
        "subtítulos por la comunidad de amara.org",
        "subtitulos por la comunidad de amara.org",
        "subtítulos realizados por la comunidad de amara.org",
        "subtitulos realizados por la comunidad de amara.org",
        "subtitulado por la comunidad de amara.org",
        "subtítulos creados por la comunidad de amara.org",
        "subtitulos creados por la comunidad de amara.org",
        "subtítulos hechos por la comunidad de amara.org",
        "subtitulos hechos por la comunidad de amara.org",
        "subtítulos en español de amara.org",
        "subtitulos en espanol de amara.org",
        "gracias por ver el video",
        "gracias por ver el vídeo",
        "suscríbete a mi canal",
        "suscribete a mi canal",
        "más información",
        "mas informacion",
        # URLs concretas
        "www.alimmenta.com",
        "www.mooji.org",
    ]


    def looks_like_voice(x: np.ndarray) -> bool:
        """Heurística rápida para decidir si merece la pena transcribir."""
        if x.size == 0:
            return False
        peak = float(np.max(np.abs(x)))
        if peak < SILENCE_PEAK:
            return False
        rms = float(np.sqrt(np.mean(np.square(x))))
        if rms < SILENCE_RMS:
            return False
        return True

    def is_hallucination_line(s: str) -> bool:
        t = (s or "").strip().lower()
        if not t:
            return True

        # Normalizar espacios y puntuación final para evitar variantes triviales
        t = " ".join(t.split())
        t_cmp = t.rstrip(" .!?,;:")

        # Filtrar líneas muy cortas (típico de ruido)
        if len(t_cmp) < 2:
            return True

        # Coincidencia por substring contra lista de patrones
        for p in HALLUCINATION_PATTERNS:
            if p in t_cmp:
                return True

        return False


    prompt = PROMPT_ES if INPUT_LANG == "es" else PROMPT_CA

    def _transcription_loop(proc: Optional[subprocess.Popen] = None):
        """Bucle común de transcripción: lee de audio_q, procesa y transcribe."""
        last_log = 0.0

        while not _stop_event.is_set():
            if proc is not None and proc.poll() is not None:
                if _stop_event.is_set() or proc.returncode == 0:
                    break
                err = b""
                if proc.stderr is not None:
                    try:
                        err = proc.stderr.read() or b""
                    except Exception:
                        err = b""
                raise RuntimeError(
                    f"parec terminó (code={proc.returncode}).\n{err.decode(errors='ignore')}"
                )

            try:
                data = audio_q.get(timeout=0.5)
            except queue.Empty:
                if _stop_event.is_set():
                    break
                continue

            if data.ndim == 2:
                data = data[:, 0]
            data = data.astype(np.float32, copy=False)

            buf.append(data)
            total = sum(b.shape[0] for b in buf)

            if total < MIN_SAMPLES:
                continue

            chunk = np.concatenate(buf, axis=0)
            buf.clear()

            if chunk.size == 0:
                continue

            is_voice = looks_like_voice(chunk)
            activity_window.append(1 if is_voice else 0)

            if not is_voice:
                continue

            try:
                segments, info = model.transcribe(
                    chunk,
                    language=INPUT_LANG,
                    task=WHISPER_TASK,
                    log_progress=WHISPER_LOG_PROGRESS,
                    beam_size=WHISPER_BEAM_SIZE,
                    best_of=WHISPER_BEST_OF,
                    patience=WHISPER_PATIENCE,
                    length_penalty=WHISPER_LENGTH_PENALTY,
                    repetition_penalty=WHISPER_REPETITION_PENALTY,
                    no_repeat_ngram_size=WHISPER_NO_REPEAT_NGRAM_SIZE,
                    temperature=WHISPER_TEMPERATURE,
                    compression_ratio_threshold=WHISPER_COMPRESSION_RATIO_THRESHOLD,
                    log_prob_threshold=WHISPER_LOG_PROB_THRESHOLD,
                    no_speech_threshold=WHISPER_NO_SPEECH_THRESHOLD,
                    condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS_TEXT,
                    prompt_reset_on_temperature=WHISPER_PROMPT_RESET_ON_TEMPERATURE,
                    initial_prompt=prompt,
                    prefix=WHISPER_PREFIX,
                    suppress_blank=WHISPER_SUPPRESS_BLANK,
                    suppress_tokens=WHISPER_SUPPRESS_TOKENS,
                    without_timestamps=WHISPER_WITHOUT_TIMESTAMPS,
                    max_initial_timestamp=WHISPER_MAX_INITIAL_TIMESTAMP,
                    word_timestamps=WHISPER_WORD_TIMESTAMPS,
                    prepend_punctuations=WHISPER_PREPEND_PUNCTUATIONS,
                    append_punctuations=WHISPER_APPEND_PUNCTUATIONS,
                    multilingual=WHISPER_MULTILINGUAL,
                    vad_filter=WHISPER_VAD_FILTER,
                    vad_parameters=WHISPER_VAD_PARAMETERS,
                    max_new_tokens=WHISPER_MAX_NEW_TOKENS,
                    chunk_length=WHISPER_CHUNK_LENGTH,
                    clip_timestamps=WHISPER_CLIP_TIMESTAMPS,
                    hallucination_silence_threshold=WHISPER_HALLUCINATION_SILENCE_THRESHOLD,
                    hotwords=WHISPER_HOTWORDS,
                    language_detection_threshold=WHISPER_LANGUAGE_DETECTION_THRESHOLD,
                    language_detection_segments=WHISPER_LANGUAGE_DETECTION_SEGMENTS,
                )

                segs = list(segments)
                if not segs:
                    continue

                # Filtro de calidad por segmento: descarta los que probablemente
                # no contienen voz o tienen confianza muy baja (típico de ruido).
                valid_segs = []
                for s in segs:
                    if s.no_speech_prob < MAX_NOSPEECH_PROB and s.avg_logprob >= MIN_AVG_LOGPROB:
                        valid_segs.append(s)
                    elif DEBUG_STT:
                        print(
                            "[STT][DROP] no_speech={:.2f} logprob={:.2f} :: {}".format(
                                s.no_speech_prob, s.avg_logprob, s.text.strip()
                            )
                        )

                if not valid_segs:
                    continue

                text = "".join(s.text for s in valid_segs).strip()

                if INPUT_LANG == "es":
                    text = clean_spanish_line(text)

                if not text or is_hallucination_line(text):
                    continue

                # print(f"[STT][{INPUT_LANG}]", text)
                broadcast_line(text)

            except ValueError as e:
                msg = str(e).lower()
                if "too short" in msg or "max() iterable argument is empty" in msg:
                    continue
                now = time.time()
                if now - last_log > 5:
                    print("[STT][ERROR]", e)
                    last_log = now
                continue
            except Exception as e:
                now = time.time()
                if now - last_log > 5:
                    print("[STT][ERROR]", e)
                    last_log = now
                continue

    pulse_source = ENV_PULSE_SOURCE
    pulse_monitor = ENV_PULSE_MONITOR

    def start_pulse_producer(pulse_dev: str) -> subprocess.Popen:
        # `parec` entrega PCM raw; lo convertimos a float32 [-1,1]
        cmd = [
            "parec",
            "-d",
            pulse_dev,
            "--rate=16000",
            "--channels=1",
            "--format=s16le",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def _pump():
            assert proc.stdout is not None
            bytes_per_sample = 2  # s16le
            chunk_bytes = int(BLOCK) * bytes_per_sample
            while not _stop_event.is_set():
                b = proc.stdout.read(chunk_bytes)
                if not b:
                    break
                x = np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0
                audio_q.put(x)

        t = threading.Thread(target=_pump, name="pulse-pump", daemon=True)
        t.start()
        return proc

    def _run_pulse_loop(label: str, pulse_dev: str):
        print(_("[STT] Audio source: {} -> {}").format(label, pulse_dev))
        proc = start_pulse_producer(pulse_dev)
        print(_("[STT] Capturing audio (Pulse). Ctrl+C to stop."))

        try:
            _transcription_loop(proc=proc)
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # Prioridad: MIC por Pulse (source) -> Altavoces (monitor) -> PortAudio
    if pulse_source:
        _run_pulse_loop("MIC (Pulse source)", pulse_source)
        return

    if pulse_monitor:
        _run_pulse_loop("ALTAVOCES (monitor PipeWire/Pulse)", pulse_monitor)
        return

    with sd.InputStream(
        samplerate=RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_cb,
        blocksize=BLOCK,
    ):
        print(_("[STT] Microphone open. Ctrl+C to stop."))
        _transcription_loop()


def start_stt_if_needed():
    global _stt_started, _stt_thread
    if _stt_started:
        return
    _stt_thread = threading.Thread(target=stt_worker, daemon=True)
    _stt_thread.start()
    _stt_started = True

    # Monitor de auto-apagado por inactividad
    def auto_shutdown_check():
        while not _stop_event.is_set():
            time.sleep(10)
            if len(activity_window) < 20:
                continue
            ratio = sum(activity_window) / len(activity_window)
            if ratio < INACTIVITY_RATIO:
                print(_("[INFO] Auto-shutdown due to inactivity (Ratio: {:.4f})").format(ratio))
                _stop_event.set()
                os.kill(os.getpid(), signal.SIGINT)
                break

    t_shutdown = threading.Thread(target=auto_shutdown_check, daemon=True)
    t_shutdown.start()

def start_system_tray():
    tray = TrayIcon()
    tray.show()

    sys.exit(app.exec())

@asynccontextmanager
async def lifespan(app:FastAPI):
    start_stt_if_needed()
    open_web_with_ip("/usr/share/doc/traduia/show-server.html", port=8000)
    yield
    _stop_event.set()
    # Espera corta (no bloqueante) para salida limpia
    if _stt_thread and _stt_thread.is_alive():
        _stt_thread.join(timeout=2.0)

app,_stt_thread,_subscribers = init_app()

# DEPRECATED
# @app.on_event("startup")
# def on_startup():

# @app.on_event("shutdown")
# def on_shutdown():
#     # Ctrl+C fix: señalamos parada para que el hilo STT cierre el InputStream

@app.get("/health")
def health():
    return {"ok": True, "input_lang": INPUT_LANG}

@app.get("/activity")
def get_activity():
    if not activity_window:
        return {"ratio": 0.0, "is_active": False, "samples": 0}

    ratio = sum(activity_window) / len(activity_window)
    is_active = ratio > INACTIVITY_RATIO

    return {
        "ratio": round(ratio, 4),
        "is_active": is_active,
        "samples": len(activity_window),
        "window_mins": MONITOR_WINDOW_MINS
    }

@app.get("/", include_in_schema=False)
def root():
    i18n_json = json.dumps(get_i18n_data(), ensure_ascii=False)
    return HTMLResponse(HTML_CLIENT.replace("{{I18N_DATA}}", i18n_json))


@app.get("/alicia.png", include_in_schema=False)
def alicia_png():
    """
    Sirve alicia.png desde el mismo directorio que este .py
    """
    path = BASE_DIR / "alicia.png"
    if not path.exists():
        return JSONResponse(
            status_code=404, content={"error": _("alicia.png not found")}
        )
    return FileResponse(path, media_type="image/png")


# =========================================================
# SSE STREAM
# =========================================================

@app.get("/stream")
def stream():
    global _subscribers
    client_q: "queue.Queue[bytes]" = queue.Queue()
    with _sub_lock:
        _subscribers.append(client_q)

    def gen() -> Iterator[bytes]:
        global _subscribers,_stop_event,_sub_lock
        try:
            while not _stop_event.is_set():
                try:
                    data = client_q.get(timeout=0.8)
                    yield data
                    if b'"type": "shutdown"' in data:
                        break
                except queue.Empty:
                    if _stop_event.is_set():
                        break
                    yield b": keep-alive\n\n"
        except GeneratorExit:
            with _sub_lock:
                if client_q in _subscribers:
                    _subscribers.remove(client_q)

    return StreamingResponse(gen(), media_type="text/event-stream")

# =========================================================
# /translate
# =========================================================

class TranslateRequest(BaseModel):
    text: str
    target_lang: str


class TranslateResponse(BaseModel):
    text: str


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest):
    target = req.target_lang.lower()
    if target not in ("en", "fr", "de", "ru", "ar", "uk", "ro", "it"):
        return JSONResponse(
            status_code=400,
            content={"error": _("Supported languages: en, fr, de, ru, ar, uk, ro, it")},
        )
    txt = req.text.strip()
    if not txt:
        return TranslateResponse(text="")
    out = translate_text(txt, target)
    return TranslateResponse(text=out)

# =========================================================
# PUNTO DE ENTRADA
# =========================================================
class FastApiThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = None

    def run(self):
        try:
            config = uvicorn.Config(app, host="0.0.0.0", port=8000, reload=False)
            self.server = uvicorn.Server(config)
            self.server.install_signal_handlers = lambda: None  # Override to prevent installing signal handlers
            self.server.run()
        except Exception as e:
            print(f"[API][ERROR] {e}")

    def stop(self):
        if self.server:
            self.server.should_exit = True

class TrayIcon(QSystemTrayIcon):
    def __init__(self):
        super().__init__()
        self._setup_icon()
        self._setup_menu()
        self.activated.connect(self._on_tray_activated)
        self.api_thread = FastApiThread()

        # Timer para actualizar el ratio de actividad en el widget
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_activity_info)
        self.timer.start(10000)  # 10 segundos
        self._update_activity_info()

    def _update_activity_info(self):
        if not activity_window:
            status_text = _("Activity: Wait...")
        else:
            ratio = sum(activity_window) / len(activity_window)
            is_active = ratio > INACTIVITY_RATIO
            status = _("Active") if is_active else _("Inactive")
            status_text = _("Activity: {} ({:.1%})").format(status, ratio)

        self.setToolTip(f"{_('TraduIA Server')}\n{status_text}")
        if hasattr(self, "status_action"):
            self.status_action.setText(status_text)

    def _setup_icon(self):
        image_path = '/usr/share/icons/hicolor/128x128/apps/traduia.png'

        if image_path and os.path.exists(image_path):
            icon = QIcon(image_path)
        else:
            icon = QIcon.fromTheme("application-x-executable")

        self.setIcon(icon)
        self.setToolTip(_("TraduIA Server"))

    def _setup_menu(self):
        menu = QMenu()

        self.status_action = menu.addAction(_("Activity: Wait..."))
        self.status_action.setDisabled(True)
        menu.addSeparator()

        exit_action = menu.addAction(_("Exit"))
        exit_action.triggered.connect(self._on_exit)
        self.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        # if reason == QSystemTrayIcon.ActivationReason.Trigger:
        #     pos = QCursor.pos()
        #     menu = self.contextMenu()
        #     if menu:
        #         menu_size = menu.sizeHint()
        #         print(f"Widget position: x={pos.x()} y={pos.y()} | Menu size: x={menu_size.width()} y={menu_size.height()}")
        #         if menu.isVisible():
        #             menu.hide()
        #         else:
        #             screen = QApplication.primaryScreen()
        #             screen_geometry = screen.geometry()
        #             popup_pos = QPoint(
        #                 screen_geometry.x() + (screen_geometry.width() - menu_size.width()) // 2,
        #                 screen_geometry.y() + (screen_geometry.height() - menu_size.height()) // 2
        #             )
        #             popup_pos = QPoint(
        #                 pos.x()+35,
        #                 pos.y()-menu_size.height()+25
        #             )
        #             print(f"Popup position: x={popup_pos.x()} y={popup_pos.y()}")
        #             QTimer.singleShot(0, lambda p=popup_pos, m=menu: m.popup(p))
        # el
        if reason == QSystemTrayIcon.ActivationReason.Context:
            menu = self.contextMenu()
            if menu:
                menu.hide()
                QTimer.singleShot(0, lambda: menu.popup(QCursor.pos()))

    def _on_exit(self):
        QApplication.quit()

def _ensure_single_instance():
    lock_file = "/tmp/traduia_server.lock"
    port = 8000
    current_pid = os.getpid()

    # 1. Kill any process that looks like traduia_server.py or is using port 8000
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.pid == current_pid:
                continue

            should_kill = False
            # Check cmdline
            cmdline = proc.info.get('cmdline')
            if cmdline and any("traduia_server.py" in arg for arg in cmdline):
                should_kill = True

            # Check port (if possible)
            if not should_kill:
                try:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port == port:
                            should_kill = True
                            break
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

            if should_kill:
                print(_("[INFO] Stopping previous instance (PID {})...").format(proc.pid))
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    print(_("[INFO] Forcing stop (KILL) of PID {}...").format(proc.pid))
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2. Manage lock file to be extra safe
    try:
        f = open(lock_file, "a+")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.seek(0)
        f.truncate()
        f.write(str(current_pid))
        f.flush()
        return f
    except Exception as e:
        print(f"[WARNING] Lock file check failed: {e}")
        return None

if __name__ == "__main__":
    _lock_f = _ensure_single_instance()

    qt_tray = QApplication(sys.argv)
    qt_tray.setQuitOnLastWindowClosed(False)

    def signal_handler(sig, frame):
        QApplication.quit()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Timer to allow processing signals in the Qt event loop
    _sig_timer = QTimer()
    _sig_timer.start(500)
    _sig_timer.timeout.connect(lambda: None)

    tray = TrayIcon()
    tray.show()

    # Small delay to ensure the previous instance has fully released the port
    # before we attempt to bind to it in the background thread.
    QTimer.singleShot(500, tray.api_thread.start)

    try:
        res = qt_tray.exec()
    except:
        res = qt_tray.exec_()

    # Clean shutdown
    print(_("[INFO] Cleaning up..."))
    tray.hide()
    tray.api_thread.stop()
    tray.api_thread.join(timeout=3.0)
    sys.exit(res)

