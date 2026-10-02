#!/usr/bin/env python3
"""TraduIA transcription self-test (Whisper engine).

Runs from a git clone against a server installation:

    tests/test-transcription
    TRADUIA_SERVER_DIR=/usr/lib/traduia tests/test-transcription

It captures the default speakers (PulseAudio monitor) and runs the real
traduia_server.stt_worker() pipeline until Ctrl+C, printing the recognized
text as "[STT] <text>". No code is copied: the server module is imported and
its worker is executed as-is.
"""
import os
import sys
import threading

import common

SERVER_KIND, SERVER_DIR = common.resolve_server()
if not common.check_installed(SERVER_DIR):
    sys.exit(1)

monitor = common.resolve_monitor()
if not common.check_audio(monitor):
    sys.exit(1)

common.setup_env()
os.environ["ALICIA_PULSE_SOURCE"] = ""
os.environ["ALICIA_PULSE_MONITOR"] = monitor

ts = common.import_server(SERVER_DIR)
if ts is None:
    sys.exit(1)

if not common.check_whisper(ts):
    sys.exit(1)

if common.DEBUG:
    print("[DEBUG] server=%s server_dir=%s" % (SERVER_KIND, SERVER_DIR), flush=True)
    print("[DEBUG] input_lang=%s" % ts.INPUT_LANG, flush=True)
    print("[DEBUG] monitor=%s" % monitor, flush=True)

# Only the output sink is replaced: the transcription pipeline stays intact.
ts.broadcast_line = lambda text: print("[STT] %s" % text, flush=True)

print("[INFO] ready and listening, play some sounds for transcript (end with control+c)", flush=True)

worker_error = []


def _run_worker():
    try:
        ts.stt_worker()
    except BaseException as exc:  # noqa: BLE001 - reported after join
        worker_error.append(exc)


worker = threading.Thread(target=_run_worker, name="stt-worker", daemon=True)
worker.start()

try:
    while worker.is_alive():
        worker.join(timeout=0.5)
except KeyboardInterrupt:
    pass

if worker.is_alive():
    ts._stop_event.set()
    worker.join(timeout=10)

if worker.is_alive():
    print("[ERROR] transcription worker did not stop", flush=True)
    sys.exit(1)

if worker_error:
    print("[ERROR] %s: %s" % (type(worker_error[0]).__name__, worker_error[0]), flush=True)
    sys.exit(1)

print("[INFO] stopped", flush=True)
