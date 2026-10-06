#!/usr/bin/env python3
"""TraduIA translation cache self-test.

Runs from a git clone against a server installation:

    tests/test-translation-cache
    TRADUIA_SERVER_DIR=/usr/lib/traduia tests/test-translation-cache

Checks the single-flight translation cache: duplicated concurrent requests
run a single inference per model pair, the CA->ES pivot is shared between
targets, failures are not cached, expired entries are recomputed and a single
worker preserves the sequential order.
"""
import asyncio
import concurrent.futures
import sys
import threading
import time
import unittest

import common

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
    print("[DEBUG] translate_workers=%s" % ts.ENV_TRANSLATE_WORKERS, flush=True)


class _CountingTranslate:
    """Wraps ts._translate_text to count calls per engine and add delays."""

    def __init__(self, delays=None):
        self.original = ts._translate_text
        self.delays = delays or {}
        self.counts = {}
        self.lock = threading.Lock()

    def __call__(self, text, tok, engine):
        with self.lock:
            self.counts[id(engine)] = self.counts.get(id(engine), 0) + 1
        delay = self.delays.get(text)
        if delay:
            time.sleep(delay)
        return self.original(text, tok, engine)


class TestTranslationCache(unittest.TestCase):
    def setUp(self):
        self._orig_translate = ts._translate_text
        self._orig_input_lang = ts.INPUT_LANG
        ts._TR_CACHE.clear()
        ts._TR_PENDING.clear()

    def tearDown(self):
        ts._translate_text = self._orig_translate
        ts.INPUT_LANG = self._orig_input_lang
        ts._TR_CACHE.clear()
        ts._TR_PENDING.clear()

    def _install_counter(self, delays=None):
        counter = _CountingTranslate(delays)
        ts._translate_text = counter
        return counter

    def test_same_pair_single_flight(self):
        ts.INPUT_LANG = "es"
        counter = self._install_counter()
        text = "La maestra explica la lección."

        async def run_all():
            return await asyncio.gather(
                *(ts.translate_text_async(text, "de") for _ in range(10))
            )

        results = asyncio.run(run_all())
        self.assertEqual(
            sum(counter.counts.values()), 1,
            "expected a single inference for 10 identical requests",
        )
        self.assertEqual(len(counter.counts), 1)
        for translated in results:
            self.assertTrue(translated.strip())
            self.assertNotIn("[NO SOPORTADO", translated)

    def test_pivot_shared_between_targets(self):
        ts.INPUT_LANG = "ca"
        counter = self._install_counter()
        text = "Bon dia, xiquets i xiquetes."
        targets = ("de", "fr", "it")

        async def run_all():
            return await asyncio.gather(
                *(ts.translate_text_async(text, target) for target in targets)
            )

        results = asyncio.run(run_all())
        self.assertEqual(
            sum(counter.counts.values()), 4,
            "expected CA->ES once plus one inference per target",
        )
        self.assertEqual(max(counter.counts.values()), 1)
        for translated in results:
            self.assertTrue(translated.strip())
            self.assertNotIn("[NO SOPORTADO", translated)

    def test_failure_is_not_cached(self):
        ts.INPUT_LANG = "es"
        text = "Frase que falla."
        calls = {"n": 0}

        def boom(_text, _tok, _engine):
            calls["n"] += 1
            raise RuntimeError("forced failure")

        ts._translate_text = boom

        async def run_all():
            return await asyncio.gather(
                *(ts.translate_text_async(text, "it") for _ in range(5)),
                return_exceptions=True,
            )

        results = asyncio.run(run_all())
        self.assertTrue(all(isinstance(r, RuntimeError) for r in results))
        self.assertEqual(calls["n"], 1, "waiters must not recompute a failed key")
        self.assertFalse(ts._TR_PENDING, "pending entry must be cleaned on failure")

        ts._translate_text = self._orig_translate
        translated = asyncio.run(ts.translate_text_async(text, "it"))
        self.assertTrue(translated.strip())
        self.assertNotIn("[NO SOPORTADO", translated)

    def test_ttl_expiry(self):
        ts.INPUT_LANG = "es"
        counter = self._install_counter()
        text = "Los alumnos escuchan atentamente."
        old_ttl = ts._TR_CACHE_TTL
        ts._TR_CACHE_TTL = 0.05
        try:
            asyncio.run(ts.translate_text_async(text, "uk"))
            time.sleep(0.1)
            asyncio.run(ts.translate_text_async(text, "uk"))
        finally:
            ts._TR_CACHE_TTL = old_ttl
        self.assertEqual(
            sum(counter.counts.values()), 2,
            "expired entries must be recomputed",
        )

    def test_sequential_order_with_one_worker(self):
        ts.INPUT_LANG = "es"
        old_executor = ts._TR_EXECUTOR
        ts._TR_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        original = self._orig_translate
        completion = []

        def delayed(text, tok, engine):
            time.sleep(0.4 if text == "Primera frase." else 0.05)
            completion.append(text)
            return original(text, tok, engine)

        ts._translate_text = delayed
        try:
            async def run_all():
                first = asyncio.create_task(
                    ts.translate_text_async("Primera frase.", "de")
                )
                await asyncio.sleep(0.01)
                second = asyncio.create_task(
                    ts.translate_text_async("Segunda frase.", "de")
                )
                return await asyncio.gather(first, second)

            results = asyncio.run(run_all())
        finally:
            ts._translate_text = original
            ts._TR_EXECUTOR.shutdown(wait=False)
            ts._TR_EXECUTOR = old_executor

        self.assertEqual(completion, ["Primera frase.", "Segunda frase."])
        for translated in results:
            self.assertTrue(translated.strip())
            self.assertNotIn("[NO SOPORTADO", translated)


if __name__ == "__main__":
    test_runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    unittest.main(testRunner=test_runner)
