#!/usr/bin/env python3
"""
Fake scp -> kubectl cp transport for Mutagen.

Handles: scp [flags] local_file [container@]k8s--pod[.namespace[.context]]:remote_path
Delegates non-k8s destinations to the real scp.
"""

import json
import os
import shlex
import subprocess
import sys
import time
from typing import Optional, Tuple

from common import KUBECTL, is_k8s_destination, log as _log, parse_host, strip_k8s_host

HOME_CACHE_PATH = os.environ.get("MUTAGEN_K8S_HOME_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mutagen-k8s-home-cache.json"))
HOME_CACHE_TTL = 300  # seconds
SCP = os.environ.get("MUTAGEN_K8S_REAL_SCP", "/usr/bin/scp")


def log(msg: str, verbose: bool = False) -> None:
    _log(f"[scp] {msg}", verbose)

def parse_k8s_destination(dest: str) -> Tuple[Optional[str], str, Optional[str], str, Optional[str]]:
    """
    Parse [container@]k8s--pod[.namespace[.context]]:remote_path.
    Returns (container, pod, namespace, remote_path, context).
    """
    if "@" in dest:
        container, rest = dest.split("@", 1)
    else:
        container, rest = None, dest
    host, remote_path = rest.split(":", 1)
    pod, namespace, context = parse_host(strip_k8s_host(host))
    return container, pod, namespace, remote_path, context

def parse_scp_argv(argv: list) -> Tuple[list, str, str]:
    """
    Parse scp argv, returning (flags, source, destination).
    Handles scp [flags] source dest.
    """
    flags = []
    i = 0
    flag_arg_opts = {"-P", "-i", "-F", "-o", "-l", "-S", "-c"}

    while i < len(argv):
        a = argv[i]
        if not a.startswith("-"):
            break
        if a in flag_arg_opts:
            flags += [a, argv[i + 1]]
            i += 2
        else:
            flags.append(a)
            i += 1

    positional = argv[i:]
    if len(positional) < 2:
        raise ValueError(f"Expected source and destination, got: {positional}")

    return flags, positional[-2], positional[-1]

def _cache_key(pod: str, namespace: Optional[str], container: Optional[str], context: Optional[str]) -> str:
    return f"{context or '_'}/{namespace or '_'}/{pod}/{container or '_'}"


def get_remote_home(pod: str, namespace: Optional[str], container: Optional[str], context: Optional[str]) -> str:
    """Return $HOME inside the pod, using a file-backed cache with TTL."""
    key = _cache_key(pod, namespace, container, context)
    now = time.time()

    cache: dict = {}
    try:
        with open(HOME_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    entry = cache.get(key)
    if entry and now - entry["ts"] < HOME_CACHE_TTL:
        log(f"home_cache_hit key={key!r} home={entry['home']!r}", verbose=True)
        return entry["home"]

    cmd = [KUBECTL]
    if context:
        cmd += ["--context", context]
    cmd += ["exec"]
    if namespace:
        cmd += ["-n", namespace]
    if container:
        cmd += ["-c", container]
    cmd += [pod, "--", "/bin/sh", "-c", "echo $HOME"]

    log(f"resolving home: kubectl={shlex.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    home = result.stdout.strip()
    if not home:
        home = "/root"
        log(f"home resolution failed (exit={result.returncode}), falling back to {home!r}")
    else:
        log(f"resolved home={home!r} for key={key!r}")

    cache[key] = {"home": home, "ts": now}
    try:
        os.makedirs(os.path.dirname(HOME_CACHE_PATH), exist_ok=True)
        with open(HOME_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        log(f"home_cache_write_error={e}")

    return home


def resolve_remote_path(remote_path: str, pod: str, namespace: Optional[str], container: Optional[str], context: Optional[str]) -> str:
    """
    Expand relative paths and ~/... to an absolute path, matching real scp/sshd
    behavior where the remote shell starts in $HOME.
    """
    if remote_path.startswith("/"):
        return remote_path
    home = get_remote_home(pod, namespace, container, context)
    if remote_path.startswith("~/"):
        return home + "/" + remote_path[2:]
    if remote_path == "~":
        return home
    return home + "/" + remote_path


def main() -> int:
    log(f"argv0={sys.argv[0]} argv={shlex.join(sys.argv[1:])}", verbose=True)

    try:
        flags, source, dest = parse_scp_argv(sys.argv[1:])
    except Exception as e:
        log(f"parse_error={e}")
        print(f"fake-scp error: {e}", file=sys.stderr)
        return 255

    # Determine which side is k8s (scp can go either direction, but Mutagen
    # always copies local -> remote for agent installation).
    if is_k8s_destination(dest):
        k8s_end, other_end, direction = dest, source, "local->k8s"
    elif is_k8s_destination(source):
        k8s_end, other_end, direction = source, dest, "k8s->local"
    else:
        log(f"non-k8s, delegating to real scp", verbose=True)
        os.execv(SCP, [SCP] + sys.argv[1:])

    log(f"argv0={sys.argv[0]} argv={shlex.join(sys.argv[1:])}")
    log(f"scp {direction} {other_end!r} <-> {k8s_end!r}")

    try:
        container, pod, namespace, remote_path, context = parse_k8s_destination(k8s_end)
    except Exception as e:
        log(f"parse_error={e}")
        print(f"fake-scp error: {e}", file=sys.stderr)
        return 255

    remote_path = resolve_remote_path(remote_path, pod, namespace, container, context)

    cmd = [KUBECTL]
    if context:
        cmd += ["--context", context]
    cmd += ["cp"]
    if namespace:
        cmd += ["-n", namespace]
    if container:
        cmd += ["-c", container]
    if direction == "local->k8s":
        cmd += [other_end, f"{pod}:{remote_path}"]
    else:
        cmd += [f"{pod}:{remote_path}", other_end]

    log(f"kubectl={shlex.join(cmd)}")
    return subprocess.call(cmd)

if __name__ == "__main__":
    sys.exit(main())
