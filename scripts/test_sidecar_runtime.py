#!/usr/bin/env python3
"""Run the built desktop sidecar against a fresh runtime and check its resources."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "desktop/.build/minem-server")
    args = parser.parse_args()
    expected = json.loads((ROOT / "product-version.json").read_text())["version"]
    with tempfile.TemporaryDirectory(prefix="minem-sidecar-test-") as runtime:
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        env = {**os.environ, "MINEM_DATA_DIR": runtime, "HOST": "127.0.0.1", "PORT": str(port), "AUTO_IMPORT_ON_START": "0"}
        env.pop("MINEM_APP_ROOT", None)
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([str(args.binary.resolve())], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise AssertionError("Packaged service exited before becoming available")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/version", timeout=.5) as response:
                            data = json.load(response)
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError("Packaged service did not start")
                assert data["release"]["version"] == expected, data
                with urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                    assert b"MineM" in response.read()
                print(json.dumps({"packagedService": "passed", "webAssets": "passed", "version": expected}))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
