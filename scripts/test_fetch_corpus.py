"""Offline tests for the clone-safe corpus downloader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pypdf import PdfWriter


SCRIPT = Path(__file__).with_name("fetch_corpus.py")
SPEC = importlib.util.spec_from_file_location("fetch_corpus", SCRIPT)
assert SPEC and SPEC.loader
fetch_corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_corpus)


class FetchCorpusTests(unittest.TestCase):
    def test_download_verify_and_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.add_blank_page(width=72, height=72)
            with source.open("wb") as stream:
                writer.write(stream)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [{
                    "source_id": "paper.pdf", "download_url": "https://arxiv.org/pdf/paper",
                    "sha256": digest, "pages": 2}]}))
            output = root / "output"
            def copy_download(url, destination, timeout):
                destination.write_bytes(source.read_bytes())
            with mock.patch.object(fetch_corpus, "_download", side_effect=copy_download):
                messages = fetch_corpus.fetch(manifest, output)
            self.assertEqual(messages, ["downloaded and verified paper.pdf"])
            self.assertEqual(fetch_corpus.fetch(manifest, output), ["verified paper.pdf"])
            (output / "paper.pdf").write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                fetch_corpus.fetch(manifest, output)

    def test_extra_pdf_and_unsafe_manifest_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [{
                "source_id": "../paper.pdf", "download_url": "https://arxiv.org/pdf/paper",
                    "sha256": "0" * 64, "pages": 1}]}))
            with self.assertRaisesRegex(ValueError, "plain PDF filename"):
                fetch_corpus.fetch(manifest, root / "output")

    def test_duplicate_ids_extra_files_and_invalid_timeout_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paper = {"source_id": "paper.pdf",
                "download_url": "https://arxiv.org/pdf/paper",
                "sha256": "0" * 64, "pages": 1}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [paper, paper]}))
            with self.assertRaisesRegex(ValueError, "duplicate source_id"):
                fetch_corpus.fetch(manifest, root / "output")
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [paper]}))
            output = root / "output"
            output.mkdir()
            (output / "unexpected.pdf").write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "outside the declared scope"):
                fetch_corpus.fetch(manifest, output)
            with self.assertRaisesRegex(ValueError, "finite positive"):
                fetch_corpus.fetch(manifest, root / "other", timeout=0)
            for timeout in (float("nan"), float("inf"), True):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    fetch_corpus.fetch(manifest, root / "other", timeout=timeout)

    def test_manifest_must_be_an_object(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version 1"):
                fetch_corpus.fetch(manifest, root / "output")

    def test_non_arxiv_or_unversioned_download_url_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paper = {"source_id": "1234.56789v2.pdf",
                "download_url": "https://example.test/1234.56789v2.pdf",
                "sha256": "0" * 64, "pages": 1}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [paper]}))
            with self.assertRaisesRegex(ValueError, "versioned arXiv"):
                fetch_corpus.fetch(manifest, root / "output")
            paper["download_url"] = "https://arxiv.org/pdf/1234.56789"
            manifest.write_text(json.dumps({"schema_version": 1,
                "scope": "exactly_listed_pdfs", "papers": [paper]}))
            with self.assertRaisesRegex(ValueError, "versioned arXiv"):
                fetch_corpus.fetch(manifest, root / "output")


if __name__ == "__main__":
    unittest.main()
