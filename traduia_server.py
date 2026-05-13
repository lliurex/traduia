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

    webbrowser.open(url)

import json
import queue
import threading
import time
import subprocess
import signal
import fcntl
import psutil
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
from transformers import MarianMTModel, MarianTokenizer
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
# CONFIG GENERAL
# =========================================================

RATE = 16000
CHANNELS = 1
BLOCK = RATE // 10  # ~100 ms

INPUT_LANG = (os.getenv("ALICIA_INPUT_LANG", "es") or "es").strip().split("|")[0].strip()
if INPUT_LANG not in ("es", "ca"):
    INPUT_LANG = "es"

PROMPT_CA = (
    "Valencià, amb paraules com xiquet, faena, espill, hui, eixir, cotxera, "
    "llepolies, orxata, espenta, menut, celler."
)
PROMPT_ES = (
    "Español de España, con palabras como coche, ordenador, móvil, "
    "vámonos, trabajo, gafas, libreta."
)

WHISPER_MODEL_NAME = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# BASE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path('/usr/lib/traduia')
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

# CA -> EN/ES
MARIAN_CA_EN = "Helsinki-NLP/opus-mt-ca-en"
MARIAN_CA_ES = "Helsinki-NLP/opus-mt-ca-es"

# Caches
_m_es_tok = {}
_m_es_model = {}
_m_ca_tok = {}
_m_ca_model = {}


def _load_marian(model_name: str,
                 cache_tok: dict,
                 cache_model: dict) -> Tuple[MarianTokenizer, MarianMTModel]:
    if model_name not in cache_tok or model_name not in cache_model:
        tok = MarianTokenizer.from_pretrained(model_name)
        model = MarianMTModel.from_pretrained(model_name)
        cache_tok[model_name] = tok
        cache_model[model_name] = model
    return cache_tok[model_name], cache_model[model_name]


def translate_from_es(text: str, target: str) -> str:
    mapping = {
        "en": MARIAN_ES_EN,
        "fr": MARIAN_ES_FR,
        "de": MARIAN_ES_DE,
        "ru": MARIAN_ES_RU,
        "ar": MARIAN_ES_AR,
        "uk": MARIAN_ES_UK,
        "ro": MARIAN_ES_RO,
    }
    if target not in mapping:
        return f"[NO SOPORTADO ES->{target}]"
    model_name = mapping[target]
    tok, model = _load_marian(model_name, _m_es_tok, _m_es_model)
    batch = tok([text], return_tensors="pt", padding=True, truncation=True)
    gen = model.generate(**batch, max_length=512)
    out = tok.batch_decode(gen, skip_special_tokens=True)
    return out[0] if out else ""


def translate_from_ca(text: str, target: str) -> str:
    """
    CA -> EN directo con opus-mt-ca-en.
    CA -> X (fr,de,ru,ar,uk,ro) vía CA->ES + ES->X.
    """
    txt = text.strip()
    if not txt:
        return ""

    # CA -> EN
    if target == "en":
        tok, model = _load_marian(MARIAN_CA_EN, _m_ca_tok, _m_ca_model)
        batch = tok([txt], return_tensors="pt", padding=True, truncation=True)
        gen = model.generate(**batch, max_length=512)
        out = tok.batch_decode(gen, skip_special_tokens=True)
        return out[0] if out else ""

    # CA -> ES
    tok_ca_es, model_ca_es = _load_marian(MARIAN_CA_ES, _m_ca_tok, _m_ca_model)
    batch_es = tok_ca_es([txt], return_tensors="pt", padding=True, truncation=True)
    gen_es = model_ca_es.generate(**batch_es, max_length=512)
    out_es = tok_ca_es.batch_decode(gen_es, skip_special_tokens=True)
    if not out_es:
        return ""
    text_es = out_es[0]

    # ES -> target
    return translate_from_es(text_es, target)


