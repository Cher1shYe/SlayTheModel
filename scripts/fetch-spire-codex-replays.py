#!/usr/bin/env python3
"""Download public Spire Codex replays and group one recorder version.

The public browse endpoint does not expose mod_version. Its reported total may
also be a lower bound, so enumeration stops only at an empty page. All state is
kept under --output, allowing an interrupted run to resume without redownloading
completed files. Grouped files are hard links to the raw downloads.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


BASE_URL = "https://spire-codex.com"
CHARACTERS = ("IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT")
HASH_RE = re.compile(r"^[0-9a-f]{16}$")
PRINT_LOCK = threading.Lock()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, data: object) -> None:
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode())


def get(url: str, *, attempts: int = 6, decode_gzip: bool = True, accept_encoding: str = "gzip") -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SlayTheModel-replay-archive/1.0", "Accept-Encoding": accept_encoding})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
                return gzip.decompress(data) if decode_gzip and data[:2] == b"\x1f\x8b" else data
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 410):
                raise
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            delay = min(90.0, max(2.0 ** attempt, float(exc.headers.get("Retry-After", "0") or 0)))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
            delay = min(45.0, 2.0 ** attempt)
        time.sleep(delay)
    raise AssertionError("retry loop exhausted")


def index_replays(output: Path, *, page_limit: int | None = None) -> dict[str, dict]:
    page_dir = output / "index-pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    page = 1
    while True:
        page_path = page_dir / f"{page:05d}.json"
        if page_path.exists():
            cached = json.loads(page_path.read_text())
        else:
            query = urllib.parse.urlencode({"page": page, "limit": 100})
            result = json.loads(get(f"{BASE_URL}/api/replays?{query}"))
            if not isinstance(result.get("runs"), list):
                raise ValueError(f"page {page}: missing runs list")
            cached = {
                "page": page,
                "fetched_at": time.time(),
                "runs": [
                    {key: run.get(key) for key in ("run_hash", "character", "build_id", "submitted_at")}
                    for run in result["runs"]
                ],
            }
            atomic_json(page_path, cached)
            if page == 1 or page % 10 == 0 or not cached["runs"]:
                print(f"indexed page={page} rows={len(cached['runs'])}", flush=True)
        if not cached["runs"]:
            break
        if page_limit is not None and page >= page_limit:
            break
        page += 1

    catalog: dict[str, dict] = {}
    for page_path in sorted(page_dir.glob("[0-9][0-9][0-9][0-9][0-9].json")):
        for run in json.loads(page_path.read_text())["runs"]:
            run_hash = run.get("run_hash")
            if isinstance(run_hash, str) and HASH_RE.fullmatch(run_hash):
                catalog.setdefault(run_hash, run)
    atomic_bytes(
        output / "catalog.jsonl",
        b"".join((json.dumps(run, ensure_ascii=False, sort_keys=True) + "\n").encode() for run in catalog.values()),
    )
    return catalog


def read_catalog(output: Path) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    with (output / "catalog.jsonl").open() as handle:
        for line in handle:
            run = json.loads(line)
            run_hash = run["run_hash"]
            if HASH_RE.fullmatch(run_hash):
                catalog[run_hash] = run
    return catalog


def inspect_replay(data: bytes) -> dict:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if not data.endswith(b"\n"):
        raise ValueError("replay has no final newline")
    lines = data.splitlines()
    if len(lines) < 2:
        raise ValueError("replay has fewer than two events")
    header = json.loads(lines[0])
    if header.get("t") != "header":
        raise ValueError("first event is not header")
    last = json.loads(lines[-1])
    if last.get("t") != "end":
        raise ValueError("last event is not end")
    for line in lines[1:-1]:
        json.loads(line)
    return {
        "mod_version": header.get("mod_version"),
        "replay_version": header.get("replay_version"),
        "build_id": header.get("build_id"),
        "character": header.get("character"),
        "capture_status": last.get("capture_status"),
        "events": len(lines),
        "bytes": len(data),
    }


class RateLimiter:
    def __init__(self, per_minute: float):
        self.interval = 60.0 / per_minute
        self.next_time = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.next_time)
            self.next_time = scheduled + self.interval
        time.sleep(max(0.0, scheduled - now))


def fetch_one(output: Path, run_hash: str, listing: dict, version: str, limiter: RateLimiter) -> dict:
    plain_path = output / "raw" / f"{run_hash}.ndjson"
    gzip_path = output / "raw" / f"{run_hash}.ndjson.gz"
    raw_path = plain_path if plain_path.exists() else gzip_path
    meta_path = output / "meta" / f"{run_hash}.json"
    if meta_path.exists() and raw_path.exists():
        metadata = json.loads(meta_path.read_text())
        group_replay(output, raw_path, metadata, version)
        return metadata
    if raw_path.exists():
        data = raw_path.read_bytes()
    else:
        limiter.wait()
        data = get(f"{BASE_URL}/api/runs/{run_hash}/replay", decode_gzip=False)
    try:
        metadata = inspect_replay(data)
    except Exception as original_error:
        if not raw_path.exists():
            try:
                fallback = get(
                    f"{BASE_URL}/api/runs/{run_hash}/replay",
                    attempts=2,
                    decode_gzip=False,
                    accept_encoding="identity",
                )
                metadata = inspect_replay(fallback)
                data = fallback
            except Exception:
                suffix = ".ndjson.gz" if data[:2] == b"\x1f\x8b" else ".bin"
                atomic_bytes(output / "quarantine" / f"{run_hash}{suffix}", data)
                raise original_error
        else:
            raise
    metadata["run_hash"] = run_hash
    metadata["listed_character"] = listing.get("character")
    metadata["submitted_at"] = listing.get("submitted_at")
    metadata["archive_file"] = raw_path.name
    if metadata["character"] != listing.get("character"):
        metadata["character_mismatch"] = True
    if not raw_path.exists():
        atomic_bytes(raw_path, data if data[:2] == b"\x1f\x8b" else gzip.compress(data))
    atomic_json(meta_path, metadata)
    group_replay(output, raw_path, metadata, version)
    return metadata


def group_replay(output: Path, raw_path: Path, metadata: dict, version: str) -> None:
    if metadata["mod_version"] == version:
        character = metadata["character"]
        group = character if character in CHARACTERS else "OTHER"
        grouped = output / version / group / raw_path.name
        grouped.parent.mkdir(parents=True, exist_ok=True)
        if not grouped.exists():
            os.link(raw_path, grouped)


def quarantined_header(output: Path, run_hash: str) -> dict | None:
    for suffix in (".ndjson.gz", ".bin"):
        path = output / "quarantine" / f"{run_hash}{suffix}"
        if not path.exists():
            continue
        try:
            data = path.read_bytes()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            header = json.loads(data.splitlines()[0])
            if header.get("t") == "header":
                return {key: header.get(key) for key in ("mod_version", "replay_version", "build_id", "character")}
        except Exception:
            pass
    return None


def download_replays(output: Path, catalog: dict[str, dict], *, version: str, workers: int, per_minute: float, max_files: int | None, retry_errors_only: bool = False) -> None:
    limiter = RateLimiter(per_minute)
    entries = list(catalog.items())
    if retry_errors_only:
        progress = output / "progress.json"
        failed = json.loads(progress.read_text()).get("errors", {}) if progress.exists() else {}
        entries = [(run_hash, listing) for run_hash, listing in entries if run_hash in failed]
    if max_files is not None:
        entries = entries[:max_files]
    errors: dict[str, str] = {}
    results = Counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(fetch_one, output, run_hash, listing, version, limiter): run_hash for run_hash, listing in entries}
        for index, future in enumerate(concurrent.futures.as_completed(pending), 1):
            run_hash = pending[future]
            try:
                metadata = future.result()
                results[metadata.get("mod_version") or "UNKNOWN"] += 1
            except Exception as exc:
                errors[run_hash] = f"{type(exc).__name__}: {exc}"
            if index % 100 == 0 or index == len(entries):
                with PRINT_LOCK:
                    print(f"downloaded_or_cached={index}/{len(entries)} selected={results[version]} errors={len(errors)}", flush=True)
                atomic_json(output / "progress.json", {"processed": index, "work_items": len(entries), "catalog_size": len(catalog), "mode": "retry" if retry_errors_only else "download", "versions": dict(results), "errors": errors})
    finalize(output, catalog, version, errors)


def finalize(output: Path, catalog: dict[str, dict], version: str, errors: dict[str, str] | None = None) -> None:
    errors = errors or {}
    rows = []
    counts = Counter()
    capture_statuses = Counter()
    versions = Counter()
    verification_issues: dict[str, str] = {}
    for run_hash in catalog:
        meta_path = output / "meta" / f"{run_hash}.json"
        if not meta_path.exists():
            continue
        metadata = json.loads(meta_path.read_text())
        rows.append(metadata)
        archive_file = metadata.get("archive_file") or f"{run_hash}.ndjson"
        raw_path = output / "raw" / archive_file
        if not raw_path.is_file():
            verification_issues[run_hash] = "raw file missing"
        versions[metadata.get("mod_version") or "UNKNOWN"] += 1
        if metadata.get("mod_version") == version:
            character = metadata.get("character")
            group = character if character in CHARACTERS else "OTHER"
            counts[group] += 1
            capture_statuses[metadata.get("capture_status") or "UNKNOWN"] += 1
            grouped = output / version / group / archive_file
            if not grouped.is_file() or (raw_path.is_file() and not os.path.samefile(raw_path, grouped)):
                verification_issues[run_hash] = "group hard link missing or different"
    selected_path = output / version / "manifest.jsonl"
    atomic_bytes(
        selected_path,
        b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode() for row in rows if row.get("mod_version") == version),
    )
    atomic_bytes(
        output / "unavailable.jsonl",
        b"".join(
            (json.dumps({"run_hash": run_hash, "error": error, "listing": catalog[run_hash], "quarantined_header": quarantined_header(output, run_hash)}, ensure_ascii=False, sort_keys=True) + "\n").encode()
            for run_hash, error in sorted(errors.items())
            if run_hash in catalog
        ),
    )
    atomic_json(output / "summary.json", {
        "catalog_size": len(catalog),
        "downloaded": len(rows),
        "target_mod_version": version,
        "versions": dict(versions),
        "selected_by_character": dict(counts),
        "selected_capture_statuses": dict(capture_statuses),
        "verification_issues": verification_issues,
        "errors": errors,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/reference/spire-codex/bulk"))
    parser.add_argument("--version", default="v1.2.1")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--per-minute", type=float, default=90)
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--retry-errors-only", action="store_true", help="Retry hashes listed in progress.json without scanning all completed files")
    parser.add_argument("--page-limit", type=int, help="Only for a small index smoke test")
    parser.add_argument("--max-files", type=int, help="Only for a small download smoke test")
    args = parser.parse_args()
    if args.workers < 1 or args.per_minute <= 0:
        parser.error("--workers and --per-minute must be positive")
    if sum((args.index_only, args.download_only, args.finalize_only, args.retry_errors_only)) > 1:
        parser.error("--index-only, --download-only, and --finalize-only are mutually exclusive")
    output = args.output.resolve()
    summary_path = output / "summary.json"
    if summary_path.is_file() and json.loads(summary_path.read_text()).get("kind") == "curated_spire_codex_replays":
        parser.error("this archive was pruned to selected replays; choose another --output to download again")
    output.mkdir(parents=True, exist_ok=True)
    catalog = read_catalog(output) if args.download_only or args.finalize_only or args.retry_errors_only else index_replays(output, page_limit=args.page_limit)
    print(f"catalog_size={len(catalog)} output={output}", flush=True)
    if args.finalize_only:
        progress = output / "progress.json"
        errors = json.loads(progress.read_text()).get("errors", {}) if progress.exists() else {}
        finalize(output, catalog, args.version, errors)
    elif not args.index_only:
        download_replays(output, catalog, version=args.version, workers=args.workers, per_minute=args.per_minute, max_files=args.max_files, retry_errors_only=args.retry_errors_only)


if __name__ == "__main__":
    main()
