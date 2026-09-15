"""체크포인트 앵커: 트리 헤드를 외부 목격자에게 주기적으로 고정한다.

블록체인에 대한 답 (05 검토서 §6, 종합노트 §13.5):
- 기본 구현은 파일 기반 목격자 모사다. 실제 RFC 3161 타임스탬프 서버 연동은
  itx.audit.anchor_tsa.TSAAnchor로 교체하고 별도로 신뢰한 TSA CA를 제공한다.
- 앵커가 답하는 질문은 "탐지율이 오르는가"가 아니라 "T 가 나중에 다른 과거를 제시하면
  제3자가 발견할 수 있는가"다. 요청 단위 온체인 기록·원문·비솔트 해시 게시는 하지 않는다.
- 전송 전 신용은 앵커가 아니라 사용자가 서명한 요청 계약이 담당한다. 앵커는 그 계약과
  판정이 기록된 뒤 바뀌지 않았음을 드러내는 장치다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .merkle import MerkleTree, verify_consistency


class CheckpointAnchor:
    kind = "mock-file-witness"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.records: list[dict[str, Any]] = []

    def anchor(self, tree_head: dict[str, Any], now: int) -> dict[str, Any]:
        rec = {
            "log_id": tree_head["log_id"],
            "tree_size": tree_head["tree_size"],
            "root_hash": tree_head["root_hash"],
            "head_time": tree_head["time"],
            "ts_kid": tree_head["ts_kid"],
            "head_signature": tree_head["signature"],
            "anchored_at": now,
            "witness": self.kind,
        }
        self.records.append(rec)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.records, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    @staticmethod
    def verify_tree(tree: MerkleTree, records: list[dict[str, Any]], *,
                    tsa_ca_file: Path | str | None = None,
                    tsa_token_dir: Path | str | None = None,
                    tsa_openssl: str = "openssl") -> list[dict[str, Any]]:
        """각 앵커에 대해: 트리가 현재 제시하는 같은 크기의 루트가 앵커 루트와 같은가,
        그리고 앵커 시점 → 현재 헤드로의 일관성 증명이 성립하는가."""
        results = []
        head_size = tree.size
        head_root = tree.root()
        for rec in records:
            size = rec["tree_size"]
            out = {"tree_size": size, "anchored_root": rec["root_hash"], "anchored_at": rec["anchored_at"]}
            if size > head_size:
                out.update(recomputed_root=None, root_matches=False, consistent_with_head=False,
                           ok=False, reason="현재 로그가 앵커된 크기보다 짧음 (꼬리 삭제)")
                results.append(out)
                continue
            recomputed = tree.root_at(size)
            proof = tree.consistency_proof(size, head_size)
            consistent = verify_consistency(size, head_size, bytes.fromhex(rec["root_hash"]), head_root, proof)
            matches = recomputed.hex() == rec["root_hash"]
            out.update(
                recomputed_root=recomputed.hex(),
                root_matches=matches,
                consistent_with_head=consistent,
                ok=(matches and consistent),
                reason="일치" if (matches and consistent) else "앵커된 체크포인트와 다른 과거를 제시함 (기록 재작성)",
            )
            # TSA 기록은 루트 비교만으로 통과시키지 않는다. 감사자의 신뢰 CA와
            # 저장된 토큰이 없거나 검증에 실패하면 전체 앵커도 실패한다.
            if rec.get("witness") == "rfc3161-tsa" or "tsr_file" in rec:
                from itx.audit.anchor_tsa import TSAError, verify_tsa_anchor
                try:
                    info = verify_tsa_anchor(rec, token_dir=tsa_token_dir,
                                             ca_file=tsa_ca_file, openssl=tsa_openssl)
                    out.update(tsa_verified=True, gen_time=info["gen_time"])
                except TSAError as exc:
                    out.update(tsa_verified=False, ok=False, reason=str(exc))
            results.append(out)
        return results

    def verify_log(self, log) -> list[dict[str, Any]]:
        return self.verify_tree(log.tree, self.records)
