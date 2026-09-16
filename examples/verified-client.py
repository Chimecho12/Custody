"""Run from the repository root: python -m examples.verified-client (local TLS lab)."""
import tempfile

from itx.client import ItxClient

with tempfile.TemporaryDirectory(prefix="itx-sdk-") as directory, ItxClient(directory, lab=True) as client:
    result = client.request("SDK에서 수용 경계를 확인합니다.", mode="strict")
    # Only a verified response reaches the application consumer here.
    print(result.text)
    print(result.request_id, result.elapsed_ms)
