"""Independent CycloneDX-CBOM extraction via CBOM-Lens (OmniTrustILM, v1.0.0).

CBOM-Lens is an independent, third-party cryptographic-asset scanner. We run it over
the same flattened filesystem and record its component counts. Because it is
independent of the built-in extractor, the comparison between CBOM-Lens and any other
independent tool (e.g. cbomkit-theia) is a legitimate inter-tool divergence signal;
the comparison between CBOM-Lens and the built-in extractor is a calibration check.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
from collections import Counter

from ..schema import ToolObservation

_CONFIG_TEMPLATE = """version: 0
service:
  mode: manual
  verbose: false
  log: stderr
  dir: {out_dir}
filesystem:
  enabled: true
  paths:
    - {scan_path}
containers:
  enabled: false
ports:
  enabled: false
"""


def observe(root: str, cbom_lens_bin: str = "cbom-lens", timeout_s: int = 300) -> ToolObservation:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = os.path.join(tmp, "out")
        os.makedirs(out_dir, exist_ok=True)
        config_path = os.path.join(tmp, "cbom-lens.yaml")
        with open(config_path, "w") as handle:
            handle.write(_CONFIG_TEMPLATE.format(out_dir=out_dir, scan_path=root))
        try:
            subprocess.run(
                [cbom_lens_bin, "run", "--config", config_path],
                capture_output=True, timeout=timeout_s, check=False,
            )
        except FileNotFoundError:
            return ToolObservation("cbom-lens", 0, 0, 0, error="binary not found")
        except subprocess.TimeoutExpired:
            return ToolObservation("cbom-lens", 0, 0, 0, error="timed out")

        outputs = sorted(glob.glob(os.path.join(out_dir, "*.json")), key=os.path.getmtime)
        if not outputs:
            return ToolObservation("cbom-lens", 0, 0, 0, error="no output produced")
        try:
            with open(outputs[-1]) as handle:
                bom = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return ToolObservation("cbom-lens", 0, 0, 0, error=f"unparseable output: {exc}")

    counts: Counter[str] = Counter()
    for component in bom.get("components", []):
        asset_type = component.get("cryptoProperties", {}).get("assetType", "?")
        counts[asset_type] += 1
    return ToolObservation(
        tool="cbom-lens",
        certificates=counts.get("certificate", 0),
        keys=counts.get("related-crypto-material", 0),
        algorithms=counts.get("algorithm", 0),
    )
