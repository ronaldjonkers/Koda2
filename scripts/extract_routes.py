#!/usr/bin/env python3
"""Analyze koda2/api/routes.py and group endpoints by domain.

Usage: python scripts/extract_routes.py
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

ROUTES_FILE = Path("koda2/api/routes.py")

DOMAIN_PREFIXES = {
    "calendar": ["/calendar", "/events"],
    "contacts": ["/contacts"],
    "video": ["/video", "/meetings"],
    "email": ["/email", "/mail"],
    "messaging": ["/messaging", "/whatsapp", "/telegram", "/webhook"],
    "documents": ["/documents", "/docs", "/presentations"],
    "tasks": ["/tasks", "/scheduler", "/queue"],
    "agent": ["/agent", "/orchestrat", "/chat", "/message"],
    "health": ["/health", "/status", "/ping"],
}


def classify_route(path: str) -> str:
    path_lower = path.lower()
    for domain, prefixes in DOMAIN_PREFIXES.items():
        for prefix in prefixes:
            if prefix in path_lower:
                return domain
    return "misc"


def main():
    if not ROUTES_FILE.exists():
        print(f"File not found: {ROUTES_FILE}")
        sys.exit(1)

    content = ROUTES_FILE.read_text()
    # Match @router.get("/path"), @router.post("/path"), etc.
    pattern = re.compile(
        r'@\w*router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )

    groups = defaultdict(list)
    for match in pattern.finditer(content):
        method = match.group(1).upper()
        path = match.group(2)
        domain = classify_route(path)
        line_num = content[: match.start()].count("\n") + 1
        groups[domain].append((method, path, line_num))

    print("=" * 60)
    print("Route Analysis — koda2/api/routes.py")
    print("=" * 60)
    total = 0
    for domain in sorted(groups.keys()):
        routes = groups[domain]
        total += len(routes)
        print(f"\n## {domain}.py ({len(routes)} endpoints)")
        for method, path, line in routes:
            print(f"  L{line:4d}  {method:6s} {path}")

    print(f"\n{'=' * 60}")
    print(f"Total: {total} endpoints across {len(groups)} modules")


if __name__ == "__main__":
    main()
