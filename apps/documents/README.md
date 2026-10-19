# 제안요청서 처리 단계

| 단계 | 실행 파일 | 역할 | 서비스에서 호출하는 곳 |
| --- | --- | --- | --- |
| 1 | `step1_hwpx_parse_to_JSON.py` | HWPX를 문서 JSON과 이미지로 파싱 | 제안요청서 업로드 |
| 2 | `step2_hwpx_save_to_SQLite.py` | JSON·원본을 문서 DB에 저장 | 제안요청서 업로드 |
| 3 | `step3_ai_requirements_extract_to_SQLite.py` | 저장된 문서에서 사업 현황·요구사항을 추출해 DB에 저장 | 업로드 직후 자동 작업 |

서비스는 업로드 사업의 문서 버전을 연결하기 전에 인쇄 목차를 실제 쪽에 매핑해 `rfp_toc_snapshots`에 저장하고, 이어서 3단계 작업을 시작합니다. 목차는 요구사항 추출 중에도 제안요청서 확인 화면에서 사용할 수 있습니다. 작업 상태가 `done`이고 저장된 결과를 읽을 수 있을 때 화면에 `✓ 완료`를 표시합니다. 1·2단계 파일은 유지보수용 진입점이며, 실제 파싱·저장 구현은 아래 모듈에 둡니다.

수동으로 각 단계를 점검할 때는 프로젝트 루트에서 실행합니다. 2단계를 수동으로 실행해도 서비스의 업로드 이력 등록은 별개이므로, 화면에서 새 버전을 등록하려면 서비스에서 업로드해야 합니다.

```bash
python -m apps.documents.step1_hwpx_parse_to_JSON 원본.hwpx --output-json /tmp/rfp.json
python -m apps.documents.step2_hwpx_save_to_SQLite /tmp/rfp.json --source 원본.hwpx
python -m apps.documents.step3_ai_requirements_extract_to_SQLite --document-id 문서ID
```

2·3단계의 기본 DB는 `apps/server/data/database/documents_parse.sqlite3`입니다. 다른 데이터 폴더를 사용한다면 각 명령에 `--database 경로`를 지정합니다. 1단계의 이미지 폴더 기본값은 출력 JSON과 같은 위치의 `rfp.assets`입니다.

- `hwpx_parser.py`: HWPX의 쪽·문단·표·그림을 추출합니다.
- `hwpx_storage.py`: 파싱 결과와 원본 파일을 SQLite에 저장합니다.
- `rfp_toc.py`: 파싱된 제안요청서의 인쇄 목차와 실제 쪽을 연결하고 문서 버전별 목차를 저장합니다. 본문 제목으로 확인할 수 없는 항목은 확인 필요로 표시합니다.
- `apps/server/data/database/documents_parse.sqlite3`: 현재 서비스가 사용하는 문서 데이터입니다. 파서 코드는 이 폴더에 두고, SQLite 파일은 관리·평가 DB와 같은 데이터 폴더에 보관합니다. `--data-dir`을 지정하면 그 폴더의 문서 DB를 사용합니다.
- `step3_ai_requirements_extract_to_SQLite.py`: 별도 AI 요구사항 추출 모듈입니다.

메인 서버의 `app.api.project_documents`가 파서와 저장 함수를 사용합니다.
`apps/server/app/documents/__init__.py`는 기존 `app.documents.*` import가
이 폴더의 모듈을 찾도록 경로를 연결합니다. 문서 파싱 코드는 이 폴더에서 수정합니다.
