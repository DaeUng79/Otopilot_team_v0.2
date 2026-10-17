# 심사 서비스 상세 구성도와 실행 방법

이 문서는 현재 `apps/server`, `apps/web`, `apps/documents`, `apps/chatbot`으로 구성된 **단일 Python 서비스**를 설명합니다. `npm`이나 별도 Vite 서버 없이 FastAPI/Uvicorn이 화면과 API를 함께 제공합니다. 기본 포트는 `5190`이며 다른 서비스가 사용 중이면 `--port 5191`처럼 지정합니다. 현재 작업 폴더의 `5191` 서비스는 사용자 요청으로 **종료된 상태**입니다.

김유진 변경파일의 EV-03·04·05 기능을 통합했고, 문서·챗봇 모듈 폴더 이름을 `documents`, `chatbot`으로 정리했습니다. 상세 변경과 검증 범위는 [평가위원 문서 통합 설명](docs/EVALUATOR_DOCUMENT_INTEGRATION.md)을 참고하세요.

## 서비스 구성도

```mermaid
flowchart TB
    L[macOS 또는 Windows<br/>가상환경의 Python] --> MODE{실행 방식}
    MODE -->|데모| START[start_service.py<br/>--demo 자동 전달]
    MODE -->|비데모| DIRECT[apps/server/run.py<br/>--demo 없이 실행]
    START --> H[FastAPI · Uvicorn<br/>apps/server/run.py · app/api/web_api.py]
    DIRECT --> H
    U[브라우저<br/>localhost:5190 또는 5191] --> H
    H --> R[화면 라우팅<br/>/ → /app/entry/design/entry.html]
    R --> D[design_runtime.py<br/>원본 HTML에 화면별 binding 연결]
    D --> W[apps/web/src/runtime<br/>HTML · CSS · JS]
    D --> B[apps/web/src/screens<br/>화면별 binding.js]
    D --> C[apps/web/src/bindings<br/>공통 JS]
    H --> F[/src 정적 화면<br/>/fonts 글꼴]
    F --> W
    F --> FONT[apps/web/public/fonts]
    H --> V[/committee-v2<br/>위원회 화면 · 정적 자산]
    V --> VW[apps/server/app/committee/web_v2]
    H --> API[/api/v2/actions/액션ID<br/>로그인 · 저장 · 조회]
    API --> AUTH[app/admin/auth_service.py<br/>세션 · 권한 확인]
    API --> G[app/api/gateway.py<br/>액션ID → 서비스 함수]
    G --> A[app/admin<br/>관리자 · 부서 · 사업]
    G --> K[app/committee<br/>후보 · 추첨 · 명부]
    G --> E[app/evaluation<br/>출석 · 점수 · 서명 · 결과]
    D --> NEWUI[apps/web/src/evaluator<br/>EV-03 요청서 · EV-04 업체별 · EV-05 비교]
    NEWUI --> DOCAPI[/api/v2/evaluator<br/>기존 로그인 쿠키 사용]
    H --> DOCAPI
    DOCAPI --> AUTH
    DOCAPI --> DOC[app/evaluation/documents<br/>문서 열람 · 근거 비교 · 도우미 연결]
    DOC --> ED
    DOC --> DOCDB[(apps/documents/documents_parse.sqlite3<br/>읽기 전용 · 별도 경로 지정 가능)]
    DOC --> CHAT[apps/chatbot/chatbot.py<br/>AI 설정·패키지 준비 시 사용]
    A --> S[app/shared<br/>DB 접근 · 계약 · 동기화]
    K --> S
    E --> S
    S --> DATA{--data-dir}
    DATA -->|데모| DEMODB[(apps/server/data/database/<br/>admin.sqlite3 · evaluation.sqlite3 · keys.bin)]
    DATA -->|비데모| LIVEBD[(apps/server/data/production/<br/>admin.sqlite3 · evaluation.sqlite3 · keys.bin)]
    DEMODB --> AD[(관리자 · 위원회 데이터)]
    LIVEBD --> AD
    DEMODB --> ED[(평가 · 결과 데이터)]
    LIVEBD --> ED
    S --> M[migrations/admin · migrations/evaluation<br/>contracts · fixtures]
```

### 요청과 데이터의 흐름

