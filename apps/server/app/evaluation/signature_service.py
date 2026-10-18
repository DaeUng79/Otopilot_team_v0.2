"""SCO-04 / RES-03. Signatures bind the current server-calculated payload."""

import base64
import binascii
import hashlib
import sqlite3
import struct

from app.committee.committee_app.v2_core import now
from app.shared.db import DTO, Actor, Store, future, insert, one, require, text


def save_signature(c: sqlite3.Connection, s: Store, a: Actor, b: DTO) -> DTO:
    from app.evaluation.evaluation_service import review_scores
    from app.evaluation.result_service import result_payload

    session = s.session(c, a, b)
    purpose = b.get("purpose")
    require(
        purpose in {"EVALUATION", "CHAIR_RESULT"},
        "서명 목적을 확인하세요.",
        "INPUT_INVALID",
        422,
    )
    participant = s.participant(c, a, session, chair=purpose == "CHAIR_RESULT")
    require(
        b.get("consent") is True and b.get("consent_text_version") == "signature-v2",
        "점수와 서명 동의문을 확인하세요.",
        "CONSENT_REQUIRED",
        422,
    )
    if purpose == "EVALUATION":
        require(session["status"] == "OPEN", "평가 서명을 저장할 수 없는 상태입니다.")
        require(
            not c.execute(
                "SELECT 1 FROM evaluation_submissions WHERE session_id=? AND participant_id=?",
                (session["id"], participant["id"]),
            ).fetchone(),
            "이미 제출했습니다.",
            "SUBMITTED",
        )
        review = review_scores(c, s, a, b)
        require(
            not review["missing"], "모든 업체의 평가를 입력하세요.", "SCORES_INCOMPLETE"
        )
        checksum = review["payload_sha256"]
    else:
        require(
            session["status"] == "ALL_SUBMITTED",
            "전원 제출과 집계 후 서명할 수 있습니다.",
        )
        checksum = result_payload(c, session, text(b, "result_run_id"))[
            "payload_sha256"
        ]
    require(
        b.get("payload_sha256") == checksum,
        "검토한 내용이 변경되었습니다. 다시 확인하세요.",
        "PAYLOAD_CHANGED",
    )
    encoded = text(b, "image", 700000)
    try:
        raw = base64.b64decode(
            encoded.removeprefix("data:image/png;base64,"), validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise ValueError("올바른 PNG 서명이 필요합니다.") from exc
    require(
        60 <= len(raw) <= 512000
        and raw[:8] == b"\x89PNG\r\n\x1a\n"
        and raw[12:16] == b"IHDR",
        "PNG 서명 이미지를 확인하세요.",
        "IMAGE_INVALID",
        422,
    )
    width, height = struct.unpack(">II", raw[16:24])
    require(
        1 <= width <= 1600 and 1 <= height <= 800 and raw[-8:-4] == b"IEND",
        "서명 이미지 크기/형식을 확인하세요.",
        "IMAGE_INVALID",
        422,
    )
    identity = insert(
        c,
        "signatures",
        {
            "project_id": session["project_id"],
            "session_id": session["id"],
            "signer_participant_id": participant["id"],
            "purpose": purpose,
            "payload_sha256": checksum,
            "image_blob": raw,
            "image_sha256": hashlib.sha256(raw).hexdigest(),
            "consent_text_version": "signature-v2",
            "signed_at": now(),
            "expires_at": future(1),
        },
    )
    return {"id": identity, "payload_sha256": checksum, "purpose": purpose}


def verify_signature(
    c: sqlite3.Connection,
    b: DTO,
    session: DTO,
    participant: DTO,
    purpose: str,
    checksum: str,
) -> None:
    sig = one(c, "SELECT * FROM signatures WHERE id=?", (text(b, "signature_id"),))
    require(
        sig["session_id"] == session["id"]
        and sig["signer_participant_id"] == participant["id"]
        and sig["purpose"] == purpose,
        "서명 주체와 대상을 확인하세요.",
        "SIGNATURE_INVALID",
    )
    require(
        sig["payload_sha256"] == checksum == b.get("payload_sha256"),
        "서명 이후 내용이 변경되었습니다. 다시 서명하세요.",
        "PAYLOAD_CHANGED",
    )
    require(
        sig["expires_at"] > now(),
        "서명 유효시간이 지났습니다. 다시 서명하세요.",
        "SIGNATURE_EXPIRED",
    )
