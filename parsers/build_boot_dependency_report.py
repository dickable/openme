"""Build a read-only boot-dependency report from an SPI image.

The report is a composition of the existing IFD, ME/FPT, CPD, and CPD
manifest inspectors.  It intentionally reports only structural metadata and
hashes.  It does not extract, execute, decompress, or write firmware bytes,
and it does not claim that a CPD name alone proves a boot dependency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .inspect_cpd import inspect_cpd
    from .inspect_cpd_manifest import inspect_cpd_manifest
    from .inspect_ifd import inspect_ifd
    from .inspect_me import inspect_me
except ImportError:  # pragma: no cover - supports direct script execution
    from inspect_cpd import inspect_cpd
    from inspect_cpd_manifest import inspect_cpd_manifest
    from inspect_ifd import inspect_ifd
    from inspect_me import inspect_me


_REGION_FIELDS = ("index", "name", "flreg", "offset", "size", "end", "sha256")
_PARTITION_FIELDS = (
    "index",
    "name",
    "offset_in_me_region",
    "absolute_offset",
    "size",
    "end_in_me_region",
    "sha256",
)
_MODULE_FIELDS = (
    "index",
    "name",
    "name_field_size",
    "entry_offset",
    "packed_offset",
    "offset_in_partition",
    "size",
    "flags",
    "trailing_word",
    "sha256",
)
_MANIFEST_FIELDS = (
    "record_offset_in_ftpr",
    "record_size",
    "identifier",
    "raw_field_words",
    "declared_area_length",
    "declared_area_end_in_ftpr",
    "bounded_range_candidate",
)
_METADATA_FIELDS = (
    "index",
    "record_offset_in_ftpr",
    "record_size",
    "identifier",
    "raw_field_words",
    "bounded_range_candidate",
)


def _pick(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Copy only known scalar/layout fields from an inspector result."""

    return {field: item[field] for field in fields if field in item}


