#!/usr/bin/env python3
"""Shared bootstrap for the TraduIA self-tests.

Both tests/test_translation.py and tests/test_transcription.py import this
module to ask which server to load (system or repo), prepare the environment
and print the "checking ... [ok]" lines.
"""
import contextlib
import io
import os
import subprocess
import sys

sys.dont_write_bytecode = True

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)

SYSTEM_SERVER_DIR = "/usr/lib/traduia"
VENV_PY = "/opt/ai/traduia/venv/bin/python3"
MODELS_ROOT = "/opt/ai/traduia/models"

DEBUG = os.environ.get("TRADUIA_TEST_DEBUG") == "1"


def ask_server():
    while True:
        print("Select server to import:", flush=True)
        print("  1) system server (%s)" % SYSTEM_SERVER_DIR, flush=True)
        print("  2) repo server (%s)" % REPO_DIR, flush=True)
        try:
            choice = input("Choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ERROR] no server selected", flush=True)
            sys.exit(1)
        if choice == "1":
            return "system", SYSTEM_SERVER_DIR
        if choice == "2":
            return "repo", REPO_DIR
        print("[ERROR] invalid choice %r; enter 1 or 2" % choice, flush=True)


def resolve_server():
    env_dir = os.environ.get("TRADUIA_SERVER_DIR", "").strip()
    if env_dir:
        return "env", env_dir
    return ask_server()


def check(name):
    print("checking %s .... " % name, end="", flush=True)


def ok():
    print("[ok]", flush=True)


def fail(message):
    print("[ERROR] %s" % message, flush=True)


def _input_lang_from_config():
    conf = os.path.expanduser("~/.config/alicia-transcriptor/config.env")
    try:
        with open(conf, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("ALICIA_INPUT_LANG="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def setup_env():
    """Same environment the launcher exports, before importing the server."""
    os.environ.setdefault("HF_HOME", MODELS_ROOT)
    os.environ.setdefault("HF_HUB_CACHE", os.path.join(os.environ["HF_HOME"], "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.environ["HF_HOME"])
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    if not os.environ.get("ALICIA_INPUT_LANG"):
        lang = _input_lang_from_config()
        if lang:
            os.environ["ALICIA_INPUT_LANG"] = lang


def check_installed(server_dir):
    check("installed")
    problems = []
    server_file = os.path.join(server_dir, "traduia_server.py")
    if not os.path.isfile(server_file):
        problems.append("%s not found" % server_file)
    if not (os.path.isfile(VENV_PY) and os.access(VENV_PY, os.X_OK)):
        problems.append("%s not found" % VENV_PY)
    if problems:
        fail("; ".join(problems))
        return False
    ok()
    return True


def import_server(server_dir):
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    check("dependencies")
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            import traduia_server
            if getattr(traduia_server, "USE_CT2", False):
                import ctranslate2  # noqa: F401
    except Exception as exc:
        fail("%s: %s" % (type(exc).__name__, exc))
        text = captured.getvalue().strip()
        if text:
            print(text, flush=True)
        return None
    ok()
    text = captured.getvalue().strip()
    if text:
        print(text, flush=True)
    try:
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
    except Exception:
        pass
    return traduia_server


def check_whisper(server):
    check("whisper model")
    whisper_dir = getattr(server, "WHISPER_LOCAL_DIR", None)
    model_bin = os.path.join(str(whisper_dir), "model.bin") if whisper_dir else ""
    if not model_bin or not os.path.isfile(model_bin) or os.path.getsize(model_bin) == 0:
        fail("whisper model not found: %s" % model_bin)
        return False
    ok()
    return True


def check_model_pairs(server):
    check("model pairs")
    if getattr(server, "USE_CT2", False):
        subdir, file_name = "ct2", "model.bin"
    else:
        subdir, file_name = "marian", "pytorch_model.bin"
    missing = []
    for pair in server.MARIAN_PAIRS:
        path = server.MODEL_ROOT / subdir / ("opus-mt-%s" % pair) / file_name
        try:
            if not path.is_file() or path.stat().st_size == 0:
                missing.append("opus-mt-%s" % pair)
        except OSError:
            missing.append("opus-mt-%s" % pair)
    if missing:
        fail("missing %s pairs: %s" % (subdir, ", ".join(missing)))
        return False
    ok()
    return True


def _pactl(args):
    try:
        result = subprocess.run(
            ["pactl"] + args, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()
    except Exception:
        return ""


def resolve_monitor():
    """Monitor source of the default sink (or the first .monitor available)."""
    default_sink = _pactl(["get-default-sink"])
    sources = _pactl(["list", "short", "sources"])
    names = []
    for line in sources.splitlines():
        parts = line.split()
        if len(parts) > 1:
            names.append(parts[1])
    if default_sink:
        monitor = default_sink + ".monitor"
        if monitor in names:
            return monitor
    for name in names:
        if name.endswith(".monitor"):
            return name
    return ""


def check_audio(monitor):
    check("audio (speakers)")
    if not monitor:
        fail("no PulseAudio monitor source found (pactl)")
        return False
    ok()
    return True
