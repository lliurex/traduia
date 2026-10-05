#!/usr/bin/env python3
"""TraduIA translation self-test.

Runs from a git clone against a server installation:

    tests/test-translation
    TRADUIA_SERVER_DIR=/usr/lib/traduia tests/test-translation

Unless TRADUIA_SERVER_DIR is set, it asks interactively which server to
import (system or repo). No default is applied.
"""
import asyncio
import sys
import unittest

import common

TARGETS = ("en", "fr", "de", "ru", "ar", "uk", "ro", "it")

PHRASES = {
    "es": [
        "Buenos días, niños y niñas.",
        "Hoy empiezan las clases.",
        "La maestra explica la lección.",
        "Los alumnos escuchan atentamente.",
        "¿Puedes repetir la última frase, por favor?",
        "El examen será el próximo viernes.",
    ],
    "ca": [
        "Bon dia, xiquets i xiquetes.",
        "A hui comencen les classes.",
        "La mestra explica la lliçó.",
        "Els alumnes escolten atentament.",
        "Pots repetir l'última frase, per favor?",
        "L'examen serà el pròxim divendres.",
    ],
}

SERVER_KIND, SERVER_DIR = common.resolve_server()
if not common.check_installed(SERVER_DIR):
    sys.exit(1)

common.setup_env()
ts = common.import_server(SERVER_DIR)
if ts is None:
    sys.exit(1)

if not common.check_whisper(ts):
    sys.exit(1)

if not common.check_model_pairs(ts):
    sys.exit(1)

if common.DEBUG:
    print("[DEBUG] server=%s server_dir=%s" % (SERVER_KIND, SERVER_DIR), flush=True)
    print("[DEBUG] mode=%s" % ("ct2" if getattr(ts, "USE_CT2", False) else "marian"), flush=True)
    print("[DEBUG] input_lang=%s" % ts.INPUT_LANG, flush=True)


class TestParallelTranslations(unittest.TestCase):
    def test_parallel_translations(self):
        phrases = PHRASES.get(ts.INPUT_LANG, PHRASES["es"])
        jobs = [(phrases[i % len(phrases)], target) for i, target in enumerate(TARGETS)]
        jobs.append((phrases[0], "en"))
        jobs.append((phrases[1], "fr"))

        async def work(index, text, target):
            translated = await ts.translate_text_async(text, target)
            print("[%s] %s --> %s" % (target, text, translated), flush=True)
            return translated

        async def run_all():
            return await asyncio.gather(
                *(work(index, text, target) for index, (text, target) in enumerate(jobs))
            )

        results = asyncio.run(run_all())

        failures = 0
        for index, (text, target) in enumerate(jobs):
            translated = results[index]
            if not isinstance(translated, str) or not translated.strip() or "[NO SOPORTADO" in translated:
                failures += 1
                print("[ERROR] %s -> %s: %r" % (text, target, translated), flush=True)
        self.assertEqual(failures, 0, "%d translation(s) failed" % failures)
        print("[INFO] %d parallel translations completed" % len(jobs), flush=True)


if __name__ == "__main__":
    test_runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    unittest.main(testRunner=test_runner)
