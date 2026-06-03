# Runtime Validation Log

Last updated: 2026-06-03

## Environment

| Item | Value |
| --- | --- |
| Kubernetes type | Local kind cluster |
| Kubernetes node version | `v1.30.0` |
| Container runtime | Docker with kind node containers |
| Namespace | `llm-inference-poc` |
| Default model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Served model name | `qwen2.5-0.5b-instruct` |
| vLLM CPU image | `vllm/vllm-openai-cpu:latest-x86_64` |

## Validation Completed

| Check | Result |
| --- | --- |
| Python smoke tests | Passed |
| Kustomize render | Passed |
| Gateway image build | Passed |
| Gateway image loaded into kind nodes | Passed |
| `kubectl apply -k k8s/` | Passed |
| Gateway deployment readiness | Passed |
| Gateway `/healthz` through port-forward | Passed |
| vLLM CPU deployment readiness | Passed |
| vLLM `/v1/models` through port-forward | Passed |
| vLLM `/v1/chat/completions` through port-forward | Passed |
| Gateway `/v1/chat/completions` path | Passed |
| Small benchmark through gateway | Passed |

## Latest Result

The local kind CPU path succeeds with `Qwen/Qwen2.5-0.5B-Instruct` served as `qwen2.5-0.5b-instruct`.

Direct vLLM validation confirmed:

```text
GET /v1/models
model id: qwen2.5-0.5b-instruct
root model: Qwen/Qwen2.5-0.5B-Instruct
max_model_len: 1024
```

Chat completion validation confirmed a successful Korean greeting response:

```text
response: 안녕하세요! 어떻게 도와드릴까요?
```

Gateway benchmark evidence:

```text
requests: 2
success: 2
failure: 0
success_rate: 100.00%
avg_latency_ms: approximately 4495
```

## Resource Notes

The project originally explored Phi-4 mini, but the full BF16 checkpoint was too large for the local disk and memory budget. The default model was changed to `Qwen/Qwen2.5-0.5B-Instruct` because this PoC cares about proving the OpenAI-compatible serving path rather than model quality.

An optional Phi-4 mini manifest is included for larger-model experiments after the default Qwen path has been validated:

```powershell
kubectl apply -f k8s/vllm-deployment-phi4-mini.yaml
```

Observed rough checkpoint sizes:

```text
Phi-4 mini BF16 checkpoint: about 7.15 GiB
Qwen/Qwen2.5-0.5B-Instruct checkpoint: about 0.92 GiB
```

The CPU manifest uses:

```text
--max-model-len 1024
--enforce-eager
HF_HUB_DISABLE_XET=1
VLLM_CPU_KVCACHE_SPACE=1
VLLM_CPU_OMP_THREADS_BIND=0-1
```

These settings keep the local functional test smaller and make CPU startup more predictable.

## Commands Used

```powershell
python tests/smoke_test.py
python scripts/preflight.py --required-memory-gi 2 --check-docker --min-docker-memory-gi 4
kubectl kustomize k8s/
docker build -t registry.example.local/k8s-vllm-inference-poc-gateway:latest gateway
kind load docker-image registry.example.local/k8s-vllm-inference-poc-gateway:latest --name <kind-cluster-name>
kubectl apply -k k8s/
kubectl apply -f k8s/vllm-deployment-cpu.yaml
kubectl -n llm-inference-poc rollout status deployment/vllm --timeout=30m
kubectl -n llm-inference-poc rollout status deployment/gateway --timeout=5m
kubectl -n llm-inference-poc port-forward svc/vllm-service 8000:8000
kubectl -n llm-inference-poc port-forward svc/gateway-service 8080:8080
python benchmark/benchmark.py --url http://127.0.0.1:8080 --model qwen2.5-0.5b-instruct --requests 2 --concurrency 1 --max-tokens 16
```

## Revalidation Checklist

Use this quick checklist after changing manifests or model settings:

- `kubectl kustomize k8s/` renders successfully.
- `python tests/smoke_test.py` passes.
- vLLM reaches `1/1 Running`.
- Gateway reaches `1/1 Running`.
- `GET /v1/models` returns `qwen2.5-0.5b-instruct`.
- `POST /v1/chat/completions` works directly against vLLM.
- `POST /v1/chat/completions` works through the gateway.
- A small benchmark reports successful requests.
