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


if __name__ == "__main__":
    main()
