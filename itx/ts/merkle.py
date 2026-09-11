"""RFC 9162 (Certificate Transparency 2.0) Merkle 트리.

- 리프 해시 = SHA-256(0x00 || data), 노드 해시 = SHA-256(0x01 || left || right).
- 포함 증명(§2.1.3)과 일관성 증명(§2.1.4)의 생성·검증 알고리즘을 그대로 구현했다.
- 이 트리는 "신뢰 기준점 대비 변경을 드러내는" 장치다. 운영자가 트리와 헤드를 모두
  바꾸면 트리 자체는 깨지지 않으므로, 외부 체크포인트(anchor.py)와 비교해야 한다.
"""
from __future__ import annotations

from itx.crypto import sha256


def leaf_hash(data: bytes) -> bytes:
    return sha256(b"\x00" + data)


def node_hash(left: bytes, right: bytes) -> bytes:
    return sha256(b"\x01" + left + right)


def _largest_pow2_lt(n: int) -> int:
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def mth(hashes: list[bytes]) -> bytes:
    n = len(hashes)
    if n == 0:
        return sha256(b"")
    if n == 1:
        return hashes[0]
    k = _largest_pow2_lt(n)
    return node_hash(mth(hashes[:k]), mth(hashes[k:]))


def inclusion_path(m: int, hashes: list[bytes]) -> list[bytes]:
    n = len(hashes)
    if n <= 1:
        return []
    k = _largest_pow2_lt(n)
    if m < k:
        return inclusion_path(m, hashes[:k]) + [mth(hashes[k:])]
    return inclusion_path(m - k, hashes[k:]) + [mth(hashes[:k])]


def _subproof(m: int, hashes: list[bytes], b: bool) -> list[bytes]:
    n = len(hashes)
    if m == n:
        return [] if b else [mth(hashes)]
    k = _largest_pow2_lt(n)
    if m <= k:
        return _subproof(m, hashes[:k], b) + [mth(hashes[k:])]
    return _subproof(m - k, hashes[k:], False) + [mth(hashes[:k])]


def consistency_path(m: int, hashes: list[bytes]) -> list[bytes]:
    if m == 0 or m == len(hashes):
        return []
    return _subproof(m, hashes, True)


def verify_inclusion(leaf_index: int, tree_size: int, leaf: bytes, proof: list[bytes], root: bytes) -> bool:
    if leaf_index >= tree_size:
        return False
    fn, sn = leaf_index, tree_size - 1
    r = leaf
    for p in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while fn != 0 and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def verify_consistency(first: int, second: int, first_root: bytes, second_root: bytes, proof: list[bytes]) -> bool:
    if first > second:
        return False
    if first == second:
        return first_root == second_root and not proof
    if first == 0:
        return not proof
    if not proof:
        return False
    path = list(proof)
    if first & (first - 1) == 0:
        path = [first_root] + path
    fn, sn = first - 1, second - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    fr = sr = path[0]
    for c in path[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            if not fn & 1:
                while fn != 0 and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1
    return fr == first_root and sr == second_root and sn == 0


class MerkleTree:
    """리프 해시 목록 위의 얇은 래퍼. 크기가 작은 교육용 로그를 전제한다."""

    def __init__(self) -> None:
        self._leaves: list[bytes] = []

    @property
    def size(self) -> int:
        return len(self._leaves)

    def append(self, data: bytes) -> int:
        self._leaves.append(leaf_hash(data))
        return len(self._leaves) - 1

    def leaf(self, index: int) -> bytes:
        return self._leaves[index]

    def root(self) -> bytes:
        return mth(self._leaves)

    def root_at(self, size: int) -> bytes:
        if size > len(self._leaves):
            raise ValueError("size exceeds tree")
        return mth(self._leaves[:size])

    def inclusion_proof(self, index: int, size: int | None = None) -> list[bytes]:
        size = self.size if size is None else size
        return inclusion_path(index, self._leaves[:size])

    def consistency_proof(self, first: int, second: int | None = None) -> list[bytes]:
        second = self.size if second is None else second
        return consistency_path(first, self._leaves[:second])

    # -- 악성 운영자 모사 (시나리오 전용) ----------------------------------
    def replace_leaf(self, index: int, data: bytes) -> None:
        self._leaves[index] = leaf_hash(data)

    def truncate(self, size: int) -> None:
        del self._leaves[size:]