def translate_text(text: str, target: str) -> str:
    target = target.lower()
    if target not in ("en", "fr", "de", "ru", "ar", "uk", "ro"):
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
            'subtitle': _t("Connected to teacher's classroom · Text in your language"),
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
                'ro': _t("Romanian"), 'es': _t("Spanish"), 'ca': _t("Valencian")
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
      font-size: 18px;
      font-weight: 600;
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
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 150px;
    }
    .field-label {
      font-size: 11px;
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
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                   "Liberation Mono", "Courier New", monospace;
      font-size: 13px;
      background: radial-gradient(circle at top left, rgba(15, 23, 42, 0.9), #020617);
      color: #e5e7eb;
      outline: none;
      line-height: 1.5;
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
          <span id="subtitle">...</span>
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

        <div class="pill" id="status-pill">
          <span class="pill-dot" id="status-dot"></span>
          <span id="status-text">...</span>
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
        ["en", "fr", "de", "ru", "ar", "uk", "ro"].forEach(t => {
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
      subtitle.textContent = d.subtitle;
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
    model = WhisperModel(
        WHISPER_MODEL_NAME,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )

    audio_q: "queue.Queue[np.ndarray]" = queue.Queue()

    def audio_cb(indata, frames, time_info, status):
        # Ctrl+C fix: al parar el servidor, abortamos el callback para cerrar el stream
        if _stop_event.is_set():
            raise sd.CallbackAbort
        if status:
            print("[AUDIO]", status)
        audio_q.put(indata.copy())

    buf: List[np.ndarray] = []
    total = 0

    MIN_SECONDS = 3.0
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
    SILENCE_PEAK = float(os.getenv("ALICIA_SILENCE_PEAK", "0.0015"))
    SILENCE_RMS  = float(os.getenv("ALICIA_SILENCE_RMS",  "0.0040"))

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


    # Si llevamos muchos chunks sin voz, reseteamos el buffer de "contexto"
    # (en nuestro caso, al no arrastrar contexto, simplemente sirve para estadísticas/log).
    silence_streak = 0
    last_log = 0.0

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

    # =========================================================
    # FUENTE DE AUDIO
    # - Por defecto: sounddevice (PortAudio) -> micrófonos
    # - Si ALICIA_PULSE_MONITOR está definido: capturamos audio del sistema
    #   (lo que suena por los altavoces) vía `parec` (PipeWire/PulseAudio).
    #   Esto evita el problema de que PortAudio no exponga los *.monitor.
    # =========================================================

    pulse_source = (os.getenv("ALICIA_PULSE_SOURCE") or "").strip()
    pulse_monitor = (os.getenv("ALICIA_PULSE_MONITOR") or "").strip()

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

    def _run_pulse_loop(label: str, pulse_dev: str, beam_size: int):
        print(_("[STT] Audio source: {} -> {}").format(label, pulse_dev))
        proc = start_pulse_producer(pulse_dev)
        print(_("[STT] Capturing audio (Pulse). Ctrl+C to stop."))

        try:
            while not _stop_event.is_set():
                try:
                    data = audio_q.get(timeout=0.5)
                except queue.Empty:
                    if _stop_event.is_set():
                        break
                    if proc.poll() is not None:
                        # If the process finished with code 0 and we are stopping, it's normal.
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
                    continue

                data = data.astype(np.float32, copy=False)
                buf.append(data)
                total_samples = sum(b.shape[0] for b in buf)
                if total_samples < MIN_SAMPLES:
                    continue

                chunk = np.concatenate(buf, axis=0)
                buf.clear()

                if chunk.size == 0 or not looks_like_voice(chunk):
                    continue

                try:
                    segments, info = model.transcribe(
                        chunk,
                        language=INPUT_LANG,
                        task="transcribe",
                        vad_filter=True,
                        vad_parameters=dict(
                            min_silence_duration_ms=300,
                            speech_pad_ms=200,
                        ),
                        beam_size=beam_size,
                        condition_on_previous_text=False,
                        initial_prompt=prompt,
                    )
                    text = " ".join([s.text.strip() for s in segments]).strip()
                    if INPUT_LANG == "es":
                        text = clean_spanish_line(text)
                    if is_hallucination_line(text):
                        continue
                    broadcast_line(text)
                except Exception as e:
                    print("[STT][ERROR]", repr(e))
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
        _run_pulse_loop("MIC (Pulse source)", pulse_source, beam_size=5)
        return

    if pulse_monitor:
        _run_pulse_loop("ALTAVOCES (monitor PipeWire/Pulse)", pulse_monitor, beam_size=1)
        return

# ---- MICRÓFONO (PortAudio) ----
    with sd.InputStream(
        samplerate=RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_cb,
        blocksize=BLOCK,
    ):
        print(_("[STT] Microphone open. Ctrl+C to stop."))
        while True:
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
            total += data.shape[0]

            if total < MIN_SAMPLES:
                continue

            chunk = np.concatenate(buf, axis=0)
            buf.clear()
            total = 0

            if chunk.size == 0:
                continue

            if not looks_like_voice(chunk):
                silence_streak += 1
                # No transcribimos ruido/ambigüedad -> reduce alucinaciones.
                continue
            else:
                silence_streak = 0


            try:
                segments, info = model.transcribe(
                    chunk,
                    language=INPUT_LANG,
                    task="transcribe",
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=300,
                        speech_pad_ms=200,
                    ),
                    beam_size=5,
                    condition_on_previous_text=False,  # streaming: evita arrastre de alucinaciones
                    initial_prompt=prompt,
                )

                segs = list(segments)
                if not segs:
                    continue
                line = "".join(s.text for s in segs).strip()

                if INPUT_LANG == "es":
                    line = clean_spanish_line(line)

                if not line:
                    continue

                # Defensa extra: filtrar patrones típicos de alucinación en ruido/silencio.
                if is_hallucination_line(line):
                    continue

                print(f"[STT][{INPUT_LANG}]", line)
                broadcast_line(line)

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


def start_stt_if_needed():
    global _stt_started, _stt_thread
    if _stt_started:
        return
    _stt_thread = threading.Thread(target=stt_worker, daemon=True)
    _stt_thread.start()
    _stt_started = True

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
    if target not in ("en", "fr", "de", "ru", "ar", "uk", "ro"):
        return JSONResponse(
            status_code=400,
            content={"error": _("Supported languages: en, fr, de, ru, ar, uk, ro")},
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