1. `/`은 역할 선택 화면인 `/app/entry/design/entry.html`로 이동합니다. `design_runtime.py`가 `apps/web/src/runtime`의 원본 화면에 `screens`와 `bindings`의 기능 코드를 연결합니다.
2. 로그인과 화면 버튼은 `/api/v2/actions/{action_id}`로 요청합니다. `web_api.py`가 요청·세션을 확인하고 `gateway.py` 또는 위원회 액션 게이트웨이를 통해 업무 함수에 전달합니다.
3. 관리자·위원회 기능은 주로 `admin.sqlite3`, 평가·결과 기능은 `evaluation.sqlite3`를 사용합니다. 두 DB 간 자료 전달은 `app/shared/sync_service.py`의 outbox/inbox 방식으로 처리합니다. `keys.bin`은 기존 암호화 데이터와 함께 유지해야 합니다.
4. `/committee-v2/`는 `apps/server/app/committee/web_v2`를 제공합니다. `/src`와 `/fonts`는 `apps/web`에서 제공합니다. 시안 폴더 `apps/web_cookiesh1/v2`는 서비스에 포함하지 않으며 `/v2/` 경로는 제공하지 않습니다.
5. EV-03·04·05는 기존 화면에 `/src/evaluator` 모듈을 연결합니다. `/api/v2/evaluator`는 기존 로그인 쿠키와 위원·사업·참석·회차 권한을 검사한 뒤 문서 DB의 고정 버전을 읽습니다. 별도 8002 서버나 Vite는 필요하지 않습니다. 점수와 의견 저장은 기존 액션 API를 유지합니다.
6. `/api/v2`의 `v2`는 API 버전 이름입니다. `apps/web_cookiesh1/v2` 시안 폴더는 서비스에 사용하지 않습니다. 데모와 비데모는 같은 화면·업무 코드를 사용하며, `--demo` 시드 실행 여부와 데이터 폴더가 다릅니다.

## 실행 파일 구조

```text
simsa-service-v0.2/
├── start_service.py                  # macOS·Windows 공통 실행기
├── start_simsa_v2.py                 # 이전 명령 호환 실행기
├── start_simsa_v2.cmd                # Windows 선택용 바로가기
├── SERVICE_ARCHITECTURE_AND_RUN.md  # 이 문서
├── docs/EVALUATOR_DOCUMENT_INTEGRATION.md
└── apps/
    ├── web/
    │   ├── src/
    │   │   ├── runtime/             # 실제 HTML·CSS·JS 화면
    │   │   ├── screens/             # 화면별 기능 연결
    │   │   ├── evaluator/           # EV-03·04·05 문서·비교 기능
    │   │   └── bindings/            # 공통 기능 연결
    │   └── public/
    │       ├── fonts/               # Pretendard GOV
    │       └── index.html           # 선택적 기본 화면
    ├── documents/
    │   ├── documents_parse.sqlite3 # 문서 파싱 DB · 읽기 전용 연결
    │   ├── step3_ai_requirements_extract_to_SQLite.py
    │   └── requirements.txt        # 문서·AI 선택 의존성
    ├── chatbot/
    │   └── chatbot.py              # AI 답변 모듈
    └── server/
        ├── run.py                    # FastAPI 시작·데모 초기화
        ├── requirements.txt         # 실행 의존성
        ├── app/
        │   ├── api/                  # HTTP 라우팅·액션 매핑·화면 연결
        │   ├── admin/                # 계정·부서·사업·대시보드
        │   ├── committee/            # 후보·선정·명부·위원회 화면
        │   ├── evaluation/           # 출석·평가·서명·결과
        │   └── shared/               # DB·데모 데이터·동기화·계약
        ├── contracts/               # 실행 시 읽는 스키마·액션 계약
        ├── fixtures/                # 초기 공통 데이터 SQL
        ├── migrations/
        │   ├── admin/               # 관리자·위원회 DB 변경
        │   └── evaluation/          # 평가 DB 변경
        └── data/
            ├── database/           # 데모 DB · v0.2 압축본에 포함
            │   ├── admin.sqlite3
            │   ├── evaluation.sqlite3
            │   ├── keys.bin
            │   ├── access-code.txt
            │   └── sample-manifest.json
            └── production/         # 비데모 실행 시 생성 · 압축본 미포함
                ├── admin.sqlite3
                ├── evaluation.sqlite3
                ├── keys.bin
                └── access-code.txt
```

`artifacts/simsa-service-v0.2.zip`에는 실행에 필요한 소스·화면·현재 데모 DB와 문서 DB가 들어 있습니다. `apps/server/data/production`, `.venv`, 테스트, `apps/web_cookiesh1/v2`는 포함하지 않습니다. 압축본의 데모 DB를 `--demo` 없이 열어도 가상 계정은 남아 있으므로 비데모 실행에는 별도 데이터 폴더를 지정합니다.

## macOS·Windows에서 실행

Python 3.13이 설치된 컴퓨터에서 압축을 풀고 **압축 해제 폴더 `simsa-service-v0.2`**로 이동합니다. 저장소에서 바로 실행할 때는 현재 저장소 루트를 사용합니다. 기관 환경에서는 의존성 설치 전에 해당 패키지 게이트를 확인합니다. 가상환경은 컴퓨터마다 생성하므로 압축본에 포함하지 않습니다.

macOS 터미널:

```bash
cd simsa-service-v0.2
python3 -m venv .venv
.venv/bin/python -m pip install -r apps/server/requirements.txt
.venv/bin/python start_service.py --port 5191
# 비데모: 데모 DB와 분리된 빈 데이터 폴더 사용
.venv/bin/python apps/server/run.py --port 5191 --data-dir apps/server/data/production
```

Windows PowerShell:

