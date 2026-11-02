from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.submit_sdtm import _resolve_paths, submit


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"id": "job-123", "workflow": "sdtm"}).encode("utf-8")


class SubmitSDTMTests(unittest.TestCase):
    def test_submit_maps_local_files_to_sdtm_multipart_roles(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / "edc.json"
            raw = root / "dm.csv"
            crf = root / "blank-crf.pdf"
            report = root / "p21.xlsx"
            metadata.write_text('{"datasets": []}', encoding="utf-8")
            raw.write_text("USUBJID\nSYN-001\n", encoding="utf-8")
            crf.write_bytes(b"%PDF-1.7 synthetic")
            report.write_bytes(b"PK synthetic")
            args = argparse.Namespace(
                metadata=[str(metadata)],
                raw=[str(raw)],
                crf=str(crf),
                validation_report=str(report),
                languages=["r", "sas"],
                title="Synthetic SDTM",
                api_url="http://127.0.0.1:8000/api/v1",
                timeout=10.0,
                acknowledge_deidentified=True,
            )

            with (
                patch("scripts.submit_sdtm.urlopen", return_value=_Response()) as mocked,
                patch.dict("os.environ", {"WORKBENCH_API_TOKEN": "test-token"}),
            ):
                result = submit(args)

            request = mocked.call_args.args[0]
            body = request.data
            self.assertEqual(result["id"], "job-123")
            self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/v1/jobs/sdtm")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertIn(b'name="files"; filename="edc.json"', body)
            self.assertIn(b'name="raw_files"; filename="dm.csv"', body)
            self.assertIn(b'name="crf_file"; filename="blank-crf.pdf"', body)
            self.assertIn(b'name="validation_report"; filename="p21.xlsx"', body)
            self.assertIn(b'"deidentified_acknowledged":true', body)
            self.assertIn(b'"languages":["r","sas"]', body)

    def test_submit_requires_acknowledgement_before_reading_paths(self) -> None:
        args = argparse.Namespace(acknowledge_deidentified=False)
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            submit(args)

    def test_metadata_rejects_unsupported_extension(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "edc.txt"
            path.write_text("synthetic", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected: .json, .xlsx"):
                _resolve_paths([str(path)], label="metadata")


if __name__ == "__main__":
    unittest.main()
