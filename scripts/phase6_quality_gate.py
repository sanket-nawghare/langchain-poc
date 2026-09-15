"""Offline Phase 6 quality, security, and observability gate."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    ".python",
    ".tooling",
    "node_modules",
    "__pycache__",
}
SCANNED_SUFFIXES = {
    ".env",
    ".ini",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


def _iter_scanned_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        if path.suffix in SCANNED_SUFFIXES or path.name.endswith(".env.example"):
            files.append(path)
    return files


def check_dependency_locks(root: Path) -> GateResult:
    required = [
        root / "backend" / "uv.lock",
        root / "frontend" / "pnpm-lock.yaml",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    return GateResult(
        name="dependency_locks",
        passed=not missing,
        detail="present" if not missing else ", ".join(missing),
    )


def check_secret_patterns(root: Path) -> GateResult:
    findings: list[str] = []
    for path in _iter_scanned_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}:{name}")
    return GateResult(
        name="secret_patterns",
        passed=not findings,
        detail="none" if not findings else ", ".join(findings[:20]),
    )


def check_phase6_docs(root: Path) -> GateResult:
    required = [
        root / "docs" / "CURRENT_SYSTEM_CAPABILITIES.md",
        root / "docs" / "PHASE_6_QUALITY_SECURITY_OBSERVABILITY.md",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    return GateResult(
        name="phase6_docs",
        passed=not missing,
        detail="present" if not missing else ", ".join(missing),
    )


def run(root: Path) -> list[GateResult]:
    return [
        check_dependency_locks(root),
        check_secret_patterns(root),
        check_phase6_docs(root),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline Phase 6 quality/security gate."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    args = parser.parse_args()

    results = run(args.root.resolve())
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.name}: {result.detail}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
