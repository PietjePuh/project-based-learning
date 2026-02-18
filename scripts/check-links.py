#!/usr/bin/env python3
"""
Link Checker for project-based-learning README.md

Validates all URLs found in Markdown files and reports broken links.
Supports concurrent checking for faster execution.

Usage:
    python scripts/check-links.py [--file README.md] [--timeout 10] [--workers 10]
"""

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required.")
    print("Install it with: pip install requests")
    sys.exit(1)


@dataclass
class LinkResult:
    """Result of checking a single URL."""

    url: str
    status_code: int
    ok: bool
    error: str
    line_number: int
    context: str


def extract_links(filepath: str) -> list[tuple[str, int, str]]:
    """Extract all URLs from a Markdown file.

    Returns a list of (url, line_number, context) tuples.
    """
    url_pattern = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
    bare_url_pattern = re.compile(r"(?<!\()(https?://\S+)")

    links: list[tuple[str, int, str]] = []
    seen_urls: set[str] = set()

    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    content = path.read_text(encoding="utf-8")

    for line_num, line in enumerate(content.splitlines(), start=1):
        # Markdown links: [text](url)
        for match in url_pattern.finditer(line):
            url = match.group(2)
            context = match.group(1)
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((url, line_num, context))

        # Bare URLs not inside markdown links
        for match in bare_url_pattern.finditer(line):
            url = match.group(0).rstrip(".,;:!?)")
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((url, line_num, url[:60]))

    return links


def check_link(url: str, line_number: int, context: str, timeout: int) -> LinkResult:
    """Check if a URL is reachable."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; LinkChecker/1.0; "
            "+https://github.com/PietjePuh/project-based-learning)"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*",
    }

    try:
        response = requests.head(
            url, headers=headers, timeout=timeout, allow_redirects=True
        )

        # Some servers don't support HEAD, try GET if we get 405 or 403
        if response.status_code in (405, 403):
            response = requests.get(
                url, headers=headers, timeout=timeout, allow_redirects=True
            )

        return LinkResult(
            url=url,
            status_code=response.status_code,
            ok=response.status_code < 400,
            error="" if response.status_code < 400 else f"HTTP {response.status_code}",
            line_number=line_number,
            context=context,
        )
    except requests.exceptions.Timeout:
        return LinkResult(
            url=url,
            status_code=0,
            ok=False,
            error="Timeout",
            line_number=line_number,
            context=context,
        )
    except requests.exceptions.ConnectionError:
        return LinkResult(
            url=url,
            status_code=0,
            ok=False,
            error="Connection failed",
            line_number=line_number,
            context=context,
        )
    except requests.exceptions.TooManyRedirects:
        return LinkResult(
            url=url,
            status_code=0,
            ok=False,
            error="Too many redirects",
            line_number=line_number,
            context=context,
        )
    except requests.exceptions.RequestException as e:
        return LinkResult(
            url=url,
            status_code=0,
            ok=False,
            error=str(e)[:100],
            line_number=line_number,
            context=context,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check for broken links in Markdown files"
    )
    parser.add_argument(
        "--file",
        default="README.md",
        help="Markdown file to check (default: README.md)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent workers (default: 10)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "github"],
        default="text",
        help="Output format: text or github (for GitHub Actions annotations)",
    )
    args = parser.parse_args()

    print(f"Extracting links from {args.file}...")
    links = extract_links(args.file)
    print(f"Found {len(links)} unique links to check.\n")

    if not links:
        print("No links found.")
        return

    results: list[LinkResult] = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_link = {
            executor.submit(check_link, url, line_num, ctx, args.timeout): url
            for url, line_num, ctx in links
        }

        for i, future in enumerate(as_completed(future_to_link), start=1):
            result = future.result()
            results.append(result)

            status = "OK" if result.ok else "BROKEN"
            symbol = "." if result.ok else "X"
            print(f"  [{i}/{len(links)}] {symbol} {result.url[:80]}", end="")
            if not result.ok:
                print(f" - {result.error}", end="")
            print()

    elapsed = time.time() - start_time
    broken = [r for r in results if not r.ok]
    ok_count = len(results) - len(broken)

    print(f"\n{'=' * 60}")
    print(f"Results: {ok_count} OK, {len(broken)} broken ({elapsed:.1f}s)")
    print(f"{'=' * 60}")

    if broken:
        print(f"\nBroken links ({len(broken)}):\n")
        broken.sort(key=lambda r: r.line_number)

        for result in broken:
            if args.output == "github":
                print(
                    f"::error file={args.file},line={result.line_number}::"
                    f"Broken link: {result.url} ({result.error})"
                )
            else:
                print(f"  Line {result.line_number}: {result.context}")
                print(f"    URL: {result.url}")
                print(f"    Error: {result.error}")
                print()

        sys.exit(1)
    else:
        print("\nAll links are valid!")
        sys.exit(0)


if __name__ == "__main__":
    main()
