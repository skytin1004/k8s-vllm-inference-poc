# Engineering Handoff Template

## Issue Summary

Briefly describe the issue, impact, and when it was observed.

## Environment

| Item | Value |
| --- | --- |
| Namespace | `llm-inference-poc` |
| Component | TBD |
| Image | TBD |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Served model name | `qwen2.5-0.5b-instruct` |
| Kubernetes context | TBD |

## Reproduction Steps

1. Apply the manifests.
2. Wait for the gateway and vLLM deployments to become ready.
3. Port-forward the gateway service.
4. Run the benchmark command.
5. Capture logs and pod status.

```powershell
kubectl apply -k k8s/
```

## Observed Behavior

Describe what actually happened. Include status codes, latency changes, pod events, and benchmark errors.

## Expected Behavior

Describe the expected serving or recovery behavior.

## Logs and Metrics

Include relevant output:

```text
kubectl -n llm-inference-poc get pods
kubectl -n llm-inference-poc describe pod <pod-name>
kubectl -n llm-inference-poc logs deployment/gateway
kubectl -n llm-inference-poc logs deployment/vllm
```

## Hypothesis

State the most likely cause based on current evidence.

## Suggested Next Steps

- Confirm resource availability and scheduling events.
- Compare gateway errors with vLLM logs.
- Re-run a smaller benchmark to isolate capacity from correctness.
- Adjust model length, concurrency, or resources and retest.
