# 통합 보완 기록 — 2026-10-18 (v0.1 → 전 과정 실행 가능)

사용자 요구 프로세스(위원풀 → 사업·제안요청서 → 평가기준 → 3배수·연락·명단 확정 → 제안서 등록 → 위원 로그인·참석 → 위원장 → 평가·제출 → 집계·최종 제출 → 결과 열람·보관)를 끝까지 실행할 수 있도록 보완했다. 기존 액션 ID·함수명·화면 ID는 바꾸지 않았고, 문서 쪽 추가 모듈은 인계서 v2(§15)에 적힌 파일·함수 이름을 그대로 썼다.

## 1. 고친 버그·규칙

| 구분 | 내용 | 파일 |
|---|---|---|
| 버그 | `from signature_service import …` 모듈 경로 오류로 위원 제출(SCO-05)·위원장 최종 제출(RES-04)이 500으로 실패하던 문제 | `apps/server/app/evaluation/evaluation_service.py`, `result_service.py` |
| 규칙 | 정원 7~9 → **5~9** (화면·pydantic·서버·DB CHECK). SQLite CHECK는 표 재작성 마이그레이션으로 변경 | `migrations/admin/20261018_yujin_admin_004.sql`, `migrations/evaluation/20261018_yujin_evaluation_004.sql`, `app/shared/db.py`(`-- foreign_keys=OFF` 표식 마이그레이션 지원), `v2_contracts.py`, `evaluation_service.py`, `design_runtime.py`(PM-04 원본 상수 패치), `web_v2/index.html`, contracts JSON 문구 |
| 규칙 | 예비위원 **1~3명(권장 2명)** 강제(ROS-05 `RESERVE_COUNT`), 화면 점검 항목 추가. 직접 선정은 담당자가 체크한 본위원 수(5~9)가 정원이 되고 확정 때 규칙을 자동으로 맞춤(DRAW-01 후 ROS-05) | `committee_roster.py`, `v2_contracts.py`, `design_runtime.py`, `PM-04-committee/binding.js` |
| 보완 | 삭제(비활성)된 직접 등록 후보가 PM-04 목록에 남던 문제 | `committee_roster.py` `list_nominees` |
| 보완 | 확정명단 다운로드(ROS-06)에 분야·휴대전화와 후보 3배수 목록 추가 | `committee_roster.py` |
| 보완 | PM-05 참석 현황 5초 자동 갱신, 참석 확인이 정원에 이르면 안내 표시, 예비 순위 표시 | `PM-05-attendance-chair/binding.js` |
| 보완 | 업로드 본문 크기 제한을 제안서·결과 자료 경로에도 50MB 적용 | `committee_app/limits.py` |

## 2. 문서 쪽 연결 (오대웅 DaeUng79 모듈 검토 대상)

설계도 이름 그대로 새 파일을 두었다. 파싱·저장·AI는 기존 코드(`hwpx_parser`, `hwpx_storage`, `step3`, `step4`)를 그대로 부른다.

| 설계 모듈 | 파일 | 함수 | 화면 |
|---|---|---|---|
| RFP | `apps/documents/rfp_api.py` | `latest_rfp`, `queue_requirements`, `requirement_status`, `queue_criteria`, `queue_pipeline`, `criteria_status` (원본 step0 작업 큐 이식) | PM-02 더 보기, PM-03 |
| CRITERIA | `apps/documents/criteria_approval.py` | `open_draft`, `save_draft`, `approve_criteria` + 표 `approved_criteria_versions`/`approved_criteria_items` | PM-03 (CRT-03~05) |
| PROPOSAL | `apps/documents/proposal_document_adapter.py` | `register_proposal`, `list_proposals` + 표 `project_proposal_uploads` | PM-02 (PRO-01·02) |
| DOC | `apps/documents/document_gateway.py` | `list_uploads`, `view_source`, `archive_upload` + 표 `rfp_upload_visibility` | PM-02 (DOC-02·05·06, PRO-03) |
| MATERIAL | `apps/documents/material_service.py` | `register_result_file`, `revise_result_file`, `list_materials` + 표 `managed_result_files` | SA-04 (MAT-01~03) |
| 파서 | `apps/documents/pdf_parser.py`, `pptx_parser.py` | `parse_pdf`, `parse_pptx` (같은 문서 JSON 모양) | 제안서 PDF·PPTX |
| DRAFT | `apps/documents/step4_ai_criteria.py` | 원본 저장소에서 복사(import 경로만 수정) | AI 평가기준 초안 |
| 서버 | `apps/server/app/api/document_module_routes.py` | `/api/v2/projects/{id}/requirements`, `/criteria`, `/criteria-drafts`, `/vendors/{vid}/proposals`, `/proposals/{id}`, `/result-files`, `/api/v2/materials` | — |

