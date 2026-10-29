# 문서 서비스 파일과 처리 흐름

파일명은 형식별 파서(`parser_*`)와 업무 대상(`rfp_*`, `requirements_*`, `criteria_*`, `proposal_*`)으로 묶습니다. 번호가 아닌 아래 흐름으로 실행 순서를 확인합니다.

| 순서 | 처리 | 주요 파일 |
| --- | --- | --- |
| 1 | 제안요청서 HWPX 파싱·저장·목차 연결 | `rfp_parse.py`, `rfp_store.py`, `rfp_toc.py`, `parser_hwpx.py`, `storage_documents.py` |
| 2 | 기존 요구번호 추출 또는 서술형 요구사항 명세서 생성·검토 | `requirements_extract.py`, `requirements_review.py` |
| 3 | 평가항목 초안 생성·검토·확정 | `criteria_generate.py`, `criteria_review.py` |
| 4 | 업체별 제안서 등록·파싱 | `proposal_uploads.py`, `parser_hwpx.py`, `parser_pdf.py`, `parser_pptx.py` |
| 5 | 요구사항과 제안서 원문 근거 대조 | `proposal_analysis.py`, `proposal_analysis_jobs.py` |

`rfp_workflow.py`는 요구사항·평가항목 작업 큐를, `document_gateway.py`는 원본 조회·보관·삭제를 맡습니다. `proposal_evidence_summary.py`는 평가위원의 제안서 근거 요약, `material_service.py`는 결과 자료 보관을 맡습니다. 이 표와 함께 폴더의 Python 파일 18개가 모두 서비스 경로에 연결됩니다.

서비스는 업로드 사업의 문서 버전을 연결하기 전에 인쇄 목차를 실제 쪽에 매핑해 `rfp_toc_snapshots`에 저장하고, 이어서 요구사항 분석 작업을 시작합니다. 목차는 분석 중에도 제안요청서 보기 화면에서 사용할 수 있습니다. 요구번호가 없는 서술형 제안요청서는 `requirements_review.py`의 명세서를 검토·확정해야 평가항목 생성으로 이어집니다. `rfp_parse.py`와 `rfp_store.py`는 업로드 API와 유지보수용 진입점이며, 실제 파싱·저장 구현은 `parser_hwpx.py`와 `storage_documents.py`가 맡습니다.

수동으로 파싱·저장을 점검할 때는 프로젝트 루트에서 실행합니다. `rfp_store.py`를 수동으로 실행해도 서비스의 업로드 이력 등록은 별개이므로, 화면에서 새 버전을 등록하려면 서비스에서 업로드해야 합니다.

```bash
python -m apps.documents.rfp_parse 원본.hwpx --output-json /tmp/rfp.json
python -m apps.documents.rfp_store /tmp/rfp.json --source 원본.hwpx
python -m apps.documents.requirements_extract --document-id 문서ID
```

제안서 대조 분석은 요구사항 분석(서술형은 명세서 확정 포함)이 완료되고 업체별 제안서가 `READY`인 뒤 실행합니다. 문서 화면의 `더 보기 → 요구사항 추출`에서 각 업체의 `분석하기` 버튼으로 해당 업체의 최신 제안서만 백그라운드 처리할 수 있습니다. 명령줄에서는 프로젝트의 최신 제안요청서와 업체별 최신 제안서를 한 번에 처리합니다. 먼저 API 호출 없이 대상과 검색 후보를 점검할 수 있습니다.

```bash
python -m apps.documents.proposal_analysis --project-id 프로젝트ID --dry-run
python -m apps.documents.proposal_analysis --project-id 프로젝트ID --export-dir /tmp/proposal-analysis
```

`--proposal-upload-id`로 한 제안서만 지정할 수 있습니다. `--database`와 `--model`도 지정할 수 있으며 기본 모델은 `gpt-4o`입니다. 프로젝트 루트 `.env` 또는 환경변수의 `OPENAI_API_KEY`가 필요합니다. 중간에 실패하면 같은 명령을 다시 실행하세요. 완료한 요구사항은 재사용하고 남은 항목만 호출합니다. 업체당 요구사항 수만큼 최대 OpenAI 호출이 발생하므로 호출량과 비용을 확인한 뒤 실행하세요.
`--max-new-items 1`처럼 지정하면 소량만 실제 호출해 점검할 수 있으며, 이때 전체 요구사항이 끝나기 전까지 완료 결과는 게시되지 않습니다.

결과는 문서 DB의 `proposal_analysis_items`(재시작용)와 `proposal_analysis_results`(완료 결과)에 저장됩니다. 완료 JSON은 요구사항 구분별로 요구사항 코드·명칭·제안서 확인 사항·원문 인용·물리 페이지를 포함합니다. 근거를 찾거나 검증하지 못한 항목은 `확인되지 않음`으로 기록합니다. 이는 제안서에 내용이 **없다는 판정이 아니라**, 파싱 및 검색된 텍스트에서 확인하지 못했다는 뜻입니다. 화면이나 챗봇 연결 시 `load_latest_analysis(database, project_id, proposal_upload_id)`로 현재 버전의 완료 결과만 읽을 수 있습니다. AI 요약은 평가점수나 적합 판정을 대신하지 않으며, 평가위원은 원문 페이지를 확인해야 합니다.
요약의 모든 주장에 제안서 원문 근거가 있는지 별도 모델 호출로 재검증하고, 제목만 있는 근거와 요구사항 충족 판정 문구는 보수적으로 미확인 처리합니다.

저장·분석 명령의 기본 DB는 `apps/server/data/database/documents_parse.sqlite3`입니다. 다른 데이터 폴더를 사용한다면 각 명령에 `--database 경로`를 지정합니다. 파싱 명령의 이미지 폴더 기본값은 출력 JSON과 같은 위치의 `rfp.assets`입니다.

- `parser_hwpx.py`: HWPX의 쪽·문단·표·그림을 추출합니다.
- `storage_documents.py`: 파싱 결과와 원본 파일을 SQLite에 저장합니다.
- `rfp_toc.py`: 파싱된 제안요청서의 인쇄 목차와 실제 쪽을 연결하고 문서 버전별 목차를 저장합니다. 본문 제목으로 확인할 수 없는 항목은 확인 필요로 표시합니다.
- `apps/server/data/database/documents_parse.sqlite3`: 현재 서비스가 사용하는 문서 데이터입니다. 파서 코드는 이 폴더에 두고, SQLite 파일은 관리·평가 DB와 같은 데이터 폴더에 보관합니다. `--data-dir`을 지정하면 그 폴더의 문서 DB를 사용합니다.
- `requirements_extract.py`: 별도 AI 요구사항 추출 모듈입니다.

메인 서버의 `app.api.project_documents`가 파서와 저장 함수를 사용합니다.
`apps/server/app/documents/__init__.py`는 기존 `app.documents.*` import가
이 폴더의 모듈을 찾도록 경로를 연결합니다. 문서 파싱 코드는 이 폴더에서 수정합니다.
