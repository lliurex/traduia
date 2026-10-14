#!/usr/bin/env python3
"""TraduIA WebSocket hub self-test.

Runs from a git clone against a server installation:

    tests/test-ws-hub
    TRADUIA_SERVER_DIR=/usr/lib/traduia tests/test-ws-hub

Checks the WebSocket hub: original lines go straight to original-mode clients,
translated lines are computed once per language and fanned out to every
subscriber of that language, the per-language order is preserved, translation
errors are reported as flagged lines, 'set' messages are normalised and slow
clients are dropped.
"""
import asyncio
import sys
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

if common.DEBUG:
    print("[DEBUG] server=%s server_dir=%s" % (SERVER_KIND, SERVER_DIR), flush=True)
    print("[DEBUG] mode=%s" % ("ct2" if getattr(ts, "USE_CT2", False) else "marian"), flush=True)


class _FakeWebSocket:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def _register(mode="original", target=None, maxsize=64):
    """Registra una conexión falsa en el hub; devuelve su estado."""
    ws = _FakeWebSocket()
    state = {
        "ws": ws,
        "mode": mode,
        "target": target,
        "out_q": asyncio.Queue(maxsize=maxsize),
    }
    ts._ws_clients[ws] = state
    return state


async def _get(state):
    return await asyncio.wait_for(state["out_q"].get(), timeout=5)


class TestWsHub(unittest.TestCase):
    def setUp(self):
        self._orig_translate = ts.translate_text_async
        ts._ws_clients.clear()
        ts._lang_queues.clear()
        ts._lang_tasks.clear()
        ts._TR_CACHE.clear()
        ts._TR_PENDING.clear()

    def tearDown(self):
        ts.translate_text_async = self._orig_translate
        ts._ws_clients.clear()
        ts._lang_queues.clear()
        ts._lang_tasks.clear()
        ts._TR_CACHE.clear()
        ts._TR_PENDING.clear()

    def _install_translate(self, delays=None, error=False):
        calls = {"n": 0, "texts": []}

        async def fake(text, target):
            calls["n"] += 1
            calls["texts"].append((target, text))
            delay = (delays or {}).get(text)
            if delay:
                await asyncio.sleep(delay)
            if error:
                raise RuntimeError("boom")
            return "[%s] %s" % (target, text)

        ts.translate_text_async = fake
        return calls

    def test_dispatch_original(self):
        async def main():
            state = _register(mode="original")
            await ts._dispatch_line("Hola")
            return await _get(state)

        payload = asyncio.run(main())
        self.assertEqual(payload["type"], "line")
        self.assertEqual(payload["text"], "Hola")
        self.assertIsNone(payload["target"])
        self.assertFalse(payload["error"])

    def test_translate_once_per_language_and_fanout(self):
        calls = self._install_translate()

        async def main():
            ts._start_language_workers()
            try:
                s1 = _register(mode="translate", target="de")
                s2 = _register(mode="translate", target="de")
                s3 = _register(mode="original")
                await ts._dispatch_line("Buenos días")
                return await _get(s1), await _get(s2), await _get(s3)
            finally:
                await ts._stop_language_workers()

        p1, p2, p3 = asyncio.run(main())
        self.assertEqual(calls["n"], 1, "expected a single inference per language")
        self.assertEqual(p1["target"], "de")
        self.assertEqual(p2["text"], "[de] Buenos días")
        self.assertIsNone(p3["target"])
        self.assertEqual(p3["text"], "Buenos días")

    def test_order_preserved_per_language(self):
        self._install_translate(delays={"uno": 0.05, "dos": 0.0, "tres": 0.0})

        async def main():
            ts._start_language_workers()
            try:
                state = _register(mode="translate", target="fr")
                for text in ("uno", "dos", "tres"):
                    await ts._dispatch_line(text)
                return [await _get(state) for _ in range(3)]
            finally:
                await ts._stop_language_workers()

        payloads = asyncio.run(main())
        seqs = [p["seq"] for p in payloads]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual([p["text"] for p in payloads],
                         ["[fr] uno", "[fr] dos", "[fr] tres"])

    def test_translation_error_flag(self):
        self._install_translate(error=True)

        async def main():
            ts._start_language_workers()
            try:
                state = _register(mode="translate", target="it")
                await ts._dispatch_line("Hola")
                return await _get(state)
            finally:
                await ts._stop_language_workers()

        payload = asyncio.run(main())
        self.assertTrue(payload["error"])
        self.assertEqual(payload["target"], "it")

    def test_normalize_set(self):
        self.assertEqual(ts._normalize_set("translate", "de"), ("translate", "de"))
        self.assertEqual(ts._normalize_set("translate", "xx"), ("translate", "en"))
        self.assertEqual(ts._normalize_set("original", "de"), ("original", None))
        self.assertEqual(ts._normalize_set(None, None), ("original", None))

    def test_slow_client_dropped(self):
        async def main():
            state = _register(mode="original", maxsize=1)
            ts._enqueue(state, {"type": "line", "text": "1"})
            ts._enqueue(state, {"type": "line", "text": "2"})
            await asyncio.sleep(0)  # deja correr la tarea de cierre
            return state

        state = asyncio.run(main())
        self.assertNotIn(state["ws"], ts._ws_clients)
        self.assertTrue(state["ws"].closed)


if __name__ == "__main__":
    unittest.main(verbosity=1)
