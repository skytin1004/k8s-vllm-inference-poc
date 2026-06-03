# Demo Script

## 5-Minute Demo Flow

### 0:00-0:45 - Objective

Explain that this PoC demonstrates Kubernetes-based LLM inference serving with vLLM, a FastAPI gateway, basic benchmarking, and failure recovery observation.

### 0:45-1:30 - Architecture

Walk through the request path:

```text
Benchmark Client -> FastAPI Gateway -> Kubernetes Service -> vLLM Server -> Model
```

Emphasize that the PoC measures serving workflow and operational behavior, not model quality.

### 1:30-2:20 - Deployment Walkthrough

Show the namespace and deployments:

```powershell
kubectl apply -k k8s/
kubectl -n llm-inference-poc get pods
kubectl -n llm-inference-poc get services
```

Point out:

- vLLM serves `Qwen/Qwen2.5-0.5B-Instruct` as `qwen2.5-0.5b-instruct`.
- The gateway forwards `/v1/chat/completions` to the vLLM service.
- Resource values are placeholders and should be tuned per environment.

### 2:20-3:15 - Benchmark Walkthrough

Port-forward the gateway:

```powershell
kubectl -n llm-inference-poc port-forward svc/gateway-service 8080:8080
```

Run the benchmark:

```powershell
python benchmark/benchmark.py --url http://localhost:8080 --model qwen2.5-0.5b-instruct --requests 20 --concurrency 4 --max-tokens 128 --output benchmark/results.csv
```

Review latency percentiles, success rate, error rate, and approximate output tokens/sec.

### 3:15-4:20 - Failure Recovery Walkthrough

Delete the vLLM pod:

```powershell
kubectl -n llm-inference-poc delete pod -l app=vllm
kubectl -n llm-inference-poc get pods -w
```

Explain that transient request failures can occur while the replacement pod starts and readiness checks pass.

### 4:20-5:00 - Lessons Learned

Summarize:

- Whether the model fit the available resources.
- How latency changed under concurrency.
- How long recovery took after pod deletion.
- Which configuration changes should be tested next.
