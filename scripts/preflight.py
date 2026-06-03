import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


MEMORY_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
}


@dataclass
class NodeSummary:
    name: str
    schedulable: bool
    allocatable_memory_gi: float
    gpu_resource_keys: list[str]
    taints: list[str]


def run_kubectl(args: list[str]) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def run_docker_info() -> dict[str, Any]:
    if not shutil.which("docker"):
        raise RuntimeError("docker was not found on PATH")

    result = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    payload = json.loads(result.stdout)
    server_errors = payload.get("ServerErrors") or []
    if server_errors:
        raise RuntimeError("; ".join(server_errors))
    if not payload.get("ServerVersion") or int(payload.get("MemTotal", 0)) <= 0:
        raise RuntimeError("Docker engine returned an empty or incomplete server status")
    return payload


def parse_memory_quantity(value: str) -> int:
    for suffix, multiplier in MEMORY_UNITS.items():
        if value.endswith(suffix):
            return int(value[: -len(suffix)]) * multiplier
    return int(value)


def summarize_node(node: dict[str, Any]) -> NodeSummary:
    metadata = node.get("metadata", {})
    spec = node.get("spec", {})
    status = node.get("status", {})
    allocatable = status.get("allocatable", {})
    taints = [
        f"{taint.get('key')}={taint.get('effect')}"
        for taint in spec.get("taints", [])
    ]
    blocking_taint = any(
        taint.get("effect") in {"NoSchedule", "NoExecute"}
        for taint in spec.get("taints", [])
    )
    schedulable = not spec.get("unschedulable", False) and not blocking_taint
    memory_gi = parse_memory_quantity(allocatable.get("memory", "0")) / (1024**3)
    gpu_keys = [key for key in allocatable if "gpu" in key.lower()]

    return NodeSummary(
        name=metadata.get("name", "<unknown>"),
        schedulable=schedulable,
        allocatable_memory_gi=memory_gi,
        gpu_resource_keys=sorted(gpu_keys),
        taints=taints,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether the current Kubernetes context can schedule the vLLM PoC pod."
    )
    parser.add_argument(
        "--required-memory-gi",
        type=float,
        default=8.0,
        help="Minimum allocatable memory required on one schedulable node.",
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="Fail if no schedulable node advertises a GPU-style allocatable resource.",
    )
    parser.add_argument(
        "--check-docker",
        action="store_true",
        help="Also check local Docker engine health and memory. Useful for kind clusters.",
    )
    parser.add_argument(
        "--min-docker-memory-gi",
        type=float,
        default=8.0,
        help="Minimum Docker engine memory when --check-docker is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        context = run_kubectl(["config", "current-context"]).strip()
        nodes_payload = json.loads(run_kubectl(["get", "nodes", "-o", "json"]))
    except Exception as exc:
        print(f"FAIL: could not inspect Kubernetes context: {exc}", file=sys.stderr)
        return 1

    summaries = [summarize_node(node) for node in nodes_payload.get("items", [])]
    if not summaries:
        print(f"FAIL: context {context!r} has no nodes", file=sys.stderr)
        return 1

    print(f"context: {context}")
    print("nodes:")
    for node in summaries:
        gpu_keys = ", ".join(node.gpu_resource_keys) or "-"
        taints = ", ".join(node.taints) or "-"
        print(
            f"  - {node.name}: schedulable={node.schedulable} "
            f"memory={node.allocatable_memory_gi:.2f}Gi gpu_keys={gpu_keys} taints={taints}"
        )

    memory_ready = any(
        node.schedulable and node.allocatable_memory_gi >= args.required_memory_gi
        for node in summaries
    )
    gpu_ready = any(node.schedulable and node.gpu_resource_keys for node in summaries)

    if not memory_ready:
        print(
            f"FAIL: no schedulable node has >= {args.required_memory_gi:.2f}Gi "
            "allocatable memory for the vLLM pod request",
            file=sys.stderr,
        )
        return 1

    if args.require_gpu and not gpu_ready:
        print("FAIL: no schedulable node advertises a GPU-style resource", file=sys.stderr)
        return 1

    if not gpu_ready:
        print("WARN: no schedulable node advertises a GPU-style resource")

    if args.check_docker:
        try:
            docker_info = run_docker_info()
        except Exception as exc:
            print(f"FAIL: could not inspect Docker engine: {exc}", file=sys.stderr)
            return 1

        docker_memory_gi = int(docker_info.get("MemTotal", 0)) / (1024**3)
        server_version = docker_info.get("ServerVersion") or "<unknown>"
        print(f"docker: version={server_version} memory={docker_memory_gi:.2f}Gi")
        if docker_memory_gi < args.min_docker_memory_gi:
            print(
                f"FAIL: Docker engine memory is below {args.min_docker_memory_gi:.2f}Gi",
                file=sys.stderr,
            )
            return 1

    print("PASS: scheduling preflight checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