평가 DB 전달은 `criteria.approved`, `proposal.ready`, `proposal.archived` 계약을 `apply_event(store, envelope, "documents")`로 보낸다. 제안서 형식은 설계의 HWPX/PDF에 샘플 자료의 HWP/PPTX를 더했다(`integration_contracts.py`).

설계와 다른 점(검토 요청): 문서 DB에 `ref_project_vendors`·`ref_admin_users`·`criteria_results` 사본이 없어 그 외래키는 선언하지 않고 서버가 관리 DB로 확인한다. `approved_criteria_items`에 화면의 '근거 쪽'을 담는 `source_page` 열을 더했다. 설계의 `/document-api/...` 경로는 기존 제안요청서 라우트처럼 `/api/v2/...` 아래에 두었다.

## 3. 결과·자료

- RES-05에 `format: "xlsx"`를 주면 공식 **제안서평가 집계표(정성)** 서식(`집계표` + 위원별 시트)으로 내려받는다(`app/evaluation/result_workbook.py`). PM-06·SA-03·SA-04는 xlsx, EV-07은 서명 증빙 HTML.
- SA-04 자료 탭: 사업별 제안요청서(최신)·제안서(업체별 최신)·결과 자료·확정 결과를 한 목록으로, 결과 첨부자료 등록(MAT-02)·새 버전(MAT-03) 동작.
- SA-03 사업 상세: 제안서 원본 내려받기 추가.

## 4. 가상 데이터

- `apps/server/app/shared/sample_pool.py`: 가상 위원 72명(10개 분야) + 엑셀 업로드 테스트용 18명.
- `apps/server/seed_samples.py --samples "<샘플 폴더>"`: 위원풀 등록, 사업 3개(공공의료 AI·업무자동화 RPA·마이데이터)와 제안요청서(HWPX)·업체별 제안서 등록, 공공의료 사업 평가표 확정. 멱등. PDF·PPTX 제안서는 `pypdf`·`python-pptx`가 설치된 뒤 다시 실행하면 들어간다.
- 복사본으로 시딩할 때는 `--data-dir <관리·평가 DB 복사본 폴더> --documents-db <문서 DB 복사본 경로>`를 함께 지정한다.
- 데모 DB 검증은 임시 복사본에서 수행한다. 기존 DB와 키 파일은 코드 통합 과정에서 복사하거나 덮어쓰지 않는다.

## 5. 검증

- 마이그레이션: 기존 데모 DB 사본과 새 DB에서 모두 적용, `PRAGMA foreign_key_check` 0행, `integrity_check` ok, 트리거 복원 확인.
- 복사본 DB로 띄운 서버(포트 5199)에 HTTP로 전 과정 자동 시험(스크립트: 세션 scratchpad `e2e/e2e.py`): 관리자 로그인 → 화면 8개 렌더 → 정원 4 거부/5 저장 → 3배수 추첨(15명) → 예비 1명 거부/5+2 확정 → 확정명단 xlsx → 위원 5명 로그인·참석 → 회차 준비(정원 5)·인원 확정·위원장·평가 시작 → 5명 채점·서명·제출 → 위원장 집계(최고·최저 제외)·서명·최종 제출 → 집계표 xlsx·서명증빙 HTML → 사업 COMPLETED → 자료 목록·결과 자료 등록·새 버전 → 제안서 HWPX 업로드(17MB)·목록·원본·파싱 원문·형식 거부 → 평가표 서식 복사본·배점 합 거부·저장·확정(평가 DB 수신 APPLIED) → 제안서 보관 처리. **실패 0.**
- PPTX 파서: 샘플 2건(32MB·44MB) 파싱·저장·조회 확인. PDF 파서는 `pypdf` 미설치로 정적 검토만.
- 브라우저에서 사람이 직접 눌러 보는 검수는 하지 않았다.
- `gg verify`: 이 저장소에 하네스가 초기화되어 있지 않아 **판정 불가**("하네스가 초기화되지 않았습니다").

## 5-1. PM-04 사용성 보완 (같은 날 오후, 사용자 요청)

`apps/web/src/screens/dept-admin/PM-04-committee/binding.js`만 수정(원본 HTML 무수정).

- 사업 후보 추가 창: 너비 960px, 이름·소속·직위·분야 검색, 체크박스 다중 선택 → [선택 N명 추가] 한 번에 저장(ROS-02 반복 호출), "보이는 위원 모두 선택".
- 연락·초청: 통화 결과 드롭다운 → 체크박스(완료/미완료). 서버 값은 그대로(완료=AVAILABLE, 미완료=NOT_CONTACTED). 칩은 전체/완료/미완료.
- 명단 확정: 지정 드롭다운 → [본위원]·[예비] 체크박스, 예비 순서는 체크한 순서로 자동, 본위원 9명·예비 3명이 차면 나머지 잠김. 직접 선정은 체크한 본위원 수가 정원. 확정 버튼이 꺼진 이유를 버튼 옆에 표시.
- 검증: `apps/server/tests/ui_pm04_committee.py` — Chrome 헤드리스로 실제 클릭(후보 추가 → 통화 완료 9명 → 본위원 7+예비 1 잠김 확인 → 예비 2 → 확정 → 서버 명단 7+2, 수신 SENT). 콘솔 오류 0, PASS.

