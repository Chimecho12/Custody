"""Operator enrollment and offline audit commands, independent of a running Agent."""

def provision(directory, output_path, op, args):
    import secrets

    from .. import enrollment
    from ..auditing import fingerprint
    from ..common import MODEL_HASH, MODEL_ID
    from ..packages import create_recipient, read_document, verify_package, write_document
    if op == "enroll_prepare":
        directory = directory / "operators" / ("operator-" + secrets.token_hex(6))
        return {**enrollment.prepare_operator(directory, args["role"], args.get("endpoint") or None), "directory": str(directory)}
    if op == "enroll_propose":
        paths = args["card_paths"]
        if not 4 <= len(paths) <= 5:
            raise ValueError("역할별 카드 4~5개가 필요합니다.")
        proposal = enrollment.propose([read_document(p) for p in paths],
            previous=read_document(args["previous_bundle"]) if args.get("previous_bundle") else None,
            checkpoint=read_document(args["checkpoint"]) if args.get("checkpoint") else None,
            model_id=args.get("model_id") or MODEL_ID, model_hash=args.get("model_hash") or MODEL_HASH,
            model_kind=args.get("model_kind", "deterministic_mock"), model_name=args.get("model_name") or None,
            pre_exec=args.get("pre_exec", False))
        path = output_path("deployment-proposal")
        write_document(path, proposal)
        return {"path": str(path), "fingerprint": fingerprint(proposal), "proposal": proposal}
    if op == "enroll_endorse":
        endorsement = enrollment.endorse(args["operator_directory"], read_document(args["proposal"]),
                                           args["fingerprint"], args.get("previous_config") or None)
        path = output_path("endorsement")
        write_document(path, endorsement)
        return {"path": str(path), "role": endorsement["body"]["role"]}
    if op == "enroll_assemble":
        paths = args["endorsement_paths"]
        if not 4 <= len(paths) <= 5:
            raise ValueError("모든 운영자의 승인 파일이 필요합니다.")
        bundle = enrollment.assemble(read_document(args["proposal"]), [read_document(p) for p in paths],
            read_document(args["previous_bundle"]) if args.get("previous_bundle") else None)
        path = output_path("deployment-bundle")
        write_document(path, bundle)
        return {"path": str(path), "fingerprint": fingerprint(bundle["proposal"])}
    if op == "enroll_inspect":
        bundle = read_document(args["bundle"])
        digest = enrollment.verify_deployment(bundle)
        config = enrollment.configuration(bundle)
        return {"fingerprint": digest, "epoch": config["epoch"], "identities": config["identities"],
                "endpoints": config["endpoints"], "model_id": config["model_id"],
                "history": config["deployment_history"], "endorsements_verified": True,
                "legal_independence_verified": False}
    if op == "enroll_activate":
        return enrollment.activate(args["operator_directory"], read_document(args["bundle"]), args["fingerprint"],
            bind=args.get("bind") or "127.0.0.1", model_endpoint=args.get("model_endpoint") or None,
            previous_config=args.get("previous_config") or None)
    if op == "recipient_create":
        return create_recipient(directory / "auditors" / secrets.token_hex(8))
    if op == "audit_verify":
        return verify_package(read_document(args["package"]), read_document(args["trust"]),
                              args["fingerprint"], args.get("recipient_directory") or None)
    raise ValueError("unsupported provisioning operation")
