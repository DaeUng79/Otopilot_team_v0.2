# 심사 서비스 v0.2

Python 3.13에서 압축 해제 폴더를 열어 실행합니다. 운영 환경의 패키지 설치 정책을 먼저 확인하세요.

macOS:
    python3 -m venv .venv
    .venv/bin/python -m pip install -r apps/server/requirements.txt
    .venv/bin/python start_service.py --port 5191

Windows PowerShell:
    py -3.13 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r apps/server/requirements.txt
    .venv\Scripts\python.exe start_service.py --port 5191

포트가 비어 있으면 --port 옵션을 생략해 5190으로 실행할 수 있습니다.
배포용 압축본에는 기본 DB와 keys.bin이 동봉될 수 있습니다. 개인 정보와 개발용 접속 정보가 있으므로 압축본 접근을 제한하세요.
공개 GitHub 저장소에는 SQLite DB, keys.bin, access-code.txt, 데이터 매니페스트 및 개인 후보 명부 fixture를 올리지 않습니다. 저장소 소스에서 데모 실행 시 `--demo`가 합성 시연 데이터를 초기화하며, 문서 열람 기능을 사용하려면 문서 DB를 별도로 준비해야 합니다.
현재 평가 DB의 문서 참조 3건은 문서 DB의 파싱 버전과 연결되지 않아 실제 문서가 표시되지 않습니다.
AI 답변과 원본 SVG 렌더링에는 추가 패키지/설정이 필요합니다. 이번 압축본에 가상환경은 포함하지 않았습니다.
상세 구성은 SERVICE_ARCHITECTURE_AND_RUN.md와 docs/EVALUATOR_DOCUMENT_INTEGRATION.md를 보세요.
전체 검사 gg verify는 pytest 미설치 및 npm 테스트 미설정으로 blocked 상태입니다.
