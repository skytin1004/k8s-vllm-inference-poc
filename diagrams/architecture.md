# Architecture

```mermaid
flowchart LR
    A["Benchmark Client<br/>or User API Request"] --> B["gateway-service<br/>Kubernetes Service"]
    B --> C["gateway Pod<br/>FastAPI"]
    C --> D["vllm-service<br/>Kubernetes Service"]
    D --> E["vLLM Pod<br/>OpenAI-Compatible Server"]
    E --> F["Qwen/Qwen2.5-0.5B-Instruct<br/>served as qwen2.5-0.5b-instruct"]
    F --> E
    E --> D
    D --> C
    C --> B
    B --> A
```

The gateway keeps the client-facing endpoint stable while Kubernetes Services route traffic to the current gateway and vLLM Pods. The default model is `Qwen/Qwen2.5-0.5B-Instruct`, served as `qwen2.5-0.5b-instruct`, so the PoC stays focused on request flow, benchmark behavior, and recovery after Pod replacement rather than large-model quality evaluation.
