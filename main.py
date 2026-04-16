#!/usr/bin/env python3
"""
Fake ssh -> kubectl exec transport for Mutagen.

Design goals:
- Accept and ignore OpenSSH flags commonly passed by Mutagen (notably -o...).
- Preserve stdio as a raw byte stream (no TTY allocation).
- Emulate SSH server behavior of starting commands in $HOME (workdir problem).
- Log argv so you can see exactly what Mutagen is doing.
"""

import os
import shlex
import signal
import subprocess
import sys
from typing import List, Optional, Tuple

from common import KUBECTL, LOG_PATH, is_k8s_destination, log, parse_host, strip_k8s_host

SSH = os.environ.get("MUTAGEN_K8S_REAL_SSH", "/usr/bin/ssh")

def parse_ssh_argv(argv: List[str]) -> Tuple[str, str]:
    """
    Return (destination, remote_cmd).

    Best-effort parse of OpenSSH client argv. Skips options including those
    that take a separate argument: -p, -F, -i, -J, -l, -o, -S.
    Also handles -oOption=Value (single token).

    SSH allows flags before or after the destination; -- terminates option
    scanning and everything after it is the remote command.

    The remote command is returned as a single space-joined string — exactly
    as the SSH client sends it on the wire. The remote shell re-parses it,
    which is what makes word-splitting of tokens like 'uname -s -m' work.
    """
    option_arg_flags = {"-p", "-F", "-i", "-J", "-l", "-o", "-S"}
    dest: Optional[str] = None
    i = 0

    while i < len(argv):
        a = argv[i]
        if a == "--":
            i += 1
            break
        if a.startswith("-"):
            # -oSomething=Value is a single token.
            if a.startswith("-o") and a != "-o":
                i += 1
                continue
            # Flags with a separate argument value.
            if a in option_arg_flags:
                i += 2
                continue
            # Other boolean flags (e.g. -T, -t, -v).
            i += 1
            continue
        if dest is None:
            dest = a
            i += 1
            continue
        # First non-flag token after destination: start of remote command.
        break

    if dest is None:
        raise ValueError("No destination found in ssh argv")

    remote_tokens = argv[i:]
    # If there's a single token, it's already a shell command string (e.g. what
    # Mutagen sends). Pass it through as-is so the remote shell word-splits it.
    # If there are multiple tokens, re-quote each one so the remote shell sees
    # the same word boundaries we received.
    if len(remote_tokens) == 1:
        remote_cmd = remote_tokens[0]
    else:
        remote_cmd = shlex.join(remote_tokens)
    return dest, remote_cmd

def parse_destination(dest: str) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    Parse [container@]k8s--pod[.namespace[.context]].
    Returns (container, pod, namespace, context).
    """
    if "@" in dest:
        container, host = dest.split("@", 1)
    else:
        container, host = None, dest
    pod, namespace, context = parse_host(strip_k8s_host(host))
    if not pod:
        raise ValueError("Empty pod name in destination")
    return container, pod, namespace, context

def build_kubectl_exec(container: Optional[str], pod: str, namespace: Optional[str], context: Optional[str], remote_cmd: str) -> List[str]:
    cmd = [KUBECTL]
    if context:
        cmd += ["--context", context]

    cmd += ["exec", "-i"]  # -i is required for Mutagen agent stdio

    if namespace:
        cmd += ["-n", namespace]
    if container:
        cmd += ["-c", container]

    if not remote_cmd:
        cmd += [pod, "--", "/bin/sh"]
        return cmd

    # Emulate real SSH server behavior: pass the command as a single string to
    # sh -c, prepending cd "$HOME". sshd does exactly this — it sends the raw
    # command string and the remote shell re-parses it naturally.
    cmd += [pod, "--", "/bin/sh", "-c", f'cd "$HOME" && {remote_cmd}']
    return cmd

def main() -> int:
    log(f"argv0={sys.argv[0]} argv={shlex.join(sys.argv[1:])}", verbose=True)
    try:
        dest, remote_cmd = parse_ssh_argv(sys.argv[1:])
    except Exception as e:
        log(f"parse_error={e}")
        print(f"fake-ssh error: {e}", file=sys.stderr)
        return 255

    if not is_k8s_destination(dest):
        log(f"non-k8s destination, delegating to real ssh: {dest}", verbose=True)
        os.execv(SSH, [SSH] + sys.argv[1:])

    log(f"argv0={sys.argv[0]} argv={shlex.join(sys.argv[1:])}")

    try:
        container, pod, namespace, context = parse_destination(dest)
        kubectl_cmd = build_kubectl_exec(container, pod, namespace, context, remote_cmd)
    except Exception as e:
        log(f"parse_error={e}")
        print(f"fake-ssh error: {e}", file=sys.stderr)
        return 255

    log(f"kubectl={shlex.join(kubectl_cmd)}")

    proc = subprocess.Popen(kubectl_cmd)

    def forward(sig, _frame):
        if proc.poll() is None:
            try:
                proc.send_signal(sig)
            except Exception:
                pass

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)

    return proc.wait()

if __name__ == "__main__":
    sys.exit(main())
