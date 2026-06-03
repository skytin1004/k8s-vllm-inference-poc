import json
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://vllm-service:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=LOG_LEVEL, format="%(message)s")
logger = logging.getLogger("gateway")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="vLLM Inference Gateway", version="0.1.0")


def log_event(level: int, event: str, **fields: object) -> None:
    payload = {"event": event, **fields}
    logger.log(level, json.dumps(payload, separators=(",", ":")))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "upstream": VLLM_BASE_URL}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = time.perf_counter()
    upstream_url = f"{VLLM_BASE_URL}/v1/chat/completions"

    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
        "x-request-id": request_id,
    }
    authorization = request.headers.get("authorization")
    if authorization:
        headers["authorization"] = authorization

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            upstream_response = await client.post(
                upstream_url,
                content=body,
                headers=headers,
            )

        latency_ms = (time.perf_counter() - started) * 1000
        log_event(
            logging.INFO,
            "chat_completion_forwarded",
            request_id=request_id,
            upstream_status=upstream_response.status_code,
            latency_ms=round(latency_ms, 2),
        )

        response_headers = {
            "x-request-id": request_id,
            "x-gateway-latency-ms": f"{latency_ms:.2f}",
        }
        content_type = upstream_response.headers.get("content-type")
        if content_type:
            response_headers["content-type"] = content_type

        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=response_headers,
        )

    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - started) * 1000
        log_event(
            logging.WARNING,
            "chat_completion_timeout",
            request_id=request_id,
            latency_ms=round(latency_ms, 2),
        )
        return JSONResponse(
            status_code=504,
            content={
                "error": "upstream_timeout",
                "message": "Timed out waiting for the vLLM server.",
                "request_id": request_id,
            },
            headers={"x-request-id": request_id},
        )

    except httpx.ConnectError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        log_event(
            logging.WARNING,
            "chat_completion_connection_error",
            request_id=request_id,
            latency_ms=round(latency_ms, 2),
            error=str(exc),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_connection_error",
                "message": "Could not connect to the vLLM server.",
                "request_id": request_id,
            },
            headers={"x-request-id": request_id},
        )

    except httpx.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        log_event(
            logging.WARNING,
            "chat_completion_http_error",
            request_id=request_id,
            latency_ms=round(latency_ms, 2),
            error=str(exc),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "upstream_http_error",
                "message": "Unexpected HTTP error while calling the vLLM server.",
                "request_id": request_id,
            },
            headers={"x-request-id": request_id},
        )
