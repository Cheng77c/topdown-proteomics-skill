"""Backend port of the frontend's per-tool InputSpec derivation.

The canvas wires a child node's inputs in TypeScript
(``agent-chat-ui/.../lib/input-derivation.ts``): given a parent node's
output files and the child's tool, it picks which output becomes the
PRIMARY input, which parent outputs are auxiliary EXTERNAL inputs (e.g.
TopPIC's ``_ms2.feature``), and which EXTERNAL inputs the user must supply
(e.g. a FASTA database).

That logic only existed in the frontend, so the agent's ``create_draft``
(which passes ``input_specs=[]``) produced drafts that could never run on
their own — only the user, via the dialog, could wire them. This module
ports the same rules to Python so the agent can build runnable chains:
``submit_from_draft`` derives PRIMARY/parent-EXTERNAL inputs from the
parent's *actual* outputs at run time, while truly-external files (FASTA)
ride along on the node as EXTERNAL specs supplied by the caller.

Keep this in lockstep with ``input-derivation.ts`` — the pick rules must
match so a chain built by the agent runs identically to one built on the
canvas.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from topdown_agent.runtime.models import InputSpec, InputType, ToolName

# Filename patterns — mirror input-derivation.ts.
_MSALIGN_MS2 = re.compile(r"_ms2\.msalign$", re.IGNORECASE)
_MSALIGN = re.compile(r"\.msalign$", re.IGNORECASE)
_MZML = re.compile(r"\.(mzml|mzxml)$", re.IGNORECASE)
_PBF = re.compile(r"\.pbf$", re.IGNORECASE)
_RAW = re.compile(r"\.raw$", re.IGNORECASE)
_PIN = re.compile(r"\.pin$", re.IGNORECASE)
_FASTA = re.compile(r"\.(fasta|fa)$", re.IGNORECASE)
_PEPXML = re.compile(r"\.pepxml$", re.IGNORECASE)
_MS1FT = re.compile(r"\.ms1ft$", re.IGNORECASE)
_FEATURE_MS2 = re.compile(r"_ms2\.feature$", re.IGNORECASE)
_PSM = re.compile(r"(^|/)psm\.tsv$", re.IGNORECASE)


def _stem(path: str) -> str:
    return PurePosixPath(path).stem


def _pick(outs: list[str], pattern: re.Pattern[str],
          fallback: re.Pattern[str] | None = None) -> str | None:
    match = next((p for p in outs if pattern.search(p)), None)
    if match:
        return match
    if fallback is not None:
        return next((p for p in outs if fallback.search(p)), None)
    return None


def _pick_from_ancestors(
    ancestors: list[tuple[str, list[str]]], pattern: re.Pattern[str],
) -> tuple[str, str] | None:
    """Walk (node_id, outputs) pairs nearest-first for the first match.

    Returns ``(path, source_node_id)`` or None.
    """
    for node_id, outs in ancestors:
        hit = next((p for p in outs if pattern.search(p)), None)
        if hit:
            return hit, node_id
    return None


def _single(path: str, parent_id: str) -> list[InputSpec]:
    return [InputSpec(
        path=path, input_type=InputType.PRIMARY, name="input_0",
        source_node_id=parent_id,
    )]


def derive_inputs(
    parent_node_id: str,
    parent_outputs: list[str],
    tool: ToolName,
    extras: dict[str, str] | None = None,
    ancestors: list[tuple[str, list[str]]] | None = None,
) -> tuple[list[InputSpec], list[str]]:
    """Derive InputSpecs for a (parent, tool) pair.

    ``extras`` maps an external-input key (``fasta`` / ``feature`` /
    ``ms1ft``) to a caller-supplied path for inputs that cannot come from
    the parent's outputs. ``ancestors`` is a nearest-first list of
    ``(node_id, output_files)`` for tools whose primary input lives more
    than one step up the chain (mspathfindert).

    Returns ``(specs, missing_keys)``. ``missing_keys`` lists external
    inputs the tool needs that weren't supplied — a non-empty list means
    the node can't run yet.
    """
    extras = extras or {}
    ancestors = ancestors or []
    outs = list(parent_outputs or [])
    pid = parent_node_id

    if tool == "msconvert":
        raw = _pick(outs, _RAW, _MZML)
        if raw:
            return _single(raw, pid), []
        return [], ["feature"]

    if tool in ("topfd", "flashdeconv"):
        mz = _pick(outs, _MZML)
        if mz:
            return _single(mz, pid), []
        return [], ["feature"]

    if tool == "pbfgen":
        src = _pick(outs, _RAW, _MZML)
        if src:
            return _single(src, pid), []
        return [], ["feature"]

    if tool == "promex":
        pbf = _pick(outs, _PBF, _MZML)
        if pbf:
            return _single(pbf, pid), []
        return [], ["feature"]

    if tool == "mspathfindert":
        pbf_direct = _pick(outs, _PBF)
        ms1ft_direct = _pick(outs, _MS1FT)
        pbf_anc = None if pbf_direct else _pick_from_ancestors(ancestors, _PBF)
        ms1ft_anc = None if ms1ft_direct else _pick_from_ancestors(ancestors, _MS1FT)
        pbf = pbf_direct or (pbf_anc[0] if pbf_anc else None)
        ms1ft = ms1ft_direct or (ms1ft_anc[0] if ms1ft_anc else None)
        pbf_src = pid if pbf_direct else (pbf_anc[1] if pbf_anc else None)
        ms1ft_src = pid if ms1ft_direct else (ms1ft_anc[1] if ms1ft_anc else None)

        missing: list[str] = []
        if not pbf:
            missing.append("feature")
        if not ms1ft:
            missing.append("ms1ft")
        if not extras.get("fasta"):
            missing.append("fasta")

        specs: list[InputSpec] = []
        if pbf:
            specs.append(InputSpec(
                path=pbf, input_type=InputType.PRIMARY, name="spectrum",
                source_node_id=pbf_src,
            ))
        if extras.get("fasta"):
            specs.append(InputSpec(
                path=extras["fasta"], input_type=InputType.EXTERNAL,
                name="fasta", source_node_id=None,
            ))
        if ms1ft:
            specs.append(InputSpec(
                path=ms1ft, input_type=InputType.EXTERNAL, name="feature",
                source_node_id=ms1ft_src,
            ))
        return specs, missing

    if tool == "toppic":
        msalign = _pick(outs, _MSALIGN_MS2, _MSALIGN)
        missing = []
        if not msalign:
            missing.append("feature")
        if not extras.get("fasta"):
            missing.append("fasta")
        specs = []
        if msalign:
            specs.append(InputSpec(
                path=msalign, input_type=InputType.PRIMARY, name="msalign",
                source_node_id=pid,
            ))
        if extras.get("fasta"):
            specs.append(InputSpec(
                path=extras["fasta"], input_type=InputType.EXTERNAL,
                name="fasta", source_node_id=None,
            ))
        # TopPIC derives the feature filename from the msalign stem, so we
        # stage the parent's _ms2.feature into toppic's output_dir under
        # `<stem>.feature` (mirrors the agent's submit_pipeline wiring).
        feature = _pick(outs, _FEATURE_MS2)
        if msalign and feature:
            specs.append(InputSpec(
                path=feature, input_type=InputType.EXTERNAL, name="feature",
                source_node_id=pid, staged_as=f"{_stem(msalign)}.feature",
            ))
        return specs, missing

    if tool == "philosopher-report":
        pep = _pick(outs, _PEPXML)
        if pep:
            return _single(pep, pid), []
        return [], ["feature"]

    if tool == "philosopher-database":
        fasta = _pick(outs, _FASTA)
        if fasta:
            return _single(fasta, pid), []
        return [], ["feature"]

    if tool == "percolator":
        pin = _pick(outs, _PIN)
        if pin:
            return _single(pin, pid), []
        return [], ["feature"]

    if tool == "msfragger-closed":
        mz = _pick(outs, _MZML)
        if mz:
            return _single(mz, pid), []
        return [], ["feature"]

    # Unknown tool: first parent output as the single primary (mirrors the
    # TS fallback; backend tool validation catches a bad shape).
    if outs:
        return [InputSpec(
            path=outs[0], input_type=InputType.PRIMARY, name="input_0",
            source_node_id=pid,
        )], []
    return [], []


def has_primary(inputs: list[InputSpec]) -> bool:
    return any(s.input_type == InputType.PRIMARY for s in inputs)


def extras_from_inputs(inputs: list[InputSpec]) -> dict[str, str]:
    """Pull caller-supplied EXTERNAL inputs (e.g. FASTA) into the extras map
    keyed by spec name, so they survive re-derivation at submit time."""
    extras: dict[str, str] = {}
    for s in inputs:
        if s.input_type == InputType.EXTERNAL and s.name and s.path:
            extras[s.name] = s.path
    return extras


__all__ = ["derive_inputs", "has_primary", "extras_from_inputs"]
