import argparse
import asyncio
import importlib
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "gateway"))
sys.path.insert(0, str(PROJECT_ROOT / "benchmark"))


class MockOpenAIHandler(BaseHTTPRequestHandler):
    received_request_ids: list[str] = []

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        request_payload = json.loads(body.decode("utf-8"))
        self.received_request_ids.append(self.headers.get("x-request-id", ""))

        response_payload = {
            "id": "chatcmpl-smoke",
            "object": "chat.completion",
            "model": request_payload.get("model", "qwen2.5-0.5b-instruct"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Readiness probes keep traffic away until serving is ready.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 9,
                "total_tokens": 19,
            },
        }
        response_bytes = json.dumps(response_payload).encode("utf-8")

        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format: str, *args: object) -> None:
        return


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
        cls.server_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        os.environ["VLLM_BASE_URL"] = cls.server_url
        cls.gateway_main = importlib.import_module("main")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)

    def test_gateway_forwards_chat_completion(self) -> None:
        request_id = "smoke-request-1"
        response = asyncio.run(self._post_gateway(request_id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], request_id)
        self.assertIn(request_id, MockOpenAIHandler.received_request_ids)
        self.assertEqual(response.json()["model"], "qwen2.5-0.5b-instruct")

    async def _post_gateway(self, request_id: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.gateway_main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/v1/chat/completions",
                headers={"x-request-id": request_id},
                json={
                    "model": "qwen2.5-0.5b-instruct",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 16,
                },
            )

    def test_benchmark_records_successes_and_tokens(self) -> None:
        benchmark = importlib.import_module("benchmark")
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "smoke-results.csv"
            args = argparse.Namespace(
                url=self.server_url,
                model="qwen2.5-0.5b-instruct",
                requests=3,
                concurrency=2,
                max_tokens=16,
                prompt="hello",
                output=str(output_path),
            )

            results, elapsed = asyncio.run(benchmark.run_benchmark(args))
            benchmark.write_csv(results, args.output)

            self.assertGreater(elapsed, 0)
            self.assertEqual(len(results), 3)
            self.assertTrue(all(result.success for result in results))
            self.assertEqual(sum(result.output_tokens for result in results), 27)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