```powershell
cd simsa-service-v0.2
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps/server/requirements.txt
.venv\Scripts\python.exe start_service.py --port 5191
# 비데모: 데모 DB와 분리된 빈 데이터 폴더 사용
.venv\Scripts\python.exe apps/server/run.py --port 5191 --data-dir apps/server/data/production
```

위 명령 중 **한 가지 실행 방식만** 선택합니다. 브라우저에서 `http://127.0.0.1:5191/`을 열고, 실행 터미널에서 `Ctrl+C`로 종료합니다. 포트가 비어 있으면 `--port 5191`을 생략해 기본 포트 `5190`을 사용할 수 있습니다. 같은 데이터 폴더로 재실행하면 DB가 유지됩니다. 현재 작업 환경에서는 5191 서비스가 종료되어 있습니다.

비데모 폴더는 처음 만들면 관리자·사업·위원 데이터가 모두 비어 있습니다. 계정과 업무 데이터를 등록해야 로그인 및 평가를 진행할 수 있습니다. `--demo`를 빼는 것만으로 운영 데이터나 배포 환경이 마련되는 것은 아닙니다. 문서 DB는 별도로 `apps/documents/documents_parse.sqlite3`를 읽으며, 현재 평가 DB의 문서 참조 3건과 파싱 버전이 일치하지 않습니다.

### 실행 옵션

`start_service.py`는 현재 명령을 실행한 Python(`sys.executable`)으로 `apps/server/run.py`를 실행하며 **항상 `--demo`를 전달**합니다. 비데모는 `apps/server/run.py`를 직접 실행해야 합니다. 서버 자체의 기본값은 포트 `5190`, 데이터 폴더 `apps/server/data/database`이므로, 비데모에서는 반드시 별도 `--data-dir`을 지정합니다. 프런트엔드는 같은 FastAPI 서버가 제공하므로 `npm run dev`는 필요하지 않습니다.

| 옵션                    | 의미                                                                                                                                                                                   |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--demo`              | 가상 계정·시연 데이터를 초기화하거나 기존 데모 데이터와 연결합니다. `start_service.py`가 자동으로 전달합니다.                                                                       |
| `--original-ui`       | `apps/web/src/runtime`의 원본 화면에 기능 코드를 연결합니다. 현재 서버의 기본값도 `True`라 명시하지 않아도 같습니다.                                                               |
| `--port 5190`         | 로컬 서버 포트입니다. `--port 5191`처럼 변경할 수 있습니다.                                                                                                                          |
| `--data-dir 경로`     | SQLite DB, `keys.bin`, `access-code.txt`를 저장·읽을 폴더입니다. 데모와 비데모 폴더를 분리합니다. 기존 데이터를 이동할 때는 DB와 키를 함께 유지합니다.                            |
| `--samples 경로`      | 선택 사항인 샘플 문서 폴더입니다. 기본 실행에는 필요하지 않습니다.                                                                                                                     |
| `--documents-db 파일` | 문서 파싱 SQLite를 읽기 전용으로 연결합니다. 생략 시 `EVAL_DOCUMENTS_DB_PATH`, 그다음 `apps/documents/documents_parse.sqlite3`를 사용합니다. 상대 경로는 프로젝트 루트 기준입니다. |

과거 실행 코드에 있던 `os.execv(...)`는 현재 사용하지 않습니다. 현재 `start_service.py`는 운영체제별 Python 경로를 고정하지 않고 `sys.executable`과 `subprocess.run`을 사용합니다. 추가한 실행 옵션은 서버로 전달되지만, 자동으로 넣는 `--demo`는 제거할 수 없습니다.

### 데모 로그인

| 역할       | 계정 또는 이름                  | 비밀번호 또는 휴대전화 뒤 4자리 |
| ---------- | ------------------------------- | ------------------------------- |
| 총괄관리자 | `super-demo`                  | `DemoOnly!2026`               |
| 사업담당자 | `web-demo`                    | `DemoOnly!2026`               |
| 평가위원   | `가상위원01` ~ `가상위원07` | `0001` ~ `0007`             |

이 계정은 데모 데이터 폴더에서만 쓸 수 있습니다. 평가위원은 초청된 사업을 선택해야 할 수 있습니다. v0.2 압축본에는 현재 데모 DB와 `keys.bin`이 있으므로 접근을 제한하세요.

## 확인한 동작과 검증 범위

2026-10-18에 데모 통합 테스트 6개와 실제 브라우저의 문서 열람·비교 흐름이 통과했습니다. 폴더 변경 후에도 같은 6개 테스트가 통과했고, 비데모 서버를 별도 빈 DB로 실행했을 때 `demo: false`, 첫 화면 HTTP 200, 두 DB 무결성 `ok`, 관리자·사업·위원 0건을 확인했습니다. 사용자 요청에 따라 이후 5191 서버를 종료했고 포트 해제를 확인했습니다. Windows 실제 실행은 아직 확인하지 않았습니다.

전체 `gg verify --run-tests`는 npm 테스트 명령 미설정과 Mac 가상환경의 `pytest` 미설치로 `blocked` 상태입니다. 개별 동작 확인은 운영 배포 검증을 뜻하지 않습니다.
