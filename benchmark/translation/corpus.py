"""Download, parse, freeze, and validate the translation corpus."""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from benchlib import (
    BenchmarkError,
    apply_reviews,
    collapse_whitespace,
    comparison_text,
    expand_tracks,
    fingerprint,
    has_japanese,
    length_bucket,
    select_entries,
    sha256_file,
    validate_reviews,
    validate_source_registry,
    write_json,
)

_PS_ALLOWED_TAG_RE = re.compile(r"<(?:line|wait(?: more)?|end|delay)>", re.IGNORECASE)
_PS_ANY_TAG_RE = re.compile(r"<[^>]+>")
_METAL_CODE_RE = re.compile(r"\(CODE [^)]+\)", re.IGNORECASE)
_METAL_LINE_WIDTH_RE = re.compile(r"\\LineWidth(?:=\d+|PortraitShowing)/", re.IGNORECASE)
_METAL_LAYOUT_RE = re.compile(
    r"\((?:LINE|STOP|WAIT|PAUSE|DELAY|End quote|Start quote)[^)]*\)",
    re.IGNORECASE,
)
_METAL_HEX_RE = re.compile(r"\{[0-9A-Fa-f]{2}\}")
_METAL_VISIBLE_BRACKET_RE = re.compile(r"\[([！？!?…]+)\]")
_METAL_OTHER_BRACKET_RE = re.compile(r"\[[^]]+\]")
_METAL_OTHER_CONTROL_RE = re.compile(r"\([^)]*\)")
_BOX_DRAWING_RE = re.compile(r"[\u2500-\u257f]")
_MENU_METADATA_RE = re.compile(r"\b(?:option|choice|menu|select)\b", re.IGNORECASE)
_DS6_CONTROL_RE = re.compile(r"<[^>]+>")
_DS6_LAYOUT_RE = re.compile(r"X{2,}")
_DS6_ALLOWED_CONTROL_RE = re.compile(
    r"(?:X(?:1e|04|0a|08)|RET_IL|RETN|CH[0-9A-Fa-f]+|END|WAIT|PAGE|P|N)",
    re.IGNORECASE,
)


def _source_path(data_dir: Path, source_id: str, role: str, remote_path: str) -> Path:
    safe_name = Path(remote_path).name
    return data_dir / "sources" / source_id / f"{role}-{safe_name}"


