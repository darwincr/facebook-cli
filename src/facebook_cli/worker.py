from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from facebook_cli.conf import WORKER_IDLE_TIMEOUT_S, facebook_cli_home
from facebook_cli.session import FacebookSession, session_lock
from facebook_cli.session import _locks_dir


CONNECT_TIMEOUT_S = 60


def _worker_dir() -> Path:
    path = facebook_cli_home() / "workers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in name)


def socket_path(name: str) -> Path:
    return _worker_dir() / f"{_safe_name(name)}.sock"


def _log_path(name: str) -> Path:
    path = facebook_cli_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"worker-{_safe_name(name)}.log"


@contextmanager
def _startup_lock(name: str):
    import fcntl

    path = _locks_dir() / f"{name}.worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _send_request(path: Path, payload: dict, *, timeout: float | None = None) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        if timeout is not None:
            client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    if not chunks:
        raise RuntimeError("facebook-cli worker closed the connection without a response")
    return json.loads(b"".join(chunks).decode("utf-8"))


def _try_request(name: str, payload: dict) -> dict | None:
    path = socket_path(name)
    if not path.exists():
        return None
    try:
        return _send_request(path, payload)
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return None


def _start_worker(name: str) -> None:
    log = _log_path(name).open("ab", buffering=0)
    env = os.environ.copy()
    env["FACEBOOK_CLI_WORKER"] = "1"
    subprocess.Popen(
        [sys.executable, "-m", "facebook_cli.worker", name],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        env=env,
        close_fds=True,
        start_new_session=True,
    )


def _wait_for_worker(name: str) -> None:
    deadline = time.monotonic() + CONNECT_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            response = _send_request(socket_path(name), {"ping": True}, timeout=1)
            if response.get("returncode") == 0:
                return
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"facebook-cli worker for session {name!r} did not start within {CONNECT_TIMEOUT_S} seconds")


def run_via_worker(name: str, argv: list[str]) -> int:
    payload = {"argv": argv}
    response = _try_request(name, payload)
    if response is None:
        with _startup_lock(name):
            response = _try_request(name, payload)
            if response is None:
                _start_worker(name)
                _wait_for_worker(name)
                response = _send_request(socket_path(name), payload)

    if response is None:
        response = _send_request(socket_path(name), payload)

    stdout = response.get("stdout") or ""
    stderr = response.get("stderr") or ""
    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    return int(response.get("returncode") or 0)


def stop_worker(name: str) -> None:
    response = _try_request(name, {"shutdown": True})
    if response is None:
        return
    path = socket_path(name)
    deadline = time.monotonic() + 10
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)


def _execute_request(session: FacebookSession, argv: list[str]) -> dict:
    import contextlib
    import io

    from facebook_cli.cli import _execute_verb, _parse_args

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            args = _parse_args(argv)
            returncode = _execute_verb(args, session)
        except SystemExit as exc:
            returncode = int(exc.code or 0)
        except Exception as exc:  # noqa: BLE001
            returncode = 1
            print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
    return {"returncode": returncode, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}


def serve(name: str) -> int:
    path = socket_path(name)

    with session_lock(name), FacebookSession(name) as session:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(64)
        server.settimeout(1)
        idle_deadline = time.monotonic() + WORKER_IDLE_TIMEOUT_S
        shutdown = False
        try:
            while not shutdown and time.monotonic() < idle_deadline:
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                idle_deadline = time.monotonic() + WORKER_IDLE_TIMEOUT_S
                with conn:
                    raw = b""
                    while not raw.endswith(b"\n"):
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        raw += chunk
                    try:
                        request = json.loads(raw.decode("utf-8")) if raw else {}
                        if request.get("shutdown"):
                            shutdown = True
                            response = {"returncode": 0, "stdout": "", "stderr": ""}
                        elif request.get("ping"):
                            response = {"returncode": 0, "stdout": "", "stderr": ""}
                        else:
                            response = _execute_request(session, list(request.get("argv") or []))
                    except Exception as exc:  # noqa: BLE001
                        response = {"returncode": 1, "stdout": "", "stderr": f"error: worker: {exc}\n"}
                    conn.sendall(json.dumps(response).encode("utf-8"))
        finally:
            server.close()
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m facebook_cli.worker <session>", file=sys.stderr)
        return 2
    return serve(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
