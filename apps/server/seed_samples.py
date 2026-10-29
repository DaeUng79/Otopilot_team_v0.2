"""가상 운영 데이터 투입 (2026-10-18). 데모 DB에 실제처럼 보이는 위원풀·사업·문서를 넣는다.

실행(서버를 끈 상태에서):
  .venv\\Scripts\\python.exe apps/server/seed_samples.py --samples "C:/coding/제안요청서, 제안서 샘플"

- 위원풀: app/shared/sample_pool.py의 가상 인물 72명을 COM-05(create_candidate) 경로로 등록하고,
  추가 18명은 엑셀 업로드 테스트용 파일로 data/samples/에 저장한다.
- 사업 3개: 샘플 폴더의 제안요청서(HWPX)를 DOC-01 경로로, 업체별 제안서를 PRO-01 경로로 등록한다.
  PDF·PPTX는 pypdf·python-pptx가 설치돼 있을 때만 들어가고 없으면 건너뛴 목록을 출력한다.
- 공공의료 사업은 평가표(서식 복사본)를 확정(CRT-05)까지 해 두어 위원 선정부터 바로 이어갈 수 있다.
여러 번 실행해도 이미 있는 항목은 건너뛴다(멱등).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.api.document_module_routes import event_envelope  # noqa: E402
from app.api.project_documents import _save as save_rfp, resolve_database  # noqa: E402
from app.committee import candidate_pool  # noqa: E402
from app.committee.committee_app.v2_core import Context, digest, now  # noqa: E402
from app.documents import criteria_review, proposal_uploads  # noqa: E402
from app.shared import sample_pool  # noqa: E402
from app.shared.db import Store, insert  # noqa: E402
from app.shared.integration_contracts import apply_event  # noqa: E402
from app.shared.sync_service import deliver_outbox, ref  # noqa: E402
from run import setup  # noqa: E402

DEPT = "web-demo-dept"
ADMIN = "web-demo-admin"
MEDICAL = "공공의료(제안서 평가 지원 서비스)"
RPA = "업무자동화 제안요청서/24년 업무자동화 RPA"
MYDATA = "제안요청서[2026년 경기도 마이데이터 통합 플랫폼 운영 용역]"
PROJECTS = [
    {
        "id": "sample-medical-ai", "name": "2026년 AI 중심 공공의료원 조성사업 민간위탁",
        "contact": ("경기도청", "AI정보화담당관", "주무관", "김보건", "01031002001", "2026-11-05"),
        "rfp": f"{MEDICAL}/제안요청서/(붙임 2) 2026년 AI 중심 공공의료원 조성사업 민간위탁 제안요청서.hwpx",
        "vendors": [
            ("마이허브", f"{MEDICAL}/정성평가자료/마이허브_(식별정보 삭제)사업수행 계획서_총괄PM 김종현.hwpx"),
            ("유신씨앤씨", f"{MEDICAL}/정성평가자료/유신씨앤씨003_2026년 AI 중심 공공의료원 조성 사업_사업수행계획서(정성적 평가용)(사본)_v1.0.hwp"),
            ("메디칼스탠다드 컨소시엄", f"{MEDICAL}/정성평가자료/27. 사업수행계획서-평가용(2026-871-경기도의료원 AI중심 조성).pdf"),
        ],
        "approve_criteria": True,
    },
    {
        "id": "sample-rpa-2024", "name": "경기도 업무자동화시스템 구축 사업",
        "contact": ("경기도청", "AI정보화담당관", "주무관", "박자동", "01031002002", "2026-11-12"),
        "rfp": f"{RPA}/제안요청서/4. 제안요청서(경기도 업무자동화시스템 구축 사업(최종)).hwpx",
        "vendors": [
            ("이든티앤에스", f"{RPA}/제안서/(원본)경기도자동화업무화시스템_정성적_이든티앤에스.pdf"),
            ("휴트리온", f"{RPA}/제안서/3. 정성적제안서(원본) 경기도 업무자동화시스템 구축 용역_휴트리온.pdf"),
            ("세인이엔에스", f"{RPA}/제안서/경기도 업무자동화시스템 구축_정성적 제안서_세인이엔에스_원본.pptx"),
            ("경포", f"{RPA}/제안서/경기도_업무자동화시스템구축_제안서(원본)_경포.pptx"),
        ],
        "approve_criteria": False,
    },
    {
        "id": "sample-mydata-2026", "name": "2026년 경기도 마이데이터 통합 플랫폼 운영 용역",
        "contact": ("경기도청", "AI정보화담당관", "주무관", "이데이터", "01031002003", "2026-11-19"),
        "rfp": f"{MYDATA}/제안요청서[2026년 경기도 마이데이터 통합 플랫폼 운영 용역].hwpx",
        "vendors": [
            ("마이데이터 제안사 A", f"{MYDATA}/1. 2026년 경기도 마이데이터_정성제안서-사본 (최종본).pdf"),
        ],
        "approve_criteria": False,
    },
]


def ctx() -> Context:
    return Context(ADMIN, str(uuid4()))


def seed_catalog(store: Store) -> None:
    with store.runtime.connect(write=True) as c:
        c.execute("UPDATE departments SET organization_name='경기도청',name='AI정보화담당관',updated_at=? WHERE id=?",
                  (now(), DEPT))
        # admin.projection 스냅샷은 version으로 비교하므로 표시명을 바꾸면 version도 올린다.
        for admin_id, label in ((ADMIN, "AI정보화담당관 사업담당자"), ("super-demo", "경기도청 총괄관리자")):
            c.execute("UPDATE admin_users SET display_name=?,updated_at=?,version=version+1 WHERE id=? AND display_name<>?",
                      (label, now(), admin_id, label))
        for s in sample_pool.SPECIALTIES:
            if not c.execute("SELECT 1 FROM specialties WHERE id=?", (s["id"],)).fetchone():
                store.runtime.insert(c, "specialties", {"id": s["id"], "code": s["code"], "name": s["name"],
                                                        "aliases_json": json.dumps(s["aliases"], ensure_ascii=False), "active": 1})
            else:
                c.execute("UPDATE specialties SET aliases_json=? WHERE id=?",
                          (json.dumps(s["aliases"], ensure_ascii=False), s["id"]))
    print(f"분야 {len(sample_pool.SPECIALTIES)}개 준비")


async def seed_pool(store: Store) -> None:
    added = 0
    for m in sample_pool.POOL_MEMBERS:
        phone = m["phone"].replace("-", "")
        with store.runtime.connect() as c:
            exists = c.execute("SELECT 1 FROM evaluator_candidates WHERE department_id=? AND phone_lookup_hmac=?",
                               (DEPT, store.runtime.lookup("phone", DEPT, phone))).fetchone()
        if exists:
            continue
        await candidate_pool.create_candidate(ctx(), {
            "department_id": DEPT, "name": m["name"], "organization_name": m["organization_name"],
            "department_name": m["department_name"], "position": m["position"], "phone": m["phone"],
            "email": m["email"], "specialty_ids": m["specialty_ids"]}, runtime=store.runtime)
        added += 1
    out = ROOT / "data/samples/평가위원_추가등록_가상.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    sample_pool.write_pool_xlsx(out, sample_pool.EXTRA_MEMBERS)
    print(f"위원풀 {added}명 추가 (총 {len(sample_pool.POOL_MEMBERS)}명 기준) · 엑셀 업로드용 18명: {out}")


def seed_project(store: Store, spec: dict) -> list[dict]:
    org, dept, pos, name, phone, date = spec["contact"]
    with store.connect("admin", True) as c:
        if not c.execute("SELECT 1 FROM projects WHERE id=?", (spec["id"],)).fetchone():
            insert(c, "projects", {
                "id": spec["id"], "department_id": DEPT, "name": spec["name"], "contact_organization": org,
                "contact_department": dept, "contact_position": pos, "contact_name": name,
                "contact_phone_cipher": store.runtime.encrypt(phone, spec["id"] + ":phone"),
                "status": "PREPARING", "created_by": ADMIN})
            c.execute("INSERT INTO project_evaluation_dates(project_id,evaluation_date,updated_at) VALUES(?,?,?) "
                      "ON CONFLICT(project_id) DO UPDATE SET evaluation_date=excluded.evaluation_date,updated_at=excluded.updated_at",
                      (spec["id"], date, now()))
        vendors = []
        for i, (legal_name, _path) in enumerate(spec["vendors"]):
            vid = f"{spec['id']}-v{i + 1}"
            if not c.execute("SELECT 1 FROM project_vendors WHERE id=?", (vid,)).fetchone():
                insert(c, "project_vendors", {"id": vid, "project_id": spec["id"], "display_code": chr(65 + i),
                                              "legal_name": legal_name, "sort_order": i + 1, "active": 1})
            vendors.append({"id": vid, "display_code": chr(65 + i), "legal_name": legal_name})
    return vendors


def seed_documents(store: Store, database: Path, samples: Path, spec: dict, vendors: list[dict]) -> None:
    pid = spec["id"]
    from app.documents.rfp_workflow import latest_rfp
    if latest_rfp(database, pid) is None:
        source = samples / spec["rfp"]
        upload = save_rfp(database, pid, spec["name"], source.name, source.read_bytes())
        binding = {"project_id": pid, "upload_revision": upload["revision"],
                   "document_id": upload["document_id"], "parse_revision": upload["parse_revision"]}
        with store.connect(write=True) as db:
            ref(db, "ref_rfp_bindings", binding | {"id": digest(binding)}, upload["revision"])
        print(f"  제안요청서 등록: {source.name} ({upload['page_count']}쪽)")
    ready = proposal_uploads.latest_ready(database, pid)
    for vendor, (_name, rel) in zip(vendors, spec["vendors"]):
        if vendor["id"] in ready:
            continue
        source = samples / rel
        if not source.is_file():
            print(f"  [건너뜀] 파일 없음: {rel}")
            continue
        with store.connect() as db:
            minimum_revision = db.execute(
                "SELECT COALESCE(MAX(upload_revision),0)+1 FROM ref_proposal_uploads "
                "WHERE project_id=? AND vendor_id=?", (pid, vendor["id"])
            ).fetchone()[0]
        try:
            upload = proposal_uploads.register_proposal(
                database, project_id=pid, project_name=spec["name"], vendor_id=vendor["id"],
                filename=source.name, data=source.read_bytes(), uploaded_by=ADMIN,
                minimum_revision=minimum_revision)
        except RuntimeError as exc:  # pypdf / python-pptx 미설치
            print(f"  [건너뜀] {vendor['display_code']}사 {source.suffix}: {exc}")
            continue
        except ValueError as exc:
            print(f"  [건너뜀] {vendor['display_code']}사 {source.name}: {exc}")
            continue
        ack = apply_event(store, event_envelope("proposal.ready", upload["id"],
                                                proposal_uploads.ready_event(upload)), "documents")
        print(f"  {vendor['display_code']}사 제안서 등록: {source.name} ({upload['pages']}쪽) → 평가 연결 {ack['status']}")


def seed_criteria(store: Store, database: Path, spec: dict) -> None:
    pid = spec["id"]
    versions = criteria_review.list_versions(database, pid)
    if any(v["status"] == "APPROVED" for v in versions):
        return
    draft = criteria_review.open_draft(database, project_id=pid, source="template", ai_result=None, actor_id=ADMIN)
    # 기본 서식 복사본에 근거 쪽이 없으면 제안요청서의 평가표 쪽(없으면 1쪽)을 채워 확정한다.
    page = next((i["source_page"] for i in draft["items"] if i["source_page"]), None) or 1
    items = [{"code": i["code"], "parent_code": i["parent_code"], "title": i["title"], "description": i["description"],
              "max_score": i["points"], "source_page": i["source_page"] or page, "sort_order": i["sort_order"]}
             for i in draft["items"]]
    draft = criteria_review.save_draft(database, project_id=pid, draft_id=draft["id"], version=draft["version"],
                                         items=items, total_points=draft["total_points"])
    saved, payload = criteria_review.approve_criteria(database, project_id=pid, draft_id=draft["id"],
                                                        version=draft["version"], actor_id=ADMIN, confirmed=True)
    ack = apply_event(store, event_envelope("criteria.approved", saved["id"], payload), "documents")
    print(f"  평가표 확정: {saved['total_points']:g}점 · {len(saved['items'])}항목 → 평가 연결 {ack['status']}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, required=True, help="제안요청서·제안서 샘플 폴더")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/database")
    parser.add_argument("--documents-db", type=Path, help="--data-dir의 복사본과 함께 사용할 문서 DB")
    args = parser.parse_args()
    store = await setup(args.data_dir.resolve(), True, None)
    database = resolve_database(args.documents_db, args.data_dir.resolve())
    seed_catalog(store)
    await seed_pool(store)
    for spec in PROJECTS:
        print(f"사업: {spec['name']}")
        vendors = seed_project(store, spec)
        deliver_outbox(store)
        seed_documents(store, database, args.samples, spec, vendors)
        if spec["approve_criteria"]:
            seed_criteria(store, database, spec)
    deliver_outbox(store)
    print("완료")


if __name__ == "__main__":
    asyncio.run(main())
