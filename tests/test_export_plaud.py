from __future__ import annotations

import gzip
import importlib.util
import pathlib
import sys
import unittest


SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "skills"
    / "plaud-transcript-export"
    / "scripts"
    / "export_plaud.py"
)

spec = importlib.util.spec_from_file_location("export_plaud", SCRIPT)
export_plaud = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["export_plaud"] = export_plaud
spec.loader.exec_module(export_plaud)


class ExportPlaudFormattingTests(unittest.TestCase):
    def test_gzip_or_text_handles_plain_and_gzip(self) -> None:
        self.assertEqual(export_plaud.gzip_or_text(b"hello"), "hello")
        self.assertEqual(export_plaud.gzip_or_text(gzip.compress(b"hello")), "hello")

    def test_transcript_markdown_formats_segments(self) -> None:
        result = export_plaud.transcript_markdown(
            [
                {
                    "start_time": 1000,
                    "end_time": 62000,
                    "speaker": "Speaker 1",
                    "content": "Hello world",
                }
            ]
        )
        self.assertIn("[00:01 - 01:02] Speaker 1: Hello world", result)

    def test_outline_markdown_formats_topics(self) -> None:
        result = export_plaud.outline_markdown(
            [{"start_time": 0, "end_time": 120000, "topic": "Opening"}]
        )
        self.assertEqual(result, "- [00:00 - 02:00] Opening\n")

    def test_sanitize_detail_removes_signed_query(self) -> None:
        sanitized = export_plaud.sanitize_detail(
            {
                "data_link": (
                    "https://example-bucket.s3.amazonaws.com/file.json.gz"
                    "?X-Amz-Date=20260703T000000Z&X-Amz-Expires=300"
                    "&unused=abc123"
                )
            }
        )
        self.assertEqual(sanitized["data_link"]["host"], "example-bucket.s3.amazonaws.com")
        self.assertEqual(sanitized["data_link"]["path"], "/file.json.gz")
        self.assertEqual(sanitized["data_link"]["expires_seconds"], "300")
        self.assertNotIn("abc123", str(sanitized))

    def test_requires_auth_or_cookie(self) -> None:
        cfg = export_plaud.parse_args(["--metadata-only", "--output", "/tmp/unused"])
        with self.assertRaises(export_plaud.PlaudExportError):
            export_plaud.export(cfg)


if __name__ == "__main__":
    unittest.main()
