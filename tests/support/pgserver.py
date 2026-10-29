"""Ephemeral PostgreSQL cluster for tests (uses local initdb/pg_ctl binaries).

Set OHMYPM_TEST_DATABASE_URL to use an existing server instead (e.g. the docker compose db).
Standalone use for development::

    python -m tests.support.pgserver /tmp/ohmypm-devpg 55433   # prints the URL, Ctrl-C stops
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def binaries_available() -> bool:
    return shutil.which("initdb") is not None and shutil.which("pg_ctl") is not None


class EphemeralPostgres:
    def __init__(self, base_dir: Path, port: int | None = None, user: str = "ohmypm") -> None:
        self.base_dir = base_dir
        self.data_dir = base_dir / "data"
        self.socket_dir = base_dir / "sock"
        self.port = port or free_port()
        self.user = user

    def url(self, database: str = "postgres") -> str:
        return f"postgresql+psycopg://{self.user}@127.0.0.1:{self.port}/{database}"

    def start(self) -> None:
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        if not (self.data_dir / "PG_VERSION").exists():
            subprocess.run(
                [
                    "initdb",
                    "-D",
                    str(self.data_dir),
                    "-U",
                    self.user,
                    "--auth=trust",
                    "-E",
                    "UTF8",
                    "--locale=C.UTF-8",
                    "--no-instructions",
                ],
                check=True,
                capture_output=True,
            )
        opts = (
            f"-p {self.port} -k {self.socket_dir} -c listen_addresses=127.0.0.1 "
            "-c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=200"
        )
        subprocess.run(
            ["pg_ctl", "-D", str(self.data_dir), "-o", opts, "-l", str(self.base_dir / "pg.log"), "-w", "start"],
            check=True,
            capture_output=True,
        )

    def create_database(self, name: str) -> str:
        import psycopg

        with psycopg.connect(
            f"host=127.0.0.1 port={self.port} user={self.user} dbname=postgres", autocommit=True
        ) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{name}"')
        return self.url(name)

    def stop(self) -> None:
        subprocess.run(
            ["pg_ctl", "-D", str(self.data_dir), "-m", "immediate", "stop"], check=False, capture_output=True
        )


if __name__ == "__main__":
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ohmypm-devpg")
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 55433
    pg = EphemeralPostgres(base, port)
    pg.start()
    print(pg.create_database("ohmypm") if "--fresh" in sys.argv else pg.url("ohmypm"), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pg.stop()
