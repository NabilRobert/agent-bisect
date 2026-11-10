"""The public-repo check (requirement N7, threat T9), run by `make check` and CI.

It fails when a tracked file holds something this public repo must never
carry: a server address (any IPv4 literal outside loopback and the
documentation ranges), a former employer's or client's name, a private
note, or a recording (tapes hold prompts and tool results).

The names are kept as SHA-256 hashes of lower-case words in
`public_denylist.sha256`, so the list doesn't publish what it guards
against. To add a word: `printf %s word | shasum -a 256` and append the hash.

Plain Python on purpose: a framework would be heavier than 80 lines.
"""

import hashlib
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

DENYLIST_PATH = Path(__file__).with_name("public_denylist.sha256")

# Loopback, "any address" and the RFC 5737 documentation ranges are safe to show.
ALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/32"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]
IPV4_PATTERN = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
WORD_PATTERN = re.compile(r"[a-z0-9]+")

# Lock files are full of hashes and dotted versions; they hold no prose.
SKIPPED_FILES = {"uv.lock", "scripts/public_denylist.sha256"}
RECORDING_SUFFIXES = (".db", ".sqlite", ".tape", ".zst", ".flightrec")
PRIVATE_PATH = re.compile(r"(^|/)(HANDOVER[^/]*\.md|private/|backups/)")


def load_denylist(path: Path = DENYLIST_PATH) -> set[str]:
    lines = path.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def problems_in_name(path: str) -> list[str]:
    """A private note or a recording, judged by its path alone."""
    if PRIVATE_PATH.search(path):
        return [f"{path}: private notes never go in the repo"]
    if path.endswith(RECORDING_SUFFIXES):
        return [
            f"{path}: recordings stay out of the repo (incidents go in via `afr incident save`)"
        ]
    return []


def problems_in_text(path: str, text: str, denied_hashes: set[str]) -> list[str]:
    """Server addresses and denylisted names in a file's text."""
    problems: list[str] = []
    for match in IPV4_PATTERN.finditer(text):
        if not is_allowed_address(match.group(1)):
            address = match.group(1)
            problems.append(f"{path}: IPv4 address {address} (no server addresses in public)")
    for word in set(WORD_PATTERN.findall(text.lower())):
        if hashlib.sha256(word.encode()).hexdigest() in denied_hashes:
            problems.append(f"{path}: a denylisted name (see scripts/check_public.py)")
    return problems


def is_allowed_address(literal: str) -> bool:
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        return True  # "999.1.2.3" is a version-like string, not an address
    return any(address in network for network in ALLOWED_NETWORKS)


def tracked_files() -> list[str]:
    # git from PATH, as every developer and CI runner has it; no user input reaches the command.
    command = ["git", "ls-files", "-z"]
    listing = subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603
    return [path for path in listing.split("\0") if path]


def find_problems(paths: list[str], denied_hashes: set[str]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        problems.extend(problems_in_name(path))
        if path in SKIPPED_FILES or not Path(path).is_file():
            continue
        try:
            text = Path(path).read_text()
        except UnicodeDecodeError:
            continue  # binary files (images) hold no prose
        problems.extend(problems_in_text(path, text, denied_hashes))
    return problems


def main() -> int:
    problems = find_problems(tracked_files(), load_denylist())
    for problem in problems:
        print(problem)
    print("public-repo check: " + ("FAILED" if problems else "passed"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
