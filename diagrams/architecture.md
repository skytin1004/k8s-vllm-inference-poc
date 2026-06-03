# Architecture

```mermaid
flowchart LR
    A["Benchmark Client"] --> B["FastAPI Gateway"]
    B --> C["Kubernetes Service"]
    C --> D["vLLM OpenAI-Compatible Server"]
    D --> E["Model: microsoft/Phi-4-mini-instruct"]
```

The gateway keeps the client-facing endpoint stable while the Kubernetes service routes traffic to the current vLLM pod. This keeps the PoC focused on request flow, benchmark behavior, and recovery after pod replacement.
