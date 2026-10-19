# PM-02 · 코드

| 항목 | 내용 |
|---|---|
| 화면 기획 | [v2/사업담당자/PM-02-문서-목차/](../../../../v2/사업담당자/PM-02-문서-목차/) |
| 팀 버튼 ID | DOC-01~06 · PRJ-06·07 · PRO-01~03 |
| 상태 | 제안요청서 HWPX 업로드·파싱·원본 저장·조회 연결 |

규칙: 이 폴더 파일 맨 위에 `// PM-02 · PRJ-02 · DOC-01·02·04·05·06` 를 적는다. DB 경로나 SQL은 넣지 않고 API(기능 출력 모양)만 쓴다.

제안요청서 파일은 메인 FastAPI의 `POST /api/v2/projects/{id}/rfp`로 전송한다.
파싱 결과와 원본은 `--documents-db`의 SQLite에 저장하고, 평가위원 열람용
문서 버전을 평가 DB에 고정 연결한다. `GET /api/v2/projects/{id}/rfp`로
업로드 이력을 읽고 `/source`, `/download`로 저장된 문단·표 및 원본을 확인한다.
등록 화면의 `제안요청서 확인` 버튼은 담당자 전용
`/app/dept-admin/PM-02/design/rfp-preview.html?project_id={id}`를 연다.
이 화면은 최신 업로드의 고정 파싱 버전을 `/rfp/preview`와
`/rfp/preview/pages/{n}`에서 읽고, `/rfp/preview/pages/{n}/svg`로 원본 쪽을 렌더링한다. 렌더링할 수 없으면 저장된 파싱 내용을 보여준다. 평가위원 EV-03은 별도 로그인과
참석 확인을 요구한다.
업체별 제안서 등록·이력·원본·보관 처리(PRO-01~03)는 `POST /api/v2/projects/{id}/vendors/{vendor_id}/proposals`, `GET .../proposals`, `.../proposals/{id}/download|source`, `DELETE .../proposals/{id}`로 연결했다(HWPX·HWP·PDF·PPTX, 2026-10-18). 요구사항 추출 상태·재시도(DOC-03·04)는 `.../requirements`, `.../requirements/jobs`. 목차 수정은 아직 연결되지 않았다.

제안요청서를 등록하거나 재등록하면 서버가 요구사항 요약 작업을 자동으로 시작한다. 화면은 작업 상태를 5초 간격으로 갱신하며, 저장과 추출이 모두 성공한 경우에만 `✓ 완료`를 표시한다. API 키·통신·추출 오류가 나면 원본 보존과 실패 이유, 다시 시도 동작을 표시한다. 완료 후 `요구사항 요약`과 `제안요청서 확인` 버튼이 활성화된다.
