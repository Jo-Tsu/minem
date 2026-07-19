import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_TIMEOUTS = {
    "python_compile": 30,
    "frontend_build": 90,
    "api_contract": 20,
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _run(command, *, cwd, timeout):
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = proc.stdout[-12000:] if proc.stdout else ""
        return {
            "command": command,
            "ok": proc.returncode == 0,
            "returnCode": proc.returncode,
            "durationMs": int((time.time() - started) * 1000),
            "output": output,
        }
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") if isinstance(error.stdout, str) else ""
        return {
            "command": command,
            "ok": False,
            "returnCode": None,
            "durationMs": int((time.time() - started) * 1000),
            "output": (output + "\nTimed out").strip(),
        }


def python_compile(root):
    files = ["server.py", "minem", "scripts/check_api_contract.py"]
    existing = [item for item in files if (Path(root) / item).exists()]
    return _run(["python3", "-m", "compileall", "-q", *existing], cwd=root, timeout=DEFAULT_TIMEOUTS["python_compile"])


def frontend_build(root):
    package_json = Path(root) / "package.json"
    frontend_package = Path(root) / "frontend" / "package.json"
    if not package_json.exists() and not frontend_package.exists():
        return {"command": ["npm", "run", "build"], "ok": False, "returnCode": None, "durationMs": 0, "output": "package.json not found"}
    return _run(["npm", "run", "build"], cwd=root, timeout=DEFAULT_TIMEOUTS["frontend_build"])


def is_loopback_base_url(base_url):
    parsed = urlparse(str(base_url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in LOOPBACK_HOSTS


def api_contract(root, *, base_url="http://127.0.0.1:8790"):
    script = Path(root) / "scripts" / "check_api_contract.py"
    if not script.exists():
        return {"command": ["python3", str(script)], "ok": False, "returnCode": None, "durationMs": 0, "output": "check_api_contract.py not found"}
    if not is_loopback_base_url(base_url):
        return {
            "command": ["python3", str(script), "--base-url", base_url],
            "ok": False,
            "returnCode": None,
            "durationMs": 0,
            "output": "api_contract base_url must point to localhost or 127.0.0.1",
        }
    return _run(["python3", str(script), "--base-url", base_url], cwd=root, timeout=DEFAULT_TIMEOUTS["api_contract"])


CHECKS = {
    "python_compile": python_compile,
    "frontend_build": frontend_build,
    "api_contract": api_contract,
}


def validate_change(root, *, checks=None, base_url="http://127.0.0.1:8790"):
    root = Path(root)
    checks = checks or ["python_compile"]
    results = []
    for check in checks:
        runner = CHECKS.get(check)
        if not runner:
            results.append({
                "command": [],
                "check": check,
                "ok": False,
                "returnCode": None,
                "durationMs": 0,
                "output": f"Unknown check: {check}",
            })
            continue
        if check == "api_contract":
            result = runner(root, base_url=base_url)
        else:
            result = runner(root)
        result["check"] = check
        results.append(result)
    return {
        "ok": all(result["ok"] for result in results),
        "checks": results,
    }
