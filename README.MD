# 심사 서비스 v0.1

공공 제안평가를 지원하는 로컬 웹 서비스입니다. Python 3.13과 FastAPI/Uvicorn으로 화면과 API를 함께 제공하므로 별도 Node.js 또는 Vite 서버는 필요하지 않습니다. 기본 주소는 `http://127.0.0.1:5190/`입니다.

## 주요 기능과 구성

```mermaid
flowchart TB
    B[브라우저] --> H[FastAPI · Uvicorn<br/>apps/server/run.py]
    H --> UI[화면 라우팅 · 정적 파일]
    UI --> W[apps/web<br/>runtime · screens · bindings]
    UI --> EV[apps/web/src/evaluator<br/>EV-03 · EV-04 · EV-05]
    H --> API[/api/v2/actions/{action_id}]
    API --> AUTH[인증 · 권한 확인]
    API --> G[업무 액션 게이트웨이]
    G --> ADMIN[관리자 · 부서 · 사업]
    G --> COM[후보 · 추첨 · 위원 명부]
    G --> EVAL[출석 · 평가 · 서명 · 결과]
    EV --> DOCAPI[/api/v2/evaluator]
    DOCAPI --> DOC[문서 열람 · 근거 비교]
    DOC --> DOCDB[(문서 파싱 DB<br/>읽기 전용)]
    DOC --> CHAT[챗봇 모듈<br/>선택 기능]
    ADMIN --> DB[SQLite 데이터베이스]
    COM --> DB
    EVAL --> DB
```

- `/`은 역할 선택 화면으로 이동합니다. 화면 원본은 `apps/web/src/runtime`에, 화면별 기능 연결 코드는 `apps/web/src/screens`와 `apps/web/src/bindings`에 있습니다.
- `/api/v2/actions/{action_id}`는 로그인, 저장, 조회 등의 업무 요청을 처리합니다.
- `/committee-v2/`는 위원회 화면을 제공합니다.
- EV-03·EV-04·EV-05는 평가위원용 문서 열람과 업체별 비교 기능입니다. 문서 API는 기존 로그인과 권한을 사용합니다.
- 관리자·위원회 데이터와 평가·결과 데이터는 별도 SQLite DB에 저장되며, 두 영역 간 자료 전달은 공통 동기화 서비스를 사용합니다.
- `/api/v2`의 `v2`는 API 버전입니다. 프로젝트 버전 `v0.1`과는 별개의 표기이므로 변경하지 않습니다.

## 파일 구성

```text
.
├── README.MD
├── start_service.py                  # 로컬 데모 실행기
├── start_simsa_v2.py                 # 이전 명령 호환 실행기
├── start_simsa_v2.cmd                # Windows 실행 바로가기
├── docs/
│   └── EVALUATOR_DOCUMENT_INTEGRATION.md
└── apps/
    ├── web/
    │   ├── src/
    │   │   ├── runtime/              # HTML · CSS · JavaScript 화면
    │   │   ├── screens/              # 화면별 기능 연결
    │   │   ├── evaluator/            # EV-03·04·05 문서·비교 기능
    │   │   └── bindings/             # 공통 화면 기능
    │   └── public/
    │       └── fonts/                # Pretendard GOV 글꼴
    ├── documents/
    │   ├── step3_ai_requirements_extract_to_SQLite.py
    │   └── requirements.txt          # 문서·AI 선택 의존성
    ├── chatbot/
    │   └── chatbot.py                # AI 답변 모듈
    └── server/
        ├── run.py                    # FastAPI 시작·데모 초기화
        ├── requirements.txt          # 서버 실행 의존성
        ├── app/
        │   ├── api/                  # HTTP 라우팅·액션·화면 연결
        │   ├── admin/                # 계정·부서·사업·대시보드
        │   ├── committee/            # 후보·선정·명부·위원회 화면
        │   ├── evaluation/           # 출석·평가·서명·결과
        │   └── shared/               # DB·데모 데이터·동기화·계약
        ├── contracts/                # API·데이터 계약
        ├── fixtures/                 # 초기 공통 데이터 SQL
        ├── migrations/               # 관리자·평가 DB 변경
        └── data/                     # 로컬 실행 데이터
```

## 실행 방법

Python 3.13이 설치된 환경에서 프로젝트 루트에서 실행합니다. 기관·운영 환경에서는 패키지 설치 전에 해당 환경의 승인 정책을 확인하세요.

### macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r apps/server/requirements.txt
.venv/bin/python start_service.py
```

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/server/requirements.txt
.venv\Scripts\python.exe start_service.py
```

