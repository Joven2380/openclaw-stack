#!/usr/bin/env python3
"""
Verify that the production deployment at bottleneck-ai.com is healthy.

Usage:
    python scripts/verify_deployment.py
    python scripts/verify_deployment.py --base-url https://bottleneck-ai.com
"""

import argparse
import sys
import httpx

BASE_URL = "https://bottleneck-ai.com"

CHECKS = [
    {
        "label": "Health check",
        "method": "GET",
        "path": "/health/",
        "expect_status": 200,
        "expect_keys": ["status", "version", "env"],
    },
    {
        "label": "Health/ready (DB connectivity)",
        "method": "GET",
        "path": "/health/ready",
        "expect_status": 200,
        "expect_keys": ["status", "db"],
    },
    {
        "label": "Agents list",
        "method": "GET",
        "path": "/agents/list",
        "expect_status": 200,
        "expect_json_array": True,
    },
    {
        "label": "HTTPS redirect (www → apex)",
        "method": "GET",
        "path": "/health/",
        "override_host": "https://www.bottleneck-ai.com",
        "expect_status": 200,   # httpx follows the redirect
    },
]

GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"
BOLD  = "\033[1m"


def check(client: httpx.Client, base_url: str, spec: dict) -> bool:
    host = spec.get("override_host", base_url)
    url = f"{host}{spec['path']}"
    try:
        resp = client.request(spec["method"], url, timeout=10, follow_redirects=True)
    except Exception as exc:
        print(f"  {RED}ERROR{RESET}  {spec['label']}: {exc}")
        return False

    ok = True

    if resp.status_code != spec["expect_status"]:
        print(f"  {RED}FAIL{RESET}   {spec['label']}: HTTP {resp.status_code} (expected {spec['expect_status']})")
        ok = False

    if ok and spec.get("expect_keys"):
        try:
            body = resp.json()
            missing = [k for k in spec["expect_keys"] if k not in body]
            if missing:
                print(f"  {RED}FAIL{RESET}   {spec['label']}: missing keys {missing}")
                ok = False
        except Exception:
            print(f"  {RED}FAIL{RESET}   {spec['label']}: response is not JSON")
            ok = False

    if ok and spec.get("expect_json_array"):
        try:
            body = resp.json()
            if not isinstance(body, list):
                print(f"  {RED}FAIL{RESET}   {spec['label']}: expected JSON array")
                ok = False
            else:
                extra = f"({len(body)} agents)"
        except Exception:
            print(f"  {RED}FAIL{RESET}   {spec['label']}: response is not JSON")
            ok = False

    if ok:
        extra = locals().get("extra", "")
        print(f"  {GREEN}PASS{RESET}   {spec['label']} {extra}".rstrip())

    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"\n{BOLD}openclaw-stack deployment verification{RESET}")
    print(f"Target: {base}\n")

    passed = 0
    failed = 0
    with httpx.Client() as client:
        for spec in CHECKS:
            if check(client, base, spec):
                passed += 1
            else:
                failed += 1

    print(f"\n{BOLD}Results: {passed} passed, {failed} failed{RESET}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
