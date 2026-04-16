#!/usr/bin/env python3
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

LOG_PATH = os.environ.get("MUTAGEN_K8S_SSH_LOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mutagen-k8s-ssh.log"))
KUBECTL = os.environ.get("MUTAGEN_K8S_KUBECTL", "kubectl")
VERBOSE = os.environ.get("MUTAGEN_K8S_VERBOSE", "").lower() in ("1", "true", "yes")


def log(msg: str, verbose: bool = False) -> None:
    if verbose and not VERBOSE:
        return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def parse_host(host: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parse pod[.namespace[.context]] from a host string with k8s--/ssh:// prefix
    already stripped and port already removed.
    Uses maxsplit=1 at each level so context may itself contain dots.
    Returns (pod, namespace, context).
    """
    parts = host.split(".", 1)
    pod = parts[0]
    if len(parts) == 1:
        return pod, None, None
    sub = parts[1].split(".", 1)
    namespace = sub[0]
    context = sub[1] if len(sub) == 2 else None
    return pod, namespace, context


def is_k8s_destination(dest: str) -> bool:
    host = dest.split("@", 1)[1] if "@" in dest else dest
    host = host.split(":")[0]
    return host.startswith("k8s--")


def strip_k8s_host(host: str) -> str:
    """Strip k8s-- or ssh:// prefix and :port suffix from a host string."""
    for prefix in ("ssh://", "k8s--"):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if ":" in host:
        host, _ = host.rsplit(":", 1)
    return host
