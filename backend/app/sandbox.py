"""Analysis-worker sandbox launcher. SANDBOX_BACKEND selects the isolation layer:

* namespace (default when bubblewrap works): bwrap with ALL namespaces unshared (net/pid/ipc/uts/user/cgroup),
  read-only root, the data directory, /home, /workspace, /run and /tmp hidden (tmpfs), only the job's input
  file + trust roots bound read-only, only the job's scratch dir + one output file writable, no capabilities,
  --die-with-parent, new session, and a seccomp-BPF filter (x86_64) that denies socket() for every family except AF_UNIX (no netns interfaces exist anyway), ptrace()/
  mount/keyctl/bpf/unshare/setns/... with EPERM. rlimits (CPU, address space, nofile, nproc, fsize) also apply.
* docker: `docker run --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit`
  (+ `--runtime runsc` when SANDBOX_DOCKER_RUNTIME=runsc for gVisor). Command construction is unit-tested;
  NOT executed here (no Docker on the build box).
* process (dev fallback): plain subprocess + rlimits + the worker's Python-level egress guard. Weakest.
"""
import os, platform, shutil, struct, subprocess, sys
from pathlib import Path
from .config import WORKER_CPU_SECONDS, WORKER_MEMORY_MB, DATA_DIR, BACKEND_DIR

BACKEND = os.getenv("SANDBOX_BACKEND", "auto").lower()
DOCKER_IMAGE = os.getenv("SANDBOX_DOCKER_IMAGE", "sealcheck-worker:latest")
DOCKER_RUNTIME = os.getenv("SANDBOX_DOCKER_RUNTIME", "")  # e.g. runsc (gVisor)
VENV = Path(sys.prefix)

# ---- seccomp-BPF (x86_64) -------------------------------------------------------------------------------------------
AUDIT_ARCH_X86_64 = 0xC000003E
DENY = {"ptrace": 101, "mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161,
        "kexec_load": 246, "init_module": 175, "finit_module": 313, "delete_module": 176, "keyctl": 250,
        "add_key": 248, "request_key": 249, "bpf": 321, "unshare": 272, "setns": 308, "perf_event_open": 298,
        "process_vm_readv": 310, "process_vm_writev": 311, "userfaultfd": 323, "open_by_handle_at": 304,
        "io_uring_setup": 425, "personality": 135}
SYS_SOCKET, AF_UNIX = 41, 1  # socket(): only AF_UNIX allowed (asyncio self-pipe used by pyHanko needs socketpair)
EPERM = 1


def seccomp_bpf() -> bytes:
    """Hand-assembled classic BPF: kill on foreign arch; socket(domain != AF_UNIX) -> EPERM; DENY list -> EPERM."""
    def ins(code, jt, jf, k):
        return struct.pack("HBBI", code, jt, jf, k)
    LD_W_ABS, JEQ, RET = 0x20, 0x15, 0x06
    nrs = sorted(set(DENY.values()))
    n = len(nrs)
    # layout: 0 ld arch | 1 jeq | 2 kill | 3 ld nr | 4 jeq socket | 5..5+n-1 deny jeqs | A=5+n allow | E=6+n errno
    #         S=7+n ld arg0 | 8+n jeq AF_UNIX -> A else E
    A, E, S = 5 + n, 6 + n, 7 + n
    prog = [ins(LD_W_ABS, 0, 0, 4), ins(JEQ, 1, 0, AUDIT_ARCH_X86_64), ins(RET, 0, 0, 0x00000000),
            ins(LD_W_ABS, 0, 0, 0), ins(JEQ, S - 5, 0, SYS_SOCKET)]
    for i, nr in enumerate(nrs):
        pc = 5 + i
        prog.append(ins(JEQ, E - pc - 1, 0, nr))
    prog += [ins(RET, 0, 0, 0x7FFF0000), ins(RET, 0, 0, 0x00050000 | EPERM),
             ins(LD_W_ABS, 0, 0, 16), ins(JEQ, A - (8 + n) - 1 + 256, 0, AF_UNIX)]
    # backward jumps are impossible in cBPF: re-emit ALLOW/ERRNO after the arg check instead
    prog[-1] = ins(JEQ, 0, 1, AF_UNIX)
    prog += [ins(RET, 0, 0, 0x7FFF0000), ins(RET, 0, 0, 0x00050000 | EPERM)]
    return b"".join(prog)