def _download(url: str, destination: Path, expected_sha256: str) -> dict[str, Any]:
    if destination.is_file():
        actual = sha256_file(destination)
        if actual == expected_sha256:
            return {"sha256": actual, "bytes": destination.stat().st_size}
        raise BenchmarkError(
            f"Existing source has the wrong hash: {destination}. Remove that one file and run prepare again."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "interpreter-translation-benchmark/1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        if temporary.exists():
            temporary.unlink()
        raise BenchmarkError(f"Could not download {url}: {exc}") from exc

    actual = sha256_file(temporary)
    if actual != expected_sha256:
        temporary.unlink()
        raise BenchmarkError(f"Downloaded source hash mismatch for {url}: expected {expected_sha256}, got {actual}")
    temporary.replace(destination)
    return {"sha256": actual, "bytes": destination.stat().st_size}


def _clean_reference(text: str | None) -> str:
    return collapse_whitespace(text)


def _clean_nintendo(text: str | None) -> str:
    # The source projects' game writers explicitly discard U+FF5C. It marks a
    # layout boundary in the dump and is never drawn as a player-visible glyph.
    return collapse_whitespace((text or "").replace("｜", " "))


def _clean_phantasy(text: str | None, *, menu: bool = False) -> str:
    if not text:
        return ""
    without_layout = _PS_ALLOWED_TAG_RE.sub(" ", text).replace("~", " ")
    # Runtime substitutions such as <player>, <item>, and <number> are not
    # recoverable from a static script and therefore are not valid screenshots.
    if _PS_ANY_TAG_RE.search(without_layout):
        return ""
    if menu:
        without_layout = _BOX_DRAWING_RE.sub(" ", without_layout)
        without_layout = without_layout.replace("------", " ")
    return collapse_whitespace(without_layout)


def _clean_metal(text: str | None) -> str:
    value = text or ""
    value = _METAL_LINE_WIDTH_RE.sub(" ", value)
    value = _METAL_CODE_RE.sub(" ", value)
    value = _METAL_LAYOUT_RE.sub(" ", value)
    value = _METAL_HEX_RE.sub(" ", value)
    value = _METAL_VISIBLE_BRACKET_RE.sub(r"\1", value)
    value = _METAL_OTHER_BRACKET_RE.sub(" ", value)
    value = _METAL_OTHER_CONTROL_RE.sub(" ", value)
    return collapse_whitespace(value)


def _clean_ds6(text: str | None) -> str:
    value = _DS6_CONTROL_RE.sub(" ", text or "")
    value = _DS6_LAYOUT_RE.sub(" ", value)
    return collapse_whitespace(value)


def _valid_ds6_record(screen_raw: str, reference_raw: str, screen: str, reference: str) -> bool:
    # The script interleaves text with branches, subroutine calls, and runtime
    # substitutions. Only retain linear records whose controls are known to be
    # layout/speaker markers; otherwise the static text is not what OCR sees.
    controls = [
        match.group(0)[1:-1] for value in (screen_raw, reference_raw) for match in _DS6_CONTROL_RE.finditer(value)
    ]
    if any(not _DS6_ALLOWED_CONTROL_RE.fullmatch(control) for control in controls):
        return False
    if has_japanese(reference) or not re.search(r"[A-Za-z]", reference):
        return False
    if re.search(r"\b(?:TODO|TBD|UNTRANSLATED)\b", reference, re.IGNORECASE):
        return False
    # One combat bank contains an internal numbered-file diagnostic. It is
    # translated in the repository, but is test content rather than game text.
    if "ファイル" in screen and re.search(r"[ＭM][ー－−-][０-９0-9]+", screen):
        return False
    if re.search(r"\bthis file is\s+M-\d+\b", reference, re.IGNORECASE):
        return False
    # Some combat rows rely on the engine prepending an actor name without an
    # explicit control code in the CSV. A leading standalone particle exposes
    # the otherwise-invisible substitution and makes the row context-incomplete.
    if re.match(r"^(?:は|が|を|に|へ|と|の|も)\s", screen):
        return False
    return len(reference) <= max(40, len(screen) * 6)


def _references(*values: str) -> list[str]:
    output = []
    seen = set()
    for value in values:
        cleaned = _clean_reference(value)
        normalized = comparison_text(cleaned)
        if cleaned and normalized not in seen:
            seen.add(normalized)
            output.append(cleaned)
    return output


def _entry(
    source: dict[str, Any],
    source_index: str,
    text_type: str,
    screen: str,
    normalized: str,
    references: list[str],
    registry: dict[str, Any],
    source_file_roles: list[str],
) -> dict[str, Any] | None:
    screen = collapse_whitespace(screen)
    normalized = collapse_whitespace(normalized)
    references = _references(*references)
    maximum = registry["maximum_source_characters"]
    if not screen or not has_japanese(screen) or not references:
        return None
    if len(screen.replace(" ", "")) > maximum:
        return None
    if any(comparison_text(screen) == comparison_text(reference) for reference in references):
        return None
    bucket = length_bucket(screen, registry["length_buckets"])
    return {
        "pair_id": f"{source['id']}:{source_index}",
        "source_id": source["id"],
        "source_index": source_index,
        "game": source["game"],
        "platform": source["platform"],
        "release_year": source["release_year"],
        "genre": source["genre"],
        "text_type": text_type,
        "length_bucket": bucket,
        "screen": screen,
        "normalized": normalized or None,
        "references": references,
        "reference_status": source["reference_status"],
        "provenance": {
            "repository": source["repository"],
            "commit": source["commit"],
            "page_url": source["provenance_url"],
            "file_roles": source_file_roles,
            "license": source["license"],
        },
    }


def _parse_nintendo_messages(
    source: dict[str, Any], path: Path, registry: dict[str, Any], *, fixed: bool
) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    blocks: list[tuple[list[str], list[str], list[str]]] = []
    if fixed:
        if len(lines) % 12:
            raise BenchmarkError(f"{path} no longer consists of 12-line message records")
        for start in range(0, len(lines), 12):
            block = lines[start : start + 12]
            blocks.append((block[:4], block[4:8], block[8:12]))
    else:
        index = 0
        while index < len(lines):
            header = lines[index].split()
            if not header or not header[0].isdigit():
                raise BenchmarkError(f"Malformed variable message header in {path} at line {index + 1}")
            count = int(header[0])
            index += 1
            block = lines[index : index + count * 3]
            if len(block) != count * 3:
                raise BenchmarkError(f"Truncated variable message record in {path} at line {index + 1}")
            blocks.append((block[:count], block[count : count * 2], block[count * 2 :]))
            index += count * 3

    output = []
    for index, (screen, normalized, reference) in enumerate(blocks):
        parsed = _entry(
            source,
            f"message-{index:06d}",
            "dialogue",
            _clean_nintendo("\n".join(screen)),
            _clean_nintendo("\n".join(normalized)),
            [_clean_nintendo("\n".join(reference))],
            registry,
            ["messages"],
        )
        if parsed:
            output.append(parsed)
    return output


def _parse_nintendo_options(source: dict[str, Any], path: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) % 2:
        raise BenchmarkError(f"{path} no longer consists of alternating Japanese/English option records")
    output = []
    for index in range(0, len(lines), 2):
        parsed = _entry(
            source,
            f"option-{index // 2:06d}",
            "menu",
            _clean_nintendo(lines[index]),
            "",
            [_clean_nintendo(lines[index + 1])],
            registry,
            ["options"],
        )
        if parsed:
            output.append(parsed)
    return output


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise BenchmarkError(
            "Preparing the Phantasy Star corpus requires PyYAML (already an Interpreter dependency)"
        ) from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise BenchmarkError(f"Invalid YAML source {path}: {exc}") from exc


def _parse_phantasy_star(
    source: dict[str, Any], paths: dict[str, Path], registry: dict[str, Any]
) -> list[dict[str, Any]]:
    output = []
    messages = _load_yaml(paths["messages"])
    if not isinstance(messages, list):
        raise BenchmarkError(f"Expected a YAML list in {paths['messages']}")
    for index, value in enumerate(messages):
        if not isinstance(value, dict):
            continue
        screen = _clean_phantasy(value.get("ja"))
        normalized = _clean_phantasy(value.get("kanji"))
        references = [_clean_phantasy(value.get("literal")), _clean_phantasy(value.get("us"))]
        parsed = _entry(
            source,
            f"message-{index:06d}",
            "dialogue",
            screen,
            normalized,
            references,
            registry,
            ["messages"],
        )
        if parsed:
            output.append(parsed)

    menus = _load_yaml(paths["options"])
    if not isinstance(menus, list):
        raise BenchmarkError(f"Expected a YAML list in {paths['options']}")
    for index, value in enumerate(menus):
        if not isinstance(value, dict):
            continue
        screen = _clean_phantasy(value.get("jp"), menu=True)
        normalized = _clean_phantasy(value.get("kanji"), menu=True)
        references = [
            _clean_phantasy(value.get("literal"), menu=True),
            _clean_phantasy(value.get("us"), menu=True),
        ]
        parsed = _entry(
            source,
            f"menu-{index:06d}",
            "menu",
            screen,
            normalized,
            references,
            registry,
            ["options"],
        )
        if parsed:
            output.append(parsed)
    return output


def _walk_metal(value: Any, path: str = ""):
    if isinstance(value, dict):
        if "Original" in value and "New" in value:
            yield path, value
        else:
            for key, child in value.items():
                yield from _walk_metal(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_metal(child, f"{path}/{index}")


def _parse_metal_slader(source: dict[str, Any], path: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        dialogue = value["indexTable"]["Dialogue"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BenchmarkError(f"Metal Slader source structure changed in {path}") from exc

    output = []
    for index, (json_path, text) in enumerate(_walk_metal(dialogue)):
        screen = _clean_metal(text.get("Original"))
        reference = _clean_metal(text.get("New"))
        metadata = collapse_whitespace(text.get("Menu"))
        # Debug labels describe sound effects, room transitions, portrait tests,
        # and other development metadata; they are not player-visible text.
        if re.search(r"\bdebug\b", metadata, re.IGNORECASE):
            continue
        text_type = "menu" if _MENU_METADATA_RE.search(metadata) else "dialogue"
        parsed = _entry(
            source,
            f"dialogue-{index:06d}",
            text_type,
            screen,
            "",
            [reference],
            registry,
            ["messages"],
        )
        if parsed:
            parsed["provenance"]["record_path"] = json_path
            parsed["provenance"]["record_category"] = metadata
            output.append(parsed)
    return output


def _parse_ds6(source: dict[str, Any], path: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BenchmarkError(f"Dragon Slayer source is not a valid ZIP archive: {path}") from exc

    members = sorted(
        name
        for name in archive.namelist()
        if "/csv/" in name and name.casefold().endswith(".csv") and not name.endswith("/")
    )
    if not members:
        raise BenchmarkError(f"Dragon Slayer archive contains no csv/*.csv files: {path}")

    output = []
    with archive:
        for member in members:
            relative = member.split("/csv/", 1)[1]
            if relative.startswith("Scenarios/") or relative in {"Opening.csv", "Ending.csv"}:
                text_type = "dialogue"
            elif relative.startswith("Combats/"):
                text_type = "system"
            elif relative in {"Items.csv", "Locations.csv", "Spells.csv"}:
                text_type = "menu"
            else:
                continue
            try:
                rows = csv.reader(io.StringIO(archive.read(member).decode("utf-8-sig")))
                for row_index, row in enumerate(rows):
                    if len(row) != 3 or row[0] == "*":
                        continue
                    screen = _clean_ds6(row[1])
                    reference = _clean_ds6(row[2])
                    if not _valid_ds6_record(row[1], row[2], screen, reference):
                        continue
                    stem = Path(relative).stem.replace(".", "-")
                    parsed = _entry(
                        source,
                        f"{text_type}-{stem}-{row_index:04d}",
                        text_type,
                        screen,
                        "",
                        [reference],
                        registry,
                        ["archive"],
                    )
                    if parsed:
                        parsed["provenance"]["record_path"] = relative
                        parsed["provenance"]["record_id"] = row[0]
                        output.append(parsed)
            except (UnicodeDecodeError, csv.Error) as exc:
                raise BenchmarkError(f"Could not parse {member} in {path}: {exc}") from exc
    return output


def _deduplicate_context_free(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate and ambiguous labels within one game/source.

    Interpreter currently translates one capture without dialogue history. If
    identical visible Japanese has conflicting references inside a game, there
    is no context-free gold answer and all occurrences are excluded.
    """

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        groups[(entry["source_id"], comparison_text(entry["screen"]))].append(entry)

    output = []
    for group in groups.values():
        reference_sets = {tuple(comparison_text(value) for value in entry["references"]) for entry in group}
        if len(reference_sets) > 1:
            continue
        output.append(min(group, key=lambda item: item["pair_id"]))
    return sorted(output, key=lambda item: item["pair_id"])


def prepare_corpus(
    registry: dict[str, Any],
    reviews: dict[str, Any],
    data_dir: Path,
    registry_path: Path,
    reviews_path: Path,
) -> dict[str, Any]:
    errors = [*validate_source_registry(registry), *validate_reviews(reviews)]
    if errors:
        raise BenchmarkError("Corpus configuration is invalid:\n- " + "\n- ".join(errors))

    source_files: dict[str, Any] = {}
    parsed_entries = []
    for source in registry["sources"]:
        print(f"preparing {source['game']}")
        paths: dict[str, Path] = {}
        metadata_by_role = {}
        for role, metadata in source["files"].items():
            destination = _source_path(data_dir, source["id"], role, metadata["path"])
            local = _download(metadata["url"], destination, metadata["sha256"])
            paths[role] = destination
            metadata_by_role[role] = {
                "path": destination.relative_to(data_dir).as_posix(),
                "url": metadata["url"],
                **local,
            }
        source_files[source["id"]] = metadata_by_role

        parser = source["parser"]
        if parser in {"nintendo_fixed", "nintendo_variable"}:
            parsed_entries.extend(
                _parse_nintendo_messages(source, paths["messages"], registry, fixed=parser == "nintendo_fixed")
            )
            if "options" in paths:
                parsed_entries.extend(_parse_nintendo_options(source, paths["options"], registry))
        elif parser == "phantasy_star":
            parsed_entries.extend(_parse_phantasy_star(source, paths, registry))
        elif parser == "metal_slader":
            parsed_entries.extend(_parse_metal_slader(source, paths["messages"], registry))
        elif parser == "ds6_pc98":
            parsed_entries.extend(_parse_ds6(source, paths["archive"], registry))
        else:
            raise BenchmarkError(f"Unknown corpus parser: {parser}")

    eligible = _deduplicate_context_free(parsed_entries)
    eligible = apply_reviews(eligible, reviews)
    selected = select_entries(eligible, registry)
    samples = expand_tracks(selected)

    lock = {
        "schema_version": 1,
        "corpus_id": registry["corpus_id"],
        "source_registry": registry_path.name,
        "source_registry_sha256": fingerprint(registry),
        "reviews": reviews_path.name,
        "reviews_sha256": fingerprint(reviews),
        "sampling_seed": registry["sampling_seed"],
        "length_buckets": registry["length_buckets"],
        "maximum_source_characters": registry["maximum_source_characters"],
        "source_files": source_files,
        "eligible_pairs": len(eligible),
        "pairs": selected,
        "samples": samples,
    }
    errors = validate_lock(lock, data_dir, check_files=True)
    if errors:
        raise BenchmarkError("Generated corpus lock is invalid:\n- " + "\n- ".join(errors))
    write_json(data_dir / "corpus.lock.json", lock)
    return lock


def validate_lock(lock: dict[str, Any], data_dir: Path, *, check_files: bool) -> list[str]:
    errors: list[str] = []
    if lock.get("schema_version") != 1:
        errors.append("lock schema_version must be 1")
    pairs = lock.get("pairs")
    samples = lock.get("samples")
    if not isinstance(pairs, list) or not pairs:
        errors.append("lock pairs must be a non-empty list")
    if not isinstance(samples, list) or not samples:
        errors.append("lock samples must be a non-empty list")
        return errors

    ids = [sample.get("id") for sample in samples if isinstance(sample, dict)]
    duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate sample IDs: {', '.join(duplicates)}")
    for index, sample in enumerate(samples):
        prefix = f"samples[{index}]"
        if not isinstance(sample, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("id", "pair_id", "source_id", "game", "source", "track", "text_type", "length_bucket"):
            if not isinstance(sample.get(field), str) or not sample[field]:
                errors.append(f"{prefix}.{field} must be a non-empty string")
        if sample.get("track") not in {"screen", "normalized"}:
            errors.append(f"{prefix}.track is invalid")
        if not has_japanese(sample.get("source")):
            errors.append(f"{prefix}.source has no Japanese text")
        references = sample.get("references")
        if not isinstance(references, list) or not references or not all(isinstance(x, str) and x for x in references):
            errors.append(f"{prefix}.references must be a non-empty string list")

    source_files = lock.get("source_files")
    if not isinstance(source_files, dict):
        errors.append("lock source_files must be an object")
    elif check_files:
        for source_id, roles in source_files.items():
            if not isinstance(roles, dict):
                errors.append(f"source_files.{source_id} must be an object")
                continue
            for role, metadata in roles.items():
                path = data_dir / metadata.get("path", "")
                if not path.is_file():
                    errors.append(f"missing source file: {path}")
                elif sha256_file(path) != metadata.get("sha256"):
                    errors.append(f"source file hash changed: {source_id}/{role}")
    return errors


def load_and_validate_lock(
    lock_path: Path,
    data_dir: Path,
    registry: dict[str, Any],
    reviews: dict[str, Any],
) -> dict[str, Any]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkError(f"Corpus lock not found: {lock_path}. Run prepare first.") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"Invalid corpus lock {lock_path}: {exc}") from exc
    if lock.get("source_registry_sha256") != fingerprint(registry):
        raise BenchmarkError("Corpus lock does not match sources.json; run prepare again")
    if lock.get("reviews_sha256") != fingerprint(reviews):
        raise BenchmarkError("Corpus lock does not match reviews.json; run prepare again")
    errors = validate_lock(lock, data_dir, check_files=True)
    if errors:
        raise BenchmarkError("Corpus lock validation failed:\n- " + "\n- ".join(errors))
    return lock


def inventory(lock: dict[str, Any]) -> dict[str, Any]:
    pairs = lock["pairs"]
    samples = lock["samples"]
    return {
        "eligible_pairs": lock["eligible_pairs"],
        "selected_pairs": len(pairs),
        "samples": len(samples),
        "verified_pairs": sum(bool(pair["independently_verified"]) for pair in pairs),
        "games": dict(sorted(Counter(pair["game"] for pair in pairs).items())),
        "platforms": dict(sorted(Counter(pair["platform"] for pair in pairs).items())),
        "text_types": dict(sorted(Counter(pair["text_type"] for pair in pairs).items())),
        "length_buckets": dict(sorted(Counter(pair["length_bucket"] for pair in pairs).items())),
        "tracks": dict(sorted(Counter(sample["track"] for sample in samples).items())),
    }
