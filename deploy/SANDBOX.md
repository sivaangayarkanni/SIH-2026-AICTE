# Analysis sandbox

`SANDBOX_BACKEND=auto|namespace|docker|process` (default `auto` = namespace if bubblewrap works, else process).

| Backend | Isolation | Tested here |
|---|---|---|
| namespace | bubblewrap: all namespaces unshared (no network interfaces), cap-drop ALL, read-only root, tmpfs over /tmp,/workspace,/home,DATA_DIR; only input + trust roots bound ro, scratch dir rw; seccomp BPF (non-AF_UNIX socket(), ptrace, mount, bpf, unshare, keyctl… → EPERM); rlimits CPU/AS/NOFILE/FSIZE/CORE | Yes, tests/test_sandbox.py escape probes |
| docker | `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, optional `SANDBOX_DOCKER_RUNTIME=runsc` (gVisor) | argv construction only. Docker is not on the build box |
| process | rlimits + Python-level socket guard only. **Weak**: raw `_socket` bypasses it. Dev only | Yes |

The sanitized output is written to the job's scratch dir and copied out by the service after the worker exits. A bind-mounted single file breaks atomic rename (EBUSY).

gVisor in compose: install runsc on the host, register it in `/etc/docker/daemon.json` (`"runtimes": {"runsc": {"path": "/usr/local/bin/runsc"}}`), then set `SANDBOX_BACKEND=docker SANDBOX_DOCKER_RUNTIME=runsc` on the api service. The api container needs access to the Docker socket, which is a significant privilege. Prefer the namespace backend inside a pod with a seccomp/AppArmor profile that allows user namespaces. Neither of these was tested here.
