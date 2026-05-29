"""Secret/private-key sweep via gitleaks.

gitleaks has high recall for PEM-armored private keys. We run it over the flattened
filesystem and keep only key-bearing findings; every reported key path is later
re-parsed by the built-in extractor, so gitleaks contributes recall, not ground truth.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile


def extract(root: str, gitleaks_bin: str = "gitleaks", timeout_s: int = 300) -> tuple[list[dict], str | None]:
    """Return (findings, error). Each finding: {path, rule}."""
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "gitleaks.json")
        cmd = [
            gitleaks_bin, "dir", root,
            "--report-format", "json",
            "--report-path", report,
            "--no-banner",
            "--exit-code", "0",  # findings are expected; do not treat as failure
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=False)
        except FileNotFoundError:
            return [], "gitleaks binary not found"
        except subprocess.TimeoutExpired:
            return [], "gitleaks timed out"
        try:
            with open(report) as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return [], None  # no report written == no findings
    findings = []
    for item in raw or []:
        rule = (item.get("RuleID") or item.get("Rule") or "").lower()
        if "key" in rule or "private" in rule:
            findings.append({"path": item.get("File", ""), "rule": rule})
    return findings, None