def bwrap_ok() -> bool:
    if not shutil.which("bwrap") or platform.machine() != "x86_64":
        return False
    try:
        return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


_resolved = None


def active_backend() -> str:
    global _resolved
    if _resolved is None:
        if BACKEND == "auto":
            _resolved = "namespace" if bwrap_ok() else "process"
        else:
            _resolved = BACKEND
        if _resolved == "namespace" and not bwrap_ok():
            raise RuntimeError("SANDBOX_BACKEND=namespace but bubblewrap/user namespaces are unavailable")
    return _resolved


def rlimits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (WORKER_CPU_SECONDS, WORKER_CPU_SECONDS + 5))
    mem = WORKER_MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def _worker_argv(python="python3"):
    return [python, "-I", "-B", str(BACKEND_DIR / "app" / "worker.py")]


def namespace_argv(scratch: str, ro: list[str], rw_files: list[str]) -> tuple[list[str], int]:
    r, w = os.pipe()
    os.write(w, seccomp_bpf()); os.close(w)
    a = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
         "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
         "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/var/tmp"]
    for hide in ("/workspace", "/srv", "/mnt", "/media", "/opt"):
        if os.path.isdir(hide):
            a += ["--tmpfs", hide]
    a += ["--ro-bind", str(VENV), str(VENV), "--ro-bind", str(BACKEND_DIR / "app"), str(BACKEND_DIR / "app")]
    a += ["--tmpfs", str(DATA_DIR)]  # hides DB, keys, other tenants' files; specific files re-bound below
    for p in ro:
        if p and os.path.exists(p):
            a += ["--ro-bind", p, p]
    a += ["--bind", scratch, scratch]
    for f in rw_files:
        Path(f).parent.mkdir(parents=True, exist_ok=True)
        Path(f).touch(exist_ok=True)
        a += ["--bind", f, f]
    a += ["--chdir", scratch, "--seccomp", str(r)]
    return a + _worker_argv(str(VENV / "bin" / "python")), r


def docker_argv(scratch: str, ro: list[str], rw_files: list[str]) -> list[str]:
    a = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL",
         "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", f"{WORKER_MEMORY_MB}m",
         "--cpus", "1", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--user", "65534:65534"]
    if DOCKER_RUNTIME:
        a += ["--runtime", DOCKER_RUNTIME]
    for p in ro:
        a += ["-v", f"{p}:{p}:ro"]
    a += ["-v", f"{scratch}:{scratch}:rw"] + [x for f in rw_files for x in ("-v", f"{f}:{f}:rw")]
    return a + ["-w", scratch, DOCKER_IMAGE] + _worker_argv("python")


def popen(spec_paths: dict, env: dict, **kw) -> subprocess.Popen:
    """spec_paths: {scratch, ro: [...], rw_files: [...]}. Returns a Popen with stdin/stdout pipes (text)."""
    b = active_backend()
    scratch, ro, rw = spec_paths["scratch"], spec_paths.get("ro", []), spec_paths.get("rw_files", [])
    common = dict(env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
    if b == "namespace":
        argv, fd = namespace_argv(scratch, ro, rw)
        try:
            return subprocess.Popen(argv, preexec_fn=rlimits, pass_fds=(fd,), cwd=scratch, **common)
        finally:
            os.close(fd)
    if b == "docker":
        return subprocess.Popen(docker_argv(scratch, ro, rw), cwd=scratch, **common)
    return subprocess.Popen(_worker_argv(sys.executable), preexec_fn=rlimits, cwd=str(BACKEND_DIR), **common)
