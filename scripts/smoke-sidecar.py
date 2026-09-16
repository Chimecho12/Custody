"""Validate a packaged/installed Agent; child processes use the bundled runtime."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Client:
    def __init__(self, binary, directory):
        self.proc = subprocess.Popen([str(binary), "desktop", "--data-dir", str(directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=0x08000000 if os.name == "nt" else 0)
        self.messages = queue.Queue()
        self.counter = 0
        self.closed = False
        def reader():
            for line in self.proc.stdout:
                self.messages.put(json.loads(line))
        threading.Thread(target=reader, daemon=True).start()

    def call(self, op, args=None):
        self.counter += 1
        ident = str(self.counter)
        self.proc.stdin.write(json.dumps({"id": ident, "operation": op, "args": args or {}}) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            reply = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if reply.get("id") == ident:
                assert reply["ok"], reply
                return reply["result"]
        raise TimeoutError(op)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.proc.poll() is None:
            self.proc.stdin.write('{"operation":"shutdown"}\n')
            self.proc.stdin.flush()
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        errors = self.proc.stderr.read()
        self.proc.stdout.close()
        self.proc.stderr.close()
        assert self.proc.returncode == 0, errors


def run(binary, directory):
    client = Client(binary, directory)
    try:
        status = client.call("status")
        assert all(v["running"] for v in status["services"].values()), status
        # 패키징된 Agent 가 앱보다 오래되면 새 화면의 명령만 거부당한다. 목록을 직접 확인한다.
        from itx.runtime.desktop import ALLOWED_OPERATIONS
        reported = set(status.get("operations") or ())
        missing = set(ALLOWED_OPERATIONS) - reported
        assert not missing, f"패키징된 Agent 가 모르는 명령: {sorted(missing)} — 사이드카를 다시 패키징하세요"
        inventory = client.call("key_inventory")
        assert inventory["keys"] and "summary" in inventory, inventory
        conformance = client.call("standards")
        assert conformance["totals"]["fail"] == 0, conformance["totals"]
        normal = client.call("request", {"prompt": "packaged normal", "mode": "strict", "token": "normal"})
        assert normal["state"] == "accept", normal
        bad = client.call("request", {"prompt": "packaged tamper", "mode": "protect", "scenario": "response_tamper", "token": "tamper"})
        assert bad["state"] == "quarantine" and bad["response"] is None, bad
        time.sleep(0.7)
        bad = client.call("refresh", {"sub": bad["sub"]})
        eqs = bad["t_verdict"]["payload"]["equations"]
        assert eqs["E6"]["result"] == eqs["E7"]["result"] == "pass"
        assert eqs["E10"]["result"] == "fail"
        first_audit = client.call("audit")
        assert first_audit["ok"] and first_audit["pinned_identity"], first_audit
        client.call("stop_t")
        continued = client.call("request", {"prompt": "outage protect", "mode": "protect", "token": "outage-p"})
        timeout = client.call("request", {"prompt": "outage strict", "mode": "strict", "token": "outage-s"})
        assert continued["state"] == "accept", continued
        assert timeout["state"] == "reject_timeout" and timeout["response"] is None, timeout
        assert client.call("status")["pending_evidence"] > 0
        client.call("start_t")
        deadline = time.monotonic() + 10
        while client.call("status")["pending_evidence"] and time.monotonic() < deadline:
            time.sleep(0.2)
        assert client.call("status")["pending_evidence"] == 0
        for r in (continued, timeout):
            client.call("refresh", {"sub": r["sub"]})
        audit = client.call("audit")
        assert audit["ok"] and audit["previous_checkpoint"], audit
        sim = client.call("simulation", {"scenario": "S03", "mode": "protect"})
        assert sim["attempts"][-1]["gate"]["action"] == "quarantine"
        exported = client.call("export")
        assert len(json.loads(Path(exported["path"]).read_text(encoding="utf-8"))["requests"]) == 4
        client.close()
        client = Client(binary, directory)
        assert len(client.call("history")) == 4
        reopened_audit = client.call("audit")
        assert reopened_audit["ok"] and reopened_audit["previous_checkpoint"]
        return {"binary": str(binary), "transport": "actual_loopback_TLS", "model": "deterministic_mock",
                "governance": "single_operator", "roles": 3, "normal_strict": normal["state"],
                "tamper_protect": bad["state"], "E6": "pass", "E7": "pass", "E10": "fail",
                "outage_protect": continued["state"], "outage_strict": timeout["state"],
                "audit": audit["ok"], "restart_history_count": 4, "restart_checkpoint_audit": reopened_audit["ok"],
                "simulation_S03": "quarantine", "samples_per_case": 1,
                "operations_reported": len(reported), "key_inventory": len(inventory["keys"]),
                "conformance_claim": conformance["claim_status"],
                "elapsed_ms": {"normal_strict": normal["elapsed_ms"], "tamper_protect": bad["elapsed_ms"],
                               "outage_protect": continued["elapsed_ms"], "outage_strict": timeout["elapsed_ms"]}}
    finally:
        client.close()
        for log in Path(directory).glob("lab/*/service.stderr.log"):
            if log.stat().st_size:
                print(log.parent.name, log.read_text(encoding="utf-8"), file=sys.stderr)


if __name__ == "__main__":
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="itx-packaged-") as directory:
        result = run(binary, directory)
    print(json.dumps(result, ensure_ascii=False))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
