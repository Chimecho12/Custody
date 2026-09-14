"""Exercise v0.3 provisioning, witness, encryption and rotation inside the frozen Agent."""
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from itx.client import ItxClient
from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("smoke_sidecar", Path(__file__).with_name("smoke-sidecar.py"))
smoke = module_from_spec(spec)
spec.loader.exec_module(smoke)


def free_ports():
    sockets = [socket.socket() for _ in "RMTW"]
    try:
        for s in sockets:
            s.bind(("127.0.0.1", 0))
        return dict(zip("RMTW", [s.getsockname()[1] for s in sockets]))
    finally:
        for s in sockets:
            s.close()


def provision(client, previous=None, checkpoint=None, old_configs=None):
    ports = free_ports()
    operators = {r: client.call("enroll_prepare", {"role": r, "endpoint": f"https://127.0.0.1:{ports[r]}" if r != "U" else None}) for r in "URMTW"}
    proposal = client.call("enroll_propose", {"card_paths": [v["card"] for v in operators.values()],
                          "previous_bundle": previous, "checkpoint": checkpoint})
    endorsements = [client.call("enroll_endorse", {"operator_directory": operators[r]["directory"],
        "proposal": proposal["path"], "fingerprint": proposal["fingerprint"],
        "previous_config": old_configs[r] if old_configs else None})["path"] for r in operators]
    bundle = client.call("enroll_assemble", {"proposal": proposal["path"], "endorsement_paths": endorsements, "previous_bundle": previous})
    inspected = client.call("enroll_inspect", {"bundle": bundle["path"]})
    assert inspected["endorsements_verified"] and not inspected["legal_independence_verified"]
    configs = {r: client.call("enroll_activate", {"operator_directory": operators[r]["directory"],
        "bundle": bundle["path"], "fingerprint": bundle["fingerprint"],
        "previous_config": old_configs[r] if old_configs else None})["config_path"] for r in operators}
    return bundle["path"], configs


class Services:
    def __init__(self, binary, configs):
        self.children = []
        try:
            for role in "TMRW":
                errors = open(Path(configs[role]).parent / "smoke.stderr.log", "ab")
                child = subprocess.Popen([str(binary), "service", "--config", configs[role], "--parent-pipe"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                    creationflags=0x08000000 if os.name == "nt" else 0)
                errors.close()
                self.children.append(child)
                ready = queue.Queue()
                threading.Thread(target=lambda c=child, q=ready: q.put(c.stdout.readline()), daemon=True).start()
                line = ready.get(timeout=45)
                assert line and json.loads(line)["ready"], role
        except Exception:
            self.close()
            raise

    def close(self):
        for child in self.children:
            child.stdin.close()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
        self.children = []


def run(binary, root):
    setup = smoke.Client(binary, root / "setup")
    services = None
    try:
        bundle, configs = provision(setup)
        services = Services(binary, configs)
        with ItxClient(root / "consumer", config=configs["U"], agent_binary=binary) as client:
            assert client._call("preflight")["ok"]
            assert client.request("packaged five roles", mode="strict").mode == "strict"
            witnessed = client._call("witness")
            assert not witnessed["on_chain"]
            recipient = setup.call("recipient_create")
            trust = client._call("export_trust")
            public = client._call("export_evidence")
            encrypted = client._call("export_evidence", {"recipient_path": recipient["path"], "recipient_fingerprint": recipient["fingerprint"]})
            checkpoint = client._call("export_checkpoint")
            new_bundle, new_configs = provision(setup, bundle, checkpoint["path"], configs)
            try:
                client.request("retired", mode="protect")
                raise AssertionError("retired epoch accepted")
            except RuntimeError as exc:
                assert "폐기" in str(exc), str(exc)
        services.close()
        # All services are stopped: these two verifications must work fully offline.
        args = {"trust": trust["path"], "fingerprint": trust["fingerprint"]}
        public_report = setup.call("audit_verify", {**args, "package": public["path"]})
        private_report = setup.call("audit_verify", {**args, "package": encrypted["path"], "recipient_directory": str(Path(recipient["path"]).parent)})
        assert public_report["ok"] and public_report["private_scope"] == "partial", public_report
        assert private_report["ok"] and private_report["private_scope"] == "complete", private_report
        assert private_report["witness_receipts_checked"] == 1
        services = Services(binary, new_configs)
        with ItxClient(root / "rotated-consumer", config=new_configs["U"], agent_binary=binary) as client:
            assert client.request("new epoch", mode="strict").mode == "strict"
            assert client.audit()["ok"]
            assert client.status()["epoch"] == 2
        return {"version": "0.3.0", "binary": str(binary), "transport": "actual_loopback_TLS",
            "model": "deterministic_mock", "governance": "five_keys_one_Windows_account",
            "provisioning": True, "signed_preflight": True, "witness_receipts": 1, "on_chain": False,
            "offline_public_audit": public_report["private_scope"], "offline_encrypted_audit": private_report["private_scope"],
            "old_epoch_rejected": True, "new_epoch": 2, "sdk_consumer": True}
    finally:
        if services:
            services.close()
        setup.close()


if __name__ == "__main__":
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="itx-frozen-extensions-") as directory:
        result = run(binary, Path(directory))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