브라우저에서 `http://127.0.0.1:5190/`을 엽니다. 서버를 종료하려면 실행 터미널에서 `Ctrl+C`를 누릅니다. 포트를 바꾸려면 `start_service.py --port 5191`처럼 지정하고 해당 포트로 접속하세요. 기본 포트는 `5190`입니다.

`start_service.py`는 현재 실행한 Python 인터프리터로 `apps/server/run.py`를 실행하고 합성 데모 데이터를 위한 `--demo` 옵션을 자동 전달합니다. 비데모 서버는 별도의 데이터 폴더를 지정해 직접 실행합니다.

```bash
.venv/bin/python apps/server/run.py --port 5191 --data-dir apps/server/data/production
```

비데모 모드는 처음 실행할 때 비어 있는 DB를 사용하므로 계정과 업무 데이터를 등록해야 로그인 및 평가가 가능합니다. 데모와 비데모 데이터를 분리하고, 기존 데이터를 이동할 때는 DB와 해당 암호화 키를 함께 유지하세요.

### 실행 옵션

| 옵션 | 설명 |
|---|---|
| `--demo` | 합성 시연 계정과 데이터를 초기화합니다. `start_service.py`가 자동으로 전달합니다. |
| `--port 5190` | 로컬 서버 포트를 지정합니다. 예: `--port 5191`. |
| `--data-dir 경로` | DB와 로컬 키 파일을 저장·읽을 데이터 폴더입니다. 데모·비데모 폴더를 분리하세요. |
| `--samples 경로` | 선택적인 샘플 문서 폴더입니다. |
| `--documents-db 파일` | 문서 파싱 SQLite를 읽기 전용으로 연결합니다. 생략하면 `EVAL_DOCUMENTS_DB_PATH` 또는 `apps/documents/documents_parse.sqlite3`를 사용합니다. 상대 경로는 프로젝트 루트 기준입니다. |
| `--original-ui` | 원본 화면에 기능 코드를 연결합니다. 현재 기본값이 활성화되어 있습니다. |

### 데모 계정

아래 계정은 로컬 데모 데이터에만 사용하세요.

| 역할 | 계정 또는 이름 | 비밀번호 또는 휴대전화 뒤 4자리 |
|---|---|---|
| 총괄관리자 | `super-demo` | `DemoOnly!2026` |
| 사업담당자 | `web-demo` | `DemoOnly!2026` |
| 평가위원 | `가상위원01` ~ `가상위원07` | `0001` ~ `0007` |

평가위원은 초청된 사업을 선택해야 할 수 있습니다. 이 데모 계정을 운영 환경에 사용하지 마세요.

## 데이터 및 공개 저장소 주의사항

- SQLite DB, `keys.bin`, `access-code.txt`, 데이터 매니페스트, 개인 후보 명부 fixture는 로컬 데이터 또는 배포용 파일입니다. 공개 GitHub 저장소에는 올리지 않습니다.
- 로컬의 `apps/server/data/database`와 `apps/documents/documents_parse.sqlite3`는 `.gitignore` 대상입니다. 필요한 데이터는 신뢰할 수 있는 별도 경로에서 준비하세요.
- `keys.bin`은 대응하는 암호화 데이터와 함께 보관해야 합니다. 키를 잃으면 해당 데이터에 접근하지 못할 수 있습니다.
- 배포용 데이터 파일에는 개인정보나 접속 정보가 있을 수 있으므로 접근을 제한하고, 공개 저장소에 포함되지 않았는지 확인하세요.

## 문서 열람·AI 기능의 제한

- 문서 비교 기능은 별도 문서 파싱 SQLite를 읽습니다. 문서 DB를 준비하지 않으면 원문 문서가 표시되지 않을 수 있습니다.
- 현재 평가 DB에 기록된 문서 참조 3건은 문서 DB의 파싱 버전과 연결되지 않아 실제 문서가 표시되지 않습니다.
- AI 답변과 원본 SVG 렌더링에는 별도 패키지 또는 설정이 필요합니다. 기본 서버 실행에 필수는 아닙니다.
- EV-03·04·05 기능과 검증 범위의 자세한 설명은 [평가위원 문서 통합 설명](docs/EVALUATOR_DOCUMENT_INTEGRATION.md)을 참고하세요.

## 검증 범위

2026-10-18 기준 통합 테스트 6개와 브라우저 문서 열람·비교 흐름이 통과했습니다. 별도 빈 DB를 사용하는 비데모 실행에서도 첫 화면 응답과 DB 무결성을 확인했습니다. Windows에서의 실제 실행은 검증하지 않았습니다.

전체 `gg verify --run-tests`는 Python 환경에 `pytest`가 설치되지 않았고 npm 테스트 명령이 설정되지 않아 완료되지 않았습니다. 개별 동작 확인이 전체 검증이나 운영 배포 검증을 의미하지는 않습니다.
