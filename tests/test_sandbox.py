"""Sandbox isolation tests. The namespace test runs only where bubblewrap + user namespaces work."""
import json, os, socket, sys, tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import sandbox  # noqa: E402
from app.security import issue_job_token, job_token_key  # noqa: E402


def _run(mode, extra, scratch, ro=()):
    sandbox._resolved = mode
    try:
        tok, _ = issue_job_token(0, 0)
        spec = {"token": tok, "token_key": job_token_key().hex(), "job_id": 0, "document_id": 0,
                "backend_dir": str(ROOT / "backend"), "selftest": True, **extra}
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "backend"), "SEALCHECK_SANDBOX": mode, "LANG": "C.UTF-8",
               "SEALCHECK_DATA_DIR": os.environ.get("SEALCHECK_DATA_DIR", "")}
        p = sandbox.popen({"scratch": scratch, "ro": list(ro)}, env)
        out, err = p.communicate(json.dumps(spec), timeout=60)
    finally:
        sandbox._resolved = None
    final = [json.loads(l) for l in out.splitlines() if l.strip()][-1]
    assert "selftest" in final, err[-2000:]
    return final["selftest"]


@pytest.mark.skipif(not sandbox.bwrap_ok(), reason="bubblewrap/user namespaces unavailable")
def test_namespace_sandbox_blocks_escape(tmp_path):
    host_sock = tempfile.mktemp(prefix="sealcheck-host-", suffix=".sock", dir="/tmp")
    srv = socket.socket(socket.AF_UNIX); srv.bind(host_sock); srv.listen(1)
    escape = ROOT / "escape_sandbox_test.txt"
    secret = Path(os.environ["SEALCHECK_DATA_DIR"]) / "keys" / "probe.secret"
    secret.parent.mkdir(parents=True, exist_ok=True); secret.write_text("s3cret")
    scratch = tempfile.mkdtemp(dir="/workspace")
    try:
        r = _run("namespace", {"write_targets": [str(escape), str(ROOT / "backend/app/pwn.py"), "/etc/pwn"],
                               "read_targets": [str(secret)], "unix_targets": [host_sock]}, scratch)
    finally:
        srv.close(); os.unlink(host_sock)
    # /workspace is an in-sandbox tmpfs: a write there "succeeds" but must never reach the host
    allowed = {k: v for k, v in r.items() if v == "ALLOWED" and k != f"write_outside:{escape}"}
    assert not allowed, allowed
    assert r["write_scratch_ok"] is True
    assert not escape.exists() and not (ROOT / "backend/app/pwn.py").exists()
    assert (Path(scratch) / "scratch.txt").read_text() == "ok"


def test_process_fallback_still_guards_inet(tmp_path):
    r = _run("process", {}, str(tmp_path))
    # process mode is weak by design: only the Python-level guard stops connect(); raw _socket is NOT blocked
    assert r["socket_inet_guarded"] != "ALLOWED"
    assert r["write_scratch_ok"] is True


def test_seccomp_program_shape():
    prog = sandbox.seccomp_bpf()
    assert len(prog) % 8 == 0 and len(prog) // 8 == 11 + len(set(sandbox.DENY.values()))


def test_docker_argv_hardening():
    argv = sandbox.docker_argv("/tmp/s", ["/data/in.pdf"], [])
    j = " ".join(argv)
    for flag in ("--network none", "--read-only", "--cap-drop", "--security-opt"):
        assert flag in j, flag
    assert "/data/in.pdf:/data/in.pdf:ro" in j


def test_process_fallback_logs_visible_warning(monkeypatch, caplog):
    """Acceptance-pass regression: without bubblewrap the dev server must say so at start-up."""
    import logging
    from fastapi.testclient import TestClient
    from app import main, sandbox as sb
    monkeypatch.setattr(sb, "active_backend", lambda: "process")
    with caplog.at_level(logging.WARNING, logger="sealcheck"):
        with TestClient(main.app):
            pass
    assert any("process' fallback" in r.getMessage() for r in caplog.records)


def test_run_sh_checks_prerequisites():
    from pathlib import Path
    s = (Path(__file__).resolve().parent.parent / "run.sh").read_text()
    assert "3, 11" in s and ">= 18" in s and "bubblewrap not found" in s
