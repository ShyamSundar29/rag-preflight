#!/usr/bin/env python3
"""Download the pinned public reference corpus and verify every byte and page."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "rag-preflight-chroma-reference/corpus/manifest.json"
SECOND_MANIFEST = REPOSITORY_ROOT / "rag-preflight-faiss-reference/corpus/manifest.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "pdfs"
MAX_PDF_BYTES = 100 * 1024 * 1024


def _manifest(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("scope") != "exactly_listed_pdfs"):
        raise ValueError("manifest must declare schema_version 1 and exactly_listed_pdfs")
    papers = data.get("papers")
    if not isinstance(papers, list) or not papers:
        raise ValueError("manifest papers must be a nonempty list")
    required = {"source_id", "download_url", "sha256", "pages"}
    seen = set()
    for paper in papers:
        if not isinstance(paper, dict) or not required <= paper.keys():
            raise ValueError(f"every paper must contain {sorted(required)}")
        source_id = paper["source_id"]
        if (not isinstance(source_id, str) or "/" in source_id or "\\" in source_id
                or Path(source_id).name != source_id
                or not source_id.lower().endswith(".pdf")):
            raise ValueError("source_id must be a plain PDF filename")
        if source_id in seen:
            raise ValueError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        download_url = paper["download_url"]
        if not isinstance(download_url, str):
            raise ValueError(f"{source_id}: download_url must be a versioned arXiv PDF URL")
        parsed = urlsplit(download_url)
        expected_path = "/pdf/" + source_id.removesuffix(".pdf")
        if (parsed.scheme != "https" or parsed.hostname != "arxiv.org"
                or parsed.path != expected_path or parsed.query or parsed.fragment
                or parsed.username or parsed.password or parsed.port is not None):
            raise ValueError(f"{source_id}: download_url must be a versioned arXiv PDF URL")
        digest = paper["sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"{source_id}: sha256 must contain 64 hexadecimal characters")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError(f"{source_id}: sha256 must be hexadecimal") from exc
        if type(paper["pages"]) is not int or paper["pages"] < 1:
            raise ValueError(f"{source_id}: pages must be a positive integer")
    return papers


def _verify(path: Path, paper: dict[str, object]) -> None:
    from pypdf import PdfReader

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != paper["sha256"]:
        raise ValueError(f"{path.name}: SHA-256 mismatch ({digest})")
    try:
        pages = len(PdfReader(path).pages)
    except Exception as exc:
        raise ValueError(f"{path.name}: downloaded file is not a readable PDF") from exc
    if pages != paper["pages"]:
        raise ValueError(f"{path.name}: expected {paper['pages']} pages, found {pages}")


def _download(url: str, destination: Path, timeout: float) -> None:
    request = Request(url, headers={"User-Agent": "rag-preflight-reference/0.1.0"})
    with urlopen(request, timeout=timeout) as response, destination.open("wb") as stream:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                raise ValueError(f"download exceeds {MAX_PDF_BYTES} bytes")
            stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())


def fetch(manifest: Path, output: Path, *, timeout: float = 60.0) -> list[str]:
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be a finite positive number")
    papers = _manifest(manifest)
    output.mkdir(parents=True, exist_ok=True)
    expected = {str(paper["source_id"]) for paper in papers}
    extras = sorted(path.name for path in output.glob("*.pdf") if path.name not in expected)
    if extras:
        raise ValueError(f"output contains PDFs outside the declared scope: {', '.join(extras)}")
    results = []
    for paper in papers:
        target = output / str(paper["source_id"])
        if target.exists():
            _verify(target, paper)
            results.append(f"verified {target.name}")
            continue
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".partial", dir=output)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            _download(str(paper["download_url"]), temporary, timeout)
            _verify(temporary, paper)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        results.append(f"downloaded and verified {target.name}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    try:
        if args.manifest.resolve() == DEFAULT_MANIFEST.resolve() and SECOND_MANIFEST.exists():
            if json.loads(args.manifest.read_text()) != json.loads(SECOND_MANIFEST.read_text()):
                raise ValueError("Chroma and FAISS corpus manifests differ")
        for message in fetch(args.manifest.resolve(strict=True), args.output.resolve(), timeout=args.timeout):
            print(message)
        print(f"corpus ready: {args.output.resolve()}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Corpus setup error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
