"""
Validate synced live data from source repositories.

Checks that fetched JSON/CSV/TXT files are legitimate:
  - JSON files parse without errors
  - Required fields exist in structured data
  - Files are non-empty and within reasonable size bounds
  - Generates SHA-256 checksums for an integrity manifest

Exit code 0 = all validations passed; non-zero = failures found.
"""

import hashlib
import json
import sys
from pathlib import Path

STAGING_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_staging")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB upper bound
MIN_JSON_SIZE = 2                  # at least "{}" or "[]"

REQUIRED_DAILY_INTEL_FIELDS = {
    "generated_at",
    "top_3_developments",
    "signal_updates",
    "entities_scanned",
}

REQUIRED_VERIFICATION_FIELDS = {
    "generated_at",
    "total_predictions",
    "results",
}

REQUIRED_NODE_STATUS_FIELDS = {
    "run_timestamp",
    "node_statuses",
}

REQUIRED_CONVERGENCE_FIELDS = {
    "analysis_timestamp",
    "convergence_events",
}

REQUIRED_FACT_CHECK_FIELDS = {
    "checked_at",
    "corrections_applied",
}

errors: list[str] = []
manifest: dict[str, dict] = {}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_json(path: Path, required_fields: set[str] | None = None) -> dict | list | None:
    """Parse a JSON file and optionally check for required top-level keys."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        errors.append(f"INVALID JSON — {path.name}: {exc}")
        return None
    except OSError as exc:
        errors.append(f"READ ERROR — {path.name}: {exc}")
        return None

    if required_fields and isinstance(data, dict):
        missing = required_fields - data.keys()
        if missing:
            errors.append(f"MISSING FIELDS in {path.name}: {sorted(missing)}")

    return data


def validate_file_size(path: Path) -> bool:
    size = path.stat().st_size
    if size == 0:
        errors.append(f"EMPTY FILE — {path.name}")
        return False
    if size > MAX_FILE_SIZE:
        errors.append(f"FILE TOO LARGE — {path.name}: {size:,} bytes")
        return False
    return True


def main() -> int:
    if not STAGING_DIR.is_dir():
        print(f"ERROR: Staging directory not found: {STAGING_DIR}")
        return 1

    files = sorted(STAGING_DIR.rglob("*"))
    files = [f for f in files if f.is_file()]

    if not files:
        print(f"ERROR: No files found in {STAGING_DIR}")
        return 1

    print(f"Validating {len(files)} files in {STAGING_DIR} ...")

    for fpath in files:
        rel = fpath.relative_to(STAGING_DIR)
        print(f"  Checking {rel} ...", end=" ")

        if not validate_file_size(fpath):
            print("FAIL (size)")
            continue

        # JSON-specific validation
        if fpath.suffix == ".json":
            required = None
            if fpath.name == "daily_intelligence.json":
                required = REQUIRED_DAILY_INTEL_FIELDS
            elif fpath.name == "live_verification.json":
                required = REQUIRED_VERIFICATION_FIELDS
            elif fpath.name == "node_status.json":
                required = REQUIRED_NODE_STATUS_FIELDS
            elif fpath.name == "convergence_report.json":
                required = REQUIRED_CONVERGENCE_FIELDS
            elif fpath.name == "fact_check.json":
                required = REQUIRED_FACT_CHECK_FIELDS

            if fpath.stat().st_size >= MIN_JSON_SIZE:
                result = validate_json(fpath, required)
                if result is None:
                    print("FAIL (json)")
                    continue

        # CSV sanity check — must have at least a header line
        if fpath.suffix == ".csv":
            with open(fpath, encoding="utf-8") as f:
                first_line = f.readline().strip()
            if not first_line:
                errors.append(f"EMPTY CSV — {fpath.name}")
                print("FAIL (csv)")
                continue

        # Compute checksum for manifest
        checksum = sha256_of(fpath)
        manifest[str(rel)] = {
            "sha256": checksum,
            "size": fpath.stat().st_size,
        }
        print("OK")

    # Write manifest
    manifest_path = STAGING_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            {"file_count": len(manifest), "files": manifest},
            f,
            indent=2,
        )
    print(f"\nManifest written: {manifest_path} ({len(manifest)} files)")

    if errors:
        print(f"\n{'='*60}")
        print(f"VALIDATION FAILED — {len(errors)} error(s):")
        for err in errors:
            print(f"  ✗ {err}")
        print(f"{'='*60}")
        return 1

    print(f"\n✅ All {len(manifest)} files passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
