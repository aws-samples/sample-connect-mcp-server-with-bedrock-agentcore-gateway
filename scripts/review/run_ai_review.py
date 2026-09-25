#!/usr/bin/env python3
"""Run an AI reviewer with a hard deadline and preserve its emitted output."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess  # nosec B404
import sys
import tempfile

TIMEOUT_EXIT_CODE = 124


def _stop_process_group(process: subprocess.Popen[bytes], grace_seconds: float) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(grace_seconds, 0.1))
    except subprocess.TimeoutExpired:
        # A detached descendant may outlive the process group. Output is written to
        # regular files below, so the caller can still return without waiting on pipes.
        pass


def run(command: list[str], timeout_seconds: float, grace_seconds: float) -> int:
    request = sys.stdin.buffer.read()
    with (
        tempfile.TemporaryFile() as request_stream,
        tempfile.TemporaryFile() as stdout_stream,
        tempfile.TemporaryFile() as stderr_stream,
    ):
        request_stream.write(request)
        request_stream.seek(0)
        try:
            # The trusted caller supplies argv directly and shell execution is disabled.
            # nosemgrep: dangerous-subprocess-use-audit
            process = subprocess.Popen(  # noqa: S603  # nosec B603
                command,
                stdin=request_stream,
                stdout=stdout_stream,
                stderr=stderr_stream,
                start_new_session=True,
            )
        except FileNotFoundError:
            print(f"reviewer command not found: {command[0]}", file=sys.stderr)
            return 127

        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process_group(process, grace_seconds)

        stdout_stream.flush()
        stderr_stream.flush()
        stdout_stream.seek(0)
        stderr_stream.seek(0)
        sys.stdout.buffer.write(stdout_stream.read())
        sys.stderr.buffer.write(stderr_stream.read())

        if timed_out:
            print(
                f"reviewer timed out after {timeout_seconds:g}s; partial output was preserved",
                file=sys.stderr,
            )
            return TIMEOUT_EXIT_CODE
        return process.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--grace", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a reviewer command is required after --")
    if args.timeout <= 0 or args.grace < 0:
        parser.error("timeout must be positive and grace must be non-negative")
    return run(command, args.timeout, args.grace)


if __name__ == "__main__":
    raise SystemExit(main())
