# 문서 파싱·저장

- `hwpx_parser.py`: HWPX의 쪽·문단·표·그림을 추출합니다.
- `hwpx_storage.py`: 파싱 결과와 원본 파일을 SQLite에 저장합니다.
- `rfp_toc.py`: 파싱된 제안요청서의 인쇄 목차와 실제 쪽을 연결합니다.
- `documents_parse.sqlite3`: 현재 서비스가 사용하는 문서 데이터입니다. 기존 업로드 문서를 유지하려면 함께 보관합니다.
- `step3_ai_requirements_extract_to_SQLite.py`: 별도 AI 요구사항 추출 모듈입니다.

메인 서버의 `app.api.project_documents`가 파서와 저장 함수를 사용합니다.
`apps/server/app/documents/__init__.py`는 기존 `app.documents.*` import가
이 폴더의 모듈을 찾도록 경로를 연결합니다. 문서 파싱 코드는 이 폴더에서 수정합니다.
