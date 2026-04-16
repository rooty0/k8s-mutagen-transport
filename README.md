# k8s-mutagen-transport

A fake SSH/SCP transport layer that lets [Mutagen](https://mutagen.io/) sync files directly to Kubernetes pods via `kubectl exec` and `kubectl cp`, without needing an SSH server in the pod.

## How it works

Mutagen uses SSH under the hood for file sync. This project replaces the `ssh` and `scp` binaries with thin Python wrappers:

- **`ssh`** → delegates to `kubectl exec -i` for k8s destinations, passes through to real SSH for everything else
- **`scp`** → delegates to `kubectl cp` for k8s destinations, passes through to real SCP for everything else

Destinations are identified by the `k8s--` prefix (e.g. `k8s--pod-name` or `k8s--pod-name.namespace`). An optional Kubernetes context can be embedded as a third dot-separated segment.

## Requirements

- Python 3.12+
- `kubectl` configured and pointing at your cluster
- [Mutagen](https://mutagen.io/) installed
- [uv](https://github.com/astral-sh/uv) (for the `.venv`)

## Setup

```sh
# Create the virtualenv (no external deps needed, stdlib only)
uv sync

# Make the wrapper scripts executable (if not already)
chmod +x ssh scp
```

## Usage

### 1. Activate the transport

Tell Mutagen to use this directory's `ssh` and `scp` wrappers instead of the system ones:

```sh
mutagen daemon stop
export MUTAGEN_SSH_PATH=/path/to/k8s-mutagen-transport
mutagen daemon start
```

### 2. Create a sync session

Use the `k8s--` prefix to target a pod:

```sh
# Sync to a pod in the default namespace
mutagen sync create --name=myproject ./local-dir k8s--my-pod:/data-fast/myproject

# Sync to a pod in a specific namespace
mutagen sync create --name=myproject ./local-dir k8s--my-pod.my-namespace:/data-fast/myproject

# Sync to a specific container inside a pod
mutagen sync create --name=myproject ./local-dir container@k8s--my-pod:/data-fast/myproject

# Sync using a specific kubectl context
mutagen sync create --name=myproject ./local-dir k8s--my-pod.my-namespace.my-context:/data-fast/myproject
```

### 3. Manage sync sessions normally

```sh
mutagen sync list
mutagen sync pause myproject
mutagen sync terminate myproject
```

### Using a project file

For multiple sync sessions, use a `mutagen.yml` project file and `mutagen project start`:

```yaml
# mutagen.yml
beforeCreate:
  - kubectl exec my-pod -- sh -c "cd; mkdir -p projects"

afterTerminate:
  - kubectl exec my-pod -- sh -c "cd; rm -rf projects"

sync:
  defaults:
    flushOnCreate: true
    ignore:
      vcs: true
    permissions:
      defaultFileMode: 0644
      defaultDirectoryMode: 0755

  projectA:
    alpha: /local/path/projectA
    beta: k8s--my-pod:/root/projects/projectA

  projectB:
    alpha: /local/path/projectB
    beta: k8s--my-pod.my-namespace:/root/projects/projectB
    ignore:
      paths:
        - /build
        - /dist
```

```sh
mutagen project start   # start all sessions
mutagen project flush   # force sync
mutagen project terminate
```

## Destination format

```
[container@]k8s--<pod>[.<namespace>[.<context>]]:<remote-path>
```

| Part | Description |
|---|---|
| `container@` | Optional container name within the pod |
| `k8s--` | Required prefix identifying a Kubernetes destination |
| `<pod>` | Pod name |
| `.<namespace>` | Optional Kubernetes namespace |
| `.<context>` | Optional kubectl context (uses current context if omitted); may contain dots |
| `:<remote-path>` | Remote path (supports `~`, `~/...`, and relative paths) |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MUTAGEN_K8S_KUBECTL` | `kubectl` | Path to the kubectl binary |
| `MUTAGEN_K8S_REAL_SSH` | `/usr/bin/ssh` | Real SSH binary for non-k8s destinations |
| `MUTAGEN_K8S_REAL_SCP` | `/usr/bin/scp` | Real SCP binary for non-k8s destinations |
| `MUTAGEN_K8S_SSH_LOG` | `<project-dir>/mutagen-k8s-ssh.log` | Log file path |
| `MUTAGEN_K8S_HOME_CACHE` | `<project-dir>/mutagen-k8s-home-cache.json` | Home directory cache file |
| `MUTAGEN_K8S_VERBOSE` | `""` | Set to `1`, `true`, or `yes` for verbose logging |

## Logging

All k8s-bound connections are logged to `mutagen-k8s-ssh.log` in the project directory (or the path set by `MUTAGEN_K8S_SSH_LOG`). Enable verbose mode to also log passthrough (non-k8s) connections and cache hits.

## Notes

- The transport emulates real SSH/SSHD behavior: remote commands run via `sh -c 'cd "$HOME" && <cmd>'`, so relative paths work as expected.
- `$HOME` inside the pod is resolved once and cached for 5 minutes per pod/namespace/container/context combination to avoid extra `kubectl exec` calls on every SCP operation.
- Non-k8s SSH/SCP calls are transparently forwarded to the real binaries, so regular SSH still works normally.
