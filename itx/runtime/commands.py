"""CLI operations also used by the desktop's explicit provisioning controls."""
from . import enrollment
from .agent import Agent
from .auditing import fingerprint, trust_from_config
from .common import MODEL_HASH, load_config
from .packages import build_package, create_recipient, encrypt_package, read_document, verify_package, write_document


def execute(args):
    c = args.command
    if c == "operator-init":
        return enrollment.prepare_operator(args.directory, args.role, args.endpoint)
    if c == "deployment-propose":
        proposal = enrollment.propose([read_document(p) for p in args.cards],
            previous=read_document(args.previous) if args.previous else None,
            checkpoint=read_document(args.checkpoint) if args.checkpoint else None,
            model_id=args.model_id, model_hash=args.model_hash or MODEL_HASH,
            model_kind=args.model_kind, model_name=args.model_name, pre_exec=args.pre_exec)
        write_document(args.output, proposal)
        return {"path": args.output, "fingerprint": fingerprint(proposal)}
    if c == "deployment-endorse":
        endorsement = enrollment.endorse(args.operator, read_document(args.proposal), args.fingerprint, args.previous_config)
        return {"path": write_document(args.output, endorsement)}
    if c == "deployment-assemble":
        bundle = enrollment.assemble(read_document(args.proposal), [read_document(p) for p in args.endorsements],
                                     read_document(args.previous) if args.previous else None)
        return {"path": write_document(args.output, bundle), "fingerprint": fingerprint(bundle["proposal"])}
    if c == "deployment-activate":
        return enrollment.activate(args.operator, read_document(args.bundle), args.fingerprint,
                                   bind=args.bind, model_endpoint=args.model_endpoint, previous_config=args.previous_config)
    if c == "audit-recipient":
        return create_recipient(args.directory)
    if c == "audit-trust":
        trust = trust_from_config(load_config(args.config))
        return {"path": write_document(args.output, trust), "fingerprint": fingerprint(trust)}
    if c == "audit-verify":
        report = verify_package(read_document(args.package), read_document(args.trust), args.fingerprint, args.recipient_directory)
        if args.output:
            write_document(args.output, report)
        return report
    if c == "benchmark":
        from .benchmark import benchmark
        return benchmark(args.output, args.repeats)
    if c == "endurance":
        from .endurance import endurance
        return endurance(args.output, args.requests, args.outage, tuple(args.modes))
    if c == "conformance":
        from itx.cose import run_conformance
        report = run_conformance(tuple(args.group) if args.group else None,
                                 external=not args.no_external)
        if args.output:
            write_document(args.output, report)
            report = {**report, "path": args.output}
        return report
    if c == "key-inventory":
        from itx import keys as keystore
        view = keystore.build(load_config(args.config))
        if args.output:
            write_document(args.output, view)
            view = {**view, "path": args.output}
        return view
    agent = Agent(args.config)
    try:
        if c == "audit-export":
            value = build_package(agent, include_private=bool(args.recipient))
            if args.recipient:
                value = encrypt_package(value, read_document(args.recipient), args.recipient_fingerprint)
            return {"path": write_document(args.output, value), "private_included": bool(args.recipient)}
        if c == "preflight":
            result = agent.preflight()
        elif c == "witness":
            result = agent.witness()
        elif c == "request":
            return agent.request(args.prompt, args.mode)
        else:
            raise ValueError("unsupported command")
        if args.output:
            write_document(args.output, result)
        return result
    finally:
        agent.close()
