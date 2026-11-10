"""The public-repo check: what it must catch, and what it must let through."""

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType


def load_check() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "check_public.py"
    spec = importlib.util.spec_from_file_location("check_public", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load_check()
DENIED = {hashlib.sha256(b"examplecorp").hexdigest()}
# Joined at run time, so this file passes the check it tests.
PUBLIC_ADDRESS = ".".join(["8", "8", "4", "4"])


def test_a_server_address_is_flagged() -> None:
    problems = check.problems_in_text("notes.md", f"deploy to {PUBLIC_ADDRESS} tonight", DENIED)

    assert problems == [f"notes.md: IPv4 address {PUBLIC_ADDRESS} (no server addresses in public)"]


def test_loopback_and_documentation_addresses_pass() -> None:
    text = "ollama on 127.0.0.1:11434, bind 0.0.0.0, example 203.0.113.7"

    assert check.problems_in_text("README.md", text, DENIED) == []


def test_a_dotted_number_that_cannot_be_an_address_passes() -> None:
    assert check.problems_in_text("CHANGELOG.md", "build 999.1.2.3", DENIED) == []


def test_a_denylisted_name_is_flagged_in_any_case() -> None:
    problems = check.problems_in_text("docs/cv.md", "Worked at ExampleCorp.", DENIED)

    assert problems == ["docs/cv.md: a denylisted name (see scripts/check_public.py)"]


def test_a_handover_note_is_flagged_by_its_name() -> None:
    assert check.problems_in_name("docs/HANDOVER-week2.md") != []


def test_a_recorded_tape_is_flagged_by_its_name() -> None:
    assert check.problems_in_name("runs/a1/run-07.db") != []


def test_the_committed_denylist_holds_only_hashes() -> None:
    hashes = check.load_denylist()

    assert hashes
    assert all(len(entry) == 64 and int(entry, 16) >= 0 for entry in hashes)


def test_tapes_of_the_synthetic_benchmark_set_may_be_committed() -> None:
    assert check.problems_in_name("bench/frozen/a1/runs/a1-x-bad/tape.db") == []
