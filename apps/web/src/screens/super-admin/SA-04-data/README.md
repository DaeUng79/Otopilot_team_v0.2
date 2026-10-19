# SA-04 · 코드

| 항목 | 내용 |
|---|---|
| 화면 기획 | [v2/총괄관리자/SA-04-자료-관리/](../../../../v2/총괄관리자/SA-04-자료-관리/) |
| 팀 버튼 ID | MAT-01~03 |
| 상태 | 코드 ✅ 2026-10-18 연결 — MAT-01 `GET /api/v2/materials`, MAT-02 `POST /api/v2/projects/{id}/result-files`, MAT-03 `POST .../result-files/{id}/revisions`, 결과 집계표 RES-05 format=xlsx |
| 자료 등록 유형 | [자료 등록] 창에서 유형을 고른다 — 제안요청서 → DOC-01 `POST /api/v2/projects/{id}/rfp`(전체 사업 SA-03 준비 상태와 같은 표), 업체별 제안서 → PRO-01 `POST .../vendors/{vendor_id}/proposals`, 평가결과 첨부자료 → MAT-02. 유형을 고르지 않으면 등록되지 않는다 (2026-10-18, 제안요청서가 결과 자료로 저장되던 문제 수정) |

규칙: 이 폴더 파일 맨 위에 `// SA-04 · DOC-01 · COM-01` 를 적는다. DB 경로나 SQL은 넣지 않고 API(기능 출력 모양)만 쓴다.