## 6. 남은 일

- 패키지 설치(사용자 직접): `pypdf`, `python-pptx`(제안서 PDF·PPTX), `openai`, `tiktoken`, `python-dotenv`(AI 초안·챗봇). `.env`의 `OPENAI_API_KEY`는 저장소 루트에 두었다(.gitignore 대상).
- 목차 수정(TOC 확인)·근거 연결(PM-08, PRO-04·05)·챗봇 UI 연결은 그대로 미연결.
- `contracts/actions_v2.json`의 `in_scope` 값은 설계 당시 범위 표시라 바꾸지 않았다.

## 7. 메인 프로젝트 통합 보완

- 보관한 제안서는 문서 DB에서 버전을 올린 뒤 `proposal.archived` 계약으로 평가 DB에도 `ARCHIVED` 상태를 전달한다. 전달이 실패하면 기존 재전송 API가 보관 상태와 버전을 다시 보낼 수 있다.
- 제안요청서의 최신본 조회, AI 작업 대상, 미리보기, 관리자 목록에서 보관한 업로드를 제외한다. 차수를 명시한 과거 원본 조회는 유지한다.
- 업체별 제안서 새 차수는 문서 DB와 평가 DB의 기존 최대 차수보다 크게 정한다. 기존 데모 평가 스냅샷과 새 문서 DB의 차수 충돌을 막는다.
- 새 데모 DB는 본위원 7명과 예비위원 1명으로 확정한다. 기존 데모 DB는 변경하지 않는다.
- 계약 JSON의 줄바꿈·정렬은 유지하고 정원 5~9명에 해당하는 실제 값만 수정했다. 내용 변화가 없는 `actions_v2.json`과 `.DS_Store`는 가져오지 않았다.
- 검증: 새 데모 DB와 기존 DB 복사본의 마이그레이션 및 외래키·무결성 검사, 8개 화면과 문서 API 응답, PDF 제안서 HTTP 등록→보관→평가 DB 상태 반영, 보관한 제안요청서의 최신본 제외를 확인했다. 기존 작업자의 전 과정 시험 기록은 별도로 재현하지 않았다.
- `apps/server/tests/test_document_archive_sync.py`가 제안서 보관 상태 전달과 제안요청서 최신본 제외를 회귀 검사한다. PM-04 브라우저 시험 스크립트는 macOS·Windows의 Chrome 실행 경로를 찾고 `CHROME_BIN`도 받는다.

## 8. 사업 삭제 이력 분리

- `5topilot_team-main_20261017`의 PM-01 삭제 이력 설계를 통합 서비스에 연결했다. 사업목록 상태 선택에 전체선택·준비·평가·완료·삭제를 두고, 삭제 이력의 읽기 전용 상세 화면을 제공한다.
- `PRJ-04`는 준비 중이며 평가 회차가 없는 사업만 삭제한다. 삭제 전 사업 정보·사유·요구사항 요약은 데이터 폴더의 `projects_delete.sqlite3`에 저장하고, 관리 DB의 사업은 삭제 표시한다. 전화·이메일은 기존 키로 암호화해 보관한다.
- 통합 서비스에서는 사업과 연결된 위원·평가·감사 기록의 외래키를 보존해야 하므로 원본 사업·문서·평가 데이터를 물리 삭제하지 않는다. 삭제 사업은 활성 목록에서 제외한다.
- 기존 DB에서 이미 삭제 표시된 사업은 서버 시작 시 삭제 이력 DB로 이관한다. 과거에 보관하지 않은 삭제 전 상태와 사유는 추정하지 않고 ‘미기록’으로 표시한다.
- 임시 DB 단위 시험 3개와 실제 DB 복사본의 과거 기록 2건 이관·무결성 검사를 통과했다. 실행 중인 5192 서비스의 Chrome 화면에서 상태 선택 5개, 삭제 목록 2건, 기록 상세와 JavaScript 오류 0건을 확인했다.

## 9. 문서 DB 위치 통일

- 문서 DB의 기본 파일을 `apps/documents/documents_parse.sqlite3`에서 `apps/server/data/database/documents_parse.sqlite3`로 이동했다. 파서·저장 코드는 `apps/documents`에 유지한다.
- `--data-dir`을 지정하면 문서 DB도 해당 데이터 폴더의 `documents_parse.sqlite3`를 사용한다. `--documents-db`와 `EVAL_DOCUMENTS_DB_PATH`는 기존 우선순위를 유지한다.
- 기존 문서 데이터는 원본 파일을 이동해 보존하고, 관리자·평가·문서 라우트와 샘플 시딩이 동일한 경로 결정 함수를 사용하게 했다.
