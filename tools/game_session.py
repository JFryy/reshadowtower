"""Launch, drive, and stop a headless debug-enabled game for local tools.

Single responsibility: the process and debug-port plumbing shared by the
measurement and playthrough scripts.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISC = ROOT / "disc/Shadow Tower (USA).cue"
DEFAULT_BINARY = ROOT / "build-release/Shadow_Tower_Recompiled"
GAMEPLAY_ADDR = "80041d4c"
GAMEPLAY_SIGNATURE = "e8ffbd271d80023c"
START = 0x0008


def use_framework_debug_client() -> None:
    """Make the framework's debug_client importable."""
    from dependencies import framework_root

    path = str(framework_root() / "tools")
    if path not in sys.path:
        sys.path.insert(0, path)


def ensure_port_free(port: int) -> None:
    """Fail before launching if another process (possibly another game) owns the debug port."""
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise SystemExit(f"Debug port {port} is in use ({error}); close the other instance or pass --port.") from error


def query(port: int, command: str, **arguments: Any) -> dict[str, Any]:
    import debug_client

    result = debug_client.query("127.0.0.1", port, {"id": 1, "cmd": command, **arguments})
    if not result.get("ok"):
        raise RuntimeError(f"{command} failed: {result}")
    return result


def press(port: int, button: int) -> None:
    query(port, "set_input", buttons=0xFFFF ^ button)
    time.sleep(0.15)
    query(port, "clear_input")
    time.sleep(0.6)


def clean_environment(overrides: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Return (env, removed): the environment minus PSX_*/SHADOWTOWER_* overrides."""
    removed = {k: v for k, v in os.environ.items() if k.startswith(("PSX_", "SHADOWTOWER_"))}
    env = {k: v for k, v in os.environ.items() if k not in removed}
    env.update(overrides or {})
    return env, removed


def launch_command(binary: Path, disc: Path, port: int, out: Path, renderer: str = "software",
                   game: Path = ROOT / "game.toml") -> list[str]:
    command = [str(binary), "--game", str(game), "--disc", str(disc),
               "--no-launcher", "--renderer", renderer,
               "--debug-port", str(port), "--memcard-dir", str(out / "saves")]
    if renderer == "software":
        command.append("--headless")
    return command


def wait_for_debug_server(proc: subprocess.Popen[Any], port: int, log_path: Path,
                          timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"Runtime exited {proc.returncode}; see {log_path}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Debug server unavailable; see {log_path}")
            time.sleep(0.1)


def reach_gameplay(port: int) -> None:
    """Press Start until the gameplay executable is resident, then let it load."""
    for _ in range(20):
        signature = query(port, "read_ram", addr=GAMEPLAY_ADDR, len=8)["hex"]
        if signature == GAMEPLAY_SIGNATURE:
            break
        press(port, START)  # Skip intro / title transitions.
        time.sleep(0.5)
    else:
        raise RuntimeError("Gameplay executable not reached after 20 Start presses")
    time.sleep(4)  # The executable becomes resident before loading finishes.


def terminate(proc: subprocess.Popen[Any]) -> bool:
    """SIGTERM then kill after 5 s. Returns True if a kill was needed."""
    if proc.poll() is not None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=5)
        return False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return True
