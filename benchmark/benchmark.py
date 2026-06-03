import argparse
import asyncio
import csv
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_PROMPT = "Briefly explain why readiness probes matter for inference services."


@dataclass
class RequestResult:
    request_id: int
    success: bool
    status_code: int | None
    latency_ms: float
    output_tokens: int
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark a vLLM-compatible chat completions endpoint."
    )
    parser.add_argument("--url", default="http://localhost:8080", help="Gateway base URL.")
    parser.add_argument(
        "--model",
        default="qwen2.5-0.5b-instruct",
        help="Model name sent in the chat completions request.",
    )
    parser.add_argument("--requests", type=int, default=20, help="Total requests to send.")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent requests.")
    parser.add_argument("--max-tokens", type=int, default=128, help="Maximum output tokens.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to send.")
    parser.add_argument(
        "--output",
        default="benchmark/results.csv",
        help="CSV path for per-request results.",
    )
    args = parser.parse_args()

    if args.requests < 1:
        parser.error("--requests must be at least 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.max_tokens < 1:
        parser.error("--max-tokens must be at least 1")

    return args


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * (percentile_value / 100)
    lower = math.floor(index)
    upper = math.ceil(index)

    if lower == upper:
        return sorted_values[int(index)]

    lower_value = sorted_values[lower] * (upper - index)
    upper_value = sorted_values[upper] * (index - lower)
    return lower_value + upper_value


def estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text.split()) * 1.3))


def extract_output_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if isinstance(completion_tokens, int):
        return completion_tokens

    choices = payload.get("choices") or []
    if not choices:
        return 0

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return estimate_tokens_from_text(content)

    return 0


async def send_request(
    client: httpx.AsyncClient,
    url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    request_id: int,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    headers = {"x-request-id": f"benchmark-{request_id}"}

    async with semaphore:
        started = time.perf_counter()
        try:
            response = await client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            latency_ms = (time.perf_counter() - started) * 1000

            if response.status_code >= 400:
                return RequestResult(
                    request_id=request_id,
                    success=False,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    output_tokens=0,
                    error=response.text[:300],
                )

            data = response.json()
            return RequestResult(
                request_id=request_id,
                success=True,
                status_code=response.status_code,
                latency_ms=latency_ms,
                output_tokens=extract_output_tokens(data),
                error="",
            )

        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            return RequestResult(
                request_id=request_id,
                success=False,
                status_code=None,
                latency_ms=latency_ms,
                output_tokens=0,
                error=str(exc),
            )
        except ValueError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            return RequestResult(
                request_id=request_id,
                success=False,
                status_code=None,
                latency_ms=latency_ms,
                output_tokens=0,
                error=f"Invalid JSON response: {exc}",
            )


async def run_benchmark(args: argparse.Namespace) -> tuple[list[RequestResult], float]:
    timeout = httpx.Timeout(120.0)
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    semaphore = asyncio.Semaphore(args.concurrency)

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        tasks = [
            send_request(
                client=client,
                url=args.url,
                model=args.model,
                prompt=args.prompt,
                max_tokens=args.max_tokens,
                request_id=request_id,
                semaphore=semaphore,
            )
            for request_id in range(1, args.requests + 1)
        ]
        results = await asyncio.gather(*tasks)

    total_elapsed_s = time.perf_counter() - started
    return results, total_elapsed_s


def write_csv(results: list[RequestResult], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def print_summary(results: list[RequestResult], total_elapsed_s: float) -> None:
    total = len(results)
    successes = [result for result in results if result.success]
    failures = total - len(successes)
    latencies = [result.latency_ms for result in results]
    output_tokens = sum(result.output_tokens for result in successes)
    tokens_per_second = output_tokens / total_elapsed_s if total_elapsed_s > 0 else 0.0

    rows = [
        ("requests", f"{total}"),
        ("success", f"{len(successes)}"),
        ("failure", f"{failures}"),
        ("success_rate", f"{(len(successes) / total) * 100:.2f}%"),
        ("error_rate", f"{(failures / total) * 100:.2f}%"),
        ("avg_latency_ms", f"{(sum(latencies) / len(latencies)) if latencies else 0:.2f}"),
        ("p50_latency_ms", f"{percentile(latencies, 50):.2f}"),
        ("p95_latency_ms", f"{percentile(latencies, 95):.2f}"),
        ("p99_latency_ms", f"{percentile(latencies, 99):.2f}"),
        ("output_tokens", f"{output_tokens}"),
        ("approx_output_tokens_sec", f"{tokens_per_second:.2f}"),
        ("elapsed_sec", f"{total_elapsed_s:.2f}"),
    ]

    label_width = max(len(label) for label, _ in rows)
    value_width = max(len(value) for _, value in rows)
    border = f"+-{'-' * label_width}-+-{'-' * value_width}-+"

    print(border)
    print(f"| {'metric'.ljust(label_width)} | {'value'.ljust(value_width)} |")
    print(border)
    for label, value in rows:
        print(f"| {label.ljust(label_width)} | {value.rjust(value_width)} |")
    print(border)


def main() -> None:
    args = parse_args()
    results, total_elapsed_s = asyncio.run(run_benchmark(args))
    write_csv(results, args.output)
    print_summary(results, total_elapsed_s)
    print(f"\nWrote per-request results to {args.output}")


if __name__ == "__main__":
    main()
