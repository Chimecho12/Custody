"""itx actual-network evaluation runtime and desktop sidecar entry point."""
from __future__ import annotations
import argparse
import json
import sys


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("desktop")
    d.add_argument("--data-dir", required=True)
    s = sub.add_parser("service")
    s.add_argument("--config", required=True)
    s.add_argument("--parent-pipe", action="store_true")
    i = sub.add_parser("init")
    i.add_argument("--directory", required=True)
    i.add_argument("--connected", action="store_true")
    o = sub.add_parser("operator-init", help="generate keys locally and export a signed public card")
    o.add_argument("--directory", required=True)
    o.add_argument("--role", required=True, choices=list("URMTW"))
    o.add_argument("--endpoint")
    d = sub.add_parser("deployment-propose")
    d.add_argument("--cards", nargs="+", required=True)
    d.add_argument("--previous")
    d.add_argument("--checkpoint")
    d.add_argument("--model-id", default="itx-reference-v1")
    d.add_argument("--model-hash")
    d.add_argument("--model-kind", choices=["deterministic_mock", "ollama"], default="deterministic_mock")
    d.add_argument("--model-name")
    d.add_argument("--pre-exec", action="store_true")
    d.add_argument("--output", required=True)
    e = sub.add_parser("deployment-endorse")
    e.add_argument("--operator", required=True)
    e.add_argument("--proposal", required=True)
    e.add_argument("--fingerprint", required=True)
    e.add_argument("--previous-config")
    e.add_argument("--output", required=True)
    b = sub.add_parser("deployment-assemble")
    b.add_argument("--proposal", required=True)
    b.add_argument("--endorsements", nargs="+", required=True)
    b.add_argument("--previous")
    b.add_argument("--output", required=True)
    ac = sub.add_parser("deployment-activate")
    ac.add_argument("--operator", required=True)
    ac.add_argument("--bundle", required=True)
    ac.add_argument("--fingerprint", required=True)
    ac.add_argument("--bind", default="127.0.0.1")
    ac.add_argument("--model-endpoint")
    ac.add_argument("--previous-config")
    ar = sub.add_parser("audit-recipient")
    ar.add_argument("--directory", required=True)
    at = sub.add_parser("audit-trust")
    at.add_argument("--config", required=True)
    at.add_argument("--output", required=True)
    ax = sub.add_parser("audit-export")
    ax.add_argument("--config", required=True)
    ax.add_argument("--output", required=True)
    ax.add_argument("--recipient")
    ax.add_argument("--recipient-fingerprint")
    av = sub.add_parser("audit-verify")
    av.add_argument("--package", required=True)
    av.add_argument("--trust", required=True)
    av.add_argument("--fingerprint", required=True)
    av.add_argument("--recipient-directory")
    av.add_argument("--output")
    for name in ("preflight", "witness"):
        c = sub.add_parser(name)
        c.add_argument("--config", required=True)
        c.add_argument("--output")
    req = sub.add_parser("request")
    req.add_argument("--config", required=True)
    req.add_argument("--prompt", required=True)
    req.add_argument("--mode", choices=["protect", "strict", "observe"], default="protect")
    bench = sub.add_parser("benchmark")
    bench.add_argument("--output", required=True)
    bench.add_argument("--repeats", type=int, default=5)
    a = p.parse_args()
    if a.command == "desktop":
        from itx.runtime.desktop import stdio
        stdio(a.data_dir)
    elif a.command == "service":
        from itx.runtime.service import serve
        serve(a.config, a.parent_pipe)
    elif a.command == "init":
        from itx.runtime.lab import create_deployment
        print(create_deployment(a.directory, lab=not a.connected))
    else:
        from itx.runtime.commands import execute
        result = execute(a)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and result.get("ok") is False:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