def _bounded_manifest(area: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return manifest metadata without accepting a byte-bearing extension."""

    if not area:
        return None
    result: dict[str, Any] = {
        "signature": area.get("signature"),
        "signature_offset": area.get("signature_offset"),
        "warnings": list(area.get("warnings", [])),
        "metadata_entry_count": area.get("metadata_entry_count", 0),
        "parsed_end_in_ftpr": area.get("parsed_end_in_ftpr"),
    }
    manifest = area.get("manifest")
    result["manifest"] = _pick(manifest, _MANIFEST_FIELDS) if manifest else None
    result["metadata_entries"] = [
        _pick(entry, _METADATA_FIELDS)
        for entry in area.get("metadata_entries", [])
        if isinstance(entry, dict)
    ]
    return result


def _classify_modules(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a bounded suffix-only classification to CPD names.

    ``.man`` and ``.met`` are treated as metadata records because those are
    explicit name/layout signals.  Every other safely decoded CPD name is
    only *likely* runtime code/data.  No dependency edge or boot order is
    inferred here.
    """

    likely_runtime: list[str] = []
    metadata: list[str] = []
    unknown: list[str] = []

    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            unknown.append(str(name))
        elif name.endswith((".man", ".met")):
            metadata.append(name)
        else:
            likely_runtime.append(name)

    return {
        "likely_runtime_modules": likely_runtime,
        "metadata_entries": metadata,
        "unknown_entries": unknown,
        "basis": (
            "Bounded name-based classification only: .man/.met names are "
            "metadata; other safely decoded CPD names are likely runtime "
            "modules. This does not establish execution, boot order, or a "
            "dependency edge."
        ),
    }


def _unresolved_dependencies(
    *,
    ifd: dict[str, Any],
    me: dict[str, Any],
    cpd: dict[str, Any],
    manifest: dict[str, Any],
    classification: dict[str, Any],
) -> list[dict[str, str]]:
    """Describe questions that this metadata-only pass cannot answer."""

    unresolved = [
        {
            "kind": "module_dependency_graph",
            "status": "unknown",
            "reason": (
                "CPD names, offsets, sizes, flags, and hashes do not expose "
                "imports, calls, or inter-module dependency edges."
            ),
        },
        {
            "kind": "boot_order_and_entry_points",
            "status": "unknown",
            "reason": (
                "The inspected containers do not establish loader order, "
                "entry points, load addresses, or required initialization."
            ),
        },
        {
            "kind": "module_representation",
            "status": "unknown",
            "reason": (
                "No module contents were extracted or decompressed, so the "
                "presence of compression, encryption, or signatures is not "
                "resolved by this report."
            ),
        },
        {
            "kind": "undocumented_metadata_semantics",
            "status": "unknown",
            "reason": (
                "CPD flags, trailing words, manifest words, and range "
                "candidates are retained as bounded metadata without an "
                "undocumented semantic assignment."
            ),
        },
    ]

    if not ifd.get("descriptor"):
        unresolved.append({
            "kind": "descriptor_layout",
            "status": "unknown",
            "reason": "No complete Intel Flash Descriptor was identified.",
        })
    if not me.get("fpt"):
        unresolved.append({
            "kind": "fpt_partition_layout",
            "status": "unknown",
            "reason": "No bounded FPT partition table was identified.",
        })
    if not cpd.get("cpd"):
        unresolved.append({
            "kind": "cpd_module_directory",
            "status": "unknown",
            "reason": "No bounded FTPR CPD directory was identified.",
        })
    if not manifest.get("manifest_area"):
        unresolved.append({
            "kind": "cpd_manifest_metadata",
            "status": "unknown",
            "reason": "No bounded CPD manifest area was identified.",
        })
    if classification.get("unknown_entries"):
        unresolved.append({
            "kind": "unsafe_or_unknown_cpd_names",
            "status": "unknown",
            "reason": "One or more CPD entries did not have a safe name classification.",
        })

    return unresolved


def build_boot_dependency_report(path: Path | str) -> dict[str, Any]:
    """Return a JSON-serializable, read-only boot-dependency report.

    The four existing inspectors are the only source of parsed firmware
    structure.  Their warning text is retained so malformed or incomplete
    input remains visible instead of being silently treated as absent data.
    """

    image_path = Path(path)
    ifd = inspect_ifd(image_path)
    me = inspect_me(image_path)
    cpd = inspect_cpd(image_path)
    manifest = inspect_cpd_manifest(image_path)

    descriptor_regions = [
        _pick(region, _REGION_FIELDS)
        for region in ifd.get("regions", [])
        if isinstance(region, dict)
    ]
    fpt = me.get("fpt") or {}
    fpt_partitions = [
        _pick(partition, _PARTITION_FIELDS)
        for partition in fpt.get("partitions", [])
        if isinstance(partition, dict)
    ]
    cpd_area = cpd.get("cpd") or {}
    cpd_modules = [
        _pick(entry, _MODULE_FIELDS)
        for entry in cpd_area.get("entries", [])
        if isinstance(entry, dict)
    ]
    classification = _classify_modules(cpd_modules)

    warnings: list[str] = []
    for result in (ifd, me, cpd, manifest):
        for warning in result.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
    if cpd_area:
        for warning in cpd_area.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
    manifest_area = manifest.get("manifest_area")
    if manifest_area:
        for warning in manifest_area.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)

    unresolved = _unresolved_dependencies(
        ifd=ifd,
        me=me,
        cpd=cpd,
        manifest=manifest,
        classification=classification,
    )

    return {
        "report": "boot-dependency",
        "read_only": True,
        "source": {
            "path": str(image_path),
            "size": ifd.get("size", me.get("image_size")),
            "sha256": ifd.get("sha256", me.get("sha256")),
        },
        "descriptor": ifd.get("descriptor"),
        "descriptor_regions": descriptor_regions,
        "fpt": {
            "offset_in_me_region": fpt.get("offset_in_me_region"),
            "absolute_offset": fpt.get("absolute_offset"),
            "partition_count": fpt.get("partition_count"),
            "header_version": fpt.get("header_version"),
            "entry_version": fpt.get("entry_version"),
            "header_length": fpt.get("header_length"),
        } if fpt else None,
        "fpt_partitions": fpt_partitions,
        "cpd": {
            "ftpr_partition": cpd.get("ftpr_partition"),
            "signature": cpd_area.get("signature"),
            "signature_offset": cpd_area.get("signature_offset"),
            "directory_end": cpd_area.get("directory_end"),
            "entry_count": cpd_area.get("entry_count", len(cpd_modules)),
        } if cpd_area else None,
        "cpd_modules": cpd_modules,
        "cpd_manifest": _bounded_manifest(manifest_area),
        "classification": classification,
        "unresolved_dependencies": unresolved,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON metadata to this separate path instead of stdout",
    )
    args = parser.parse_args(argv)
    try:
        result = build_boot_dependency_report(args.image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            args.output.write_text(encoded, encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"error: cannot write report: {exc}", file=sys.stderr)
            return 2
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
