# 심사임당

심사임당은 **사업 제안서를 평가하는 일을 돕는 프로그램**입니다.

사업담당자는 제안요청서와 제안서를 등록하고 평가위원을 선정합니다.

 평가위원은 자료를 읽고 점수를 제출합니다.

총괄관리자는 부서와 계정을 관리하고 결과를 확인합니다.

## 어떤 순서로 사용하나요?

1. **총괄관리자**가 부서와 사업담당자 계정을 만듭니다.
2. **사업담당자**가 사업을 등록하고 제안요청서, 평가항목, 제안서, 평가위원 명단을 준비합니다.
3. **평가위원**이 참석을 확인하고 제안서를 읽은 뒤 점수와 의견을 제출합니다.
4. **사업담당자와 총괄관리자**가 제출 상태와 평가 결과를 확인합니다.

문서에서 요구사항을 찾거나 평가항목 초안을 만드는 기능, 평가위원의 문서 질문 기능에는 AI가 사용됩니다. AI 결과는 담당자가 원문과 비교해 확인해야 합니다.

## 내 컴퓨터에서 실행하기

이 프로그램은 **Python 3.13**으로 실행합니다.

화면과 서버가 한 번에 켜지므로 별도의 `npm`이나 Vite 서버는 필요하지 않습니다. 아래 명령은 `README.MD`가 있는 **프로젝트 폴더**에서 실행하세요.

### macOS

처음 한 번만 설치합니다.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

이후 실행할 때는 다음 명령을 사용합니다.

```bash
.venv/bin/python start_service.py
```

### Windows PowerShell

처음 한 번만 설치합니다.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

이후 실행할 때는 다음 명령을 사용합니다. 가상환경을 만든 뒤에는 `start_simsa_v2.cmd`를 실행해도 됩니다.

```powershell
.venv\Scripts\python.exe start_service.py
```

실행되면 브라우저에서 **[http://127.0.0.1:5190/](http://127.0.0.1:5190/)**을 엽니다. 종료할 때는 실행한 터미널에서 `Ctrl+C`를 누릅니다. 5190번 포트를 이미 사용 중이라면 실행 명령 끝에 `--port 5191`을 붙이고 `http://127.0.0.1:5191/`로 접속하세요.

### 새 데이터로 시작할 때

위의 기본 실행 명령은 `apps/server/data/database/`에 있는 **현재 로컬 데이터**를 사용합니다. 이 폴더에는 이미 등록된 사업과 문서가 있으므로 빈 상태가 아닙니다. 새 납품 환경이나 연습용으로 처음 시작한다면 **비어 있는 별도 데이터 폴더**를 지정하세요.

```bash
# macOS
.venv/bin/python start_service.py --data-dir apps/server/data/new-service
```

```powershell
# Windows PowerShell
.venv\Scripts\python.exe start_service.py --data-dir apps/server/data/new-service
```

두 실행 명령을 동시에 켜지 마세요. 같은 데이터 폴더로 다시 실행하면 입력한 내용이 유지됩니다.

## 총괄관리자 첫 로그인

**관리자 계정이 없는 새 데이터 폴더**를 처음 실행하면 아래 계정이 자동으로 생성됩니다.

| 구분          | 입력할 값      |
| ------------- | -------------- |
| 아이디        | `superadmin` |
| 초기 비밀번호 | `superadmin` |

첫 로그인에서 비밀번호를 새로 정해야 합니다.

**현재 로컬 기본 데이터 폴더의 비밀번호는 이미 변경되어** 위 초기 비밀번호로 로그인할 수 없습니다.

서버를 다시 켜도 기존 비밀번호가 초기화되지 않습니다. 비밀번호를 잊었다면 현재 관리 담당자에게 확인하세요.

## 평가위원 로그인

평가위원은 [첫 화면](http://127.0.0.1:5190/)에서 **평가위원**을 선택하고 이름과 휴대전화 뒤 4자리를 입력합니다.

초청받은 사업이 여러 건이면 사업을 고르는 화면이 나타나고, 한 건이면 바로 들어갑니다.

사업담당자가 보낸 **사업별 로그인 링크**에는 사업 번호가 들어 있습니다. 다른 사업의 링크로 접속하면 이름과 전화번호가 맞아도 로그인되지 않습니다.

여러 사업에 참여하는 위원은 첫 화면에서 로그인해 해당 사업을 선택하면 됩니다.

위원 풀에 등록된 것만으로는 로그인할 수 없고, 해당 사업의 **확정된 초청 명단**에 있어야 합니다.

## 입력한 자료는 어디에 저장되나요?

기본 저장 위치는 `apps/server/data/database/`입니다. `--data-dir`을 지정했다면 그 폴더에 저장됩니다.

| 파일                        | 저장하는 내용                          |
| --------------------------- | -------------------------------------- |
| `admin.sqlite3`           | 계정, 부서, 사업, 평가위원 명단        |
| `evaluation.sqlite3`      | 평가 회차, 점수, 결과                  |
| `documents_parse.sqlite3` | 등록한 문서와 분석 결과                |
| `projects_delete.sqlite3` | 삭제한 사업의 이력                     |
| `keys.bin`                | 기존 자료를 읽고 인증하는 데 필요한 키 |
| `access-code.txt`         | 로컬 접속 코드                         |

**백업하거나 다른 컴퓨터로 옮길 때는 먼저 서버를 종료**하고 위 파일을 한 폴더에서 함께 복사하세요. 특히 `keys.bin`을 잃으면 암호화된 기존 자료를 읽지 못할 수 있습니다. 이 파일과 실제 사업 자료는 공개 저장소에 올리지 마세요.

## 주요 파일 구조

```text
프로젝트 폴더/
├── README.MD                 # 이 안내서
├── start_service.py          # 권장 실행 파일
├── start_simsa_v2.py         # 이전 실행 명령과의 호환용
├── start_simsa_v2.cmd        # Windows 실행 바로가기
├── requirements.txt          # Python 설치 목록
└── apps/
    ├── server/
    │   ├── run.py            # 실제 웹 서버 시작
    │   ├── app/              # 계정·사업·위원·평가·문서 기능
    │   ├── migrations/       # 데이터베이스 구조 변경
    │   └── data/database/    # 기본 저장 폴더
    ├── web/
    │   ├── src/runtime/      # 실제 화면
    │   ├── src/screens/      # 화면별 기능 연결
    │   ├── src/evaluator/    # 평가위원 문서·챗봇 화면 기능
    │   └── public/           # 글꼴 등 정적 파일
    ├── documents/             # 제안요청서·제안서 읽기와 분석
    └── chatbot/               # 문서 질문 답변
```

`start_service.py`가 `apps/server/run.py`를 실행합니다. 이 서버가 화면과 API를 함께 제공하며, 기본 접속 주소는 `http://127.0.0.1:5190/`입니다. `start_simsa_v2.py`와 `start_simsa_v2.cmd`는 이전 실행 방법을 위해 남겨 둔 파일입니다.

## AI 기능을 사용하려면

프로젝트 폴더의 `.env` 파일이나 실행 환경에 `OPENAI_API_KEY`를 설정해야 합니다. 필요한 Python 패키지는 루트의 `requirements.txt`로 설치됩니다. 키가 없거나 AI 서비스에 연결되지 않으면 문서 분석·문서 질문 등 AI 기능을 사용할 수 없으며, 화면에서 상태를 안내합니다.

 **API 키를 README, 채팅, Git 저장소에 적지 마세요.**

## 운영 서버를 쓰는 경우

아래는 **Rocky Linux 9 서버**에 새로 설치하는 예시입니다. 서버 관리자 권한(`sudo`), 접속할 도메인, Python 패키지를 내려받을 인터넷 연결이 필요합니다. Rocky Linux 10은 패키지 이름과 서버 환경을 확인한 뒤 적용하세요. 명령의 `USER@SERVER`와 `simsa.example.go.kr`은 실제 SSH 계정·서버 주소와 도메인으로 바꿉니다.

운영 자료는 프로그램과 분리해 `/var/lib/simsa`에 저장합니다. **빈 폴더로 시작하면 기존 로컬 자료는 복사되지 않으며**, 총괄관리자 `superadmin / superadmin` 계정만 자동 생성됩니다. 첫 로그인에서 비밀번호를 바꾸세요.

### 1. 서버 준비와 프로그램 복사

서버에 SSH로 접속한 뒤 아래 명령을 실행합니다. Python 3.13은 EPEL 저장소에서 설치합니다.

```bash
cat /etc/rocky-release
sudo dnf upgrade -y
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf install -y epel-release
sudo dnf install -y python3.13 python3.13-pip rsync nginx
python3.13 --version
sudo groupadd --system simsa
sudo useradd --system --gid simsa --no-create-home --shell /sbin/nologin simsa
sudo install -d -m 755 -o root -g root /opt/simsa
sudo install -d -m 750 -o simsa -g simsa /var/lib/simsa
sudo install -d -m 700 -o root -g root /etc/simsa
```

내 컴퓨터의 **프로젝트 폴더**에서 다음 명령으로 프로그램을 서버에 보냅니다. `.env`, 가상환경, 로컬 데이터는 전송하지 않습니다. 전송 경로 `/tmp/simsa`는 이 프로그램 전용 임시 폴더로 사용하세요.

```bash
rsync -av --delete --delete-excluded --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'apps/server/data/' ./ USER@SERVER:/tmp/simsa/
```

다시 서버에서 설치합니다. 이후 코드만 갱신할 때도 같은 방식으로 복사하며, `/var/lib/simsa`는 덮어쓰지 않습니다.

```bash
sudo rsync -a /tmp/simsa/ /opt/simsa/
sudo chown -R root:root /opt/simsa
sudo python3.13 -m venv /opt/simsa/.venv
sudo /opt/simsa/.venv/bin/python -m pip install -r /opt/simsa/requirements.txt
```

### 2. 도메인과 AI API 키 설정

운영 서버는 요청 주소를 검사합니다. `SIMSA_ALLOWED_HOSTS`에 실제 접속 도메인만 적습니다. AI 기능을 사용하려면 [OpenAI API 플랫폼에서 프로젝트용 API 키를 발급](https://help.openai.com/en/articles/9186755-managing-projects-in-the-api-platform)받아 `OPENAI_API_KEY`에 설정합니다. 프로젝트의 사용량과 지출 한도도 확인하세요.

```bash
sudo install -m 600 -o root -g root /dev/null /etc/simsa/simsa.env
sudoedit /etc/simsa/simsa.env
```

열린 편집기에 다음 형식으로 적습니다. **키 값은 실제 발급받은 값으로 바꾸고**, AI 기능을 사용하지 않으면 `OPENAI_API_KEY` 줄을 생략합니다. 이 파일은 Git에 넣거나 다른 사람에게 보내지 마세요.

```dotenv
SIMSA_ALLOWED_HOSTS=simsa.example.go.kr
OPENAI_API_KEY=여기에_발급받은_API_키
```

IP 주소로 접속할 계획이라면 해당 IP도 쉼표로 추가합니다. `https://`나 포트 번호는 적지 않습니다. 예: `SIMSA_ALLOWED_HOSTS=simsa.example.go.kr,192.0.2.10`.

### 3. 재부팅 후에도 자동 실행되도록 설정

다음 명령은 `systemd` 서비스 파일을 만듭니다. 프로그램은 서버 내부의 `127.0.0.1:5190`에서만 열리고, 접속자는 뒤에서 설정할 Nginx를 거칩니다.

```bash
sudo tee /etc/systemd/system/simsa.service > /dev/null <<'EOF'
[Unit]
Description=Simsaimdang web service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=simsa
Group=simsa
WorkingDirectory=/opt/simsa
EnvironmentFile=/etc/simsa/simsa.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/simsa/.venv/bin/python /opt/simsa/apps/server/run.py --host 127.0.0.1 --port 5190 --data-dir /var/lib/simsa
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now simsa
sudo systemctl status simsa --no-pager
curl -I http://127.0.0.1:5190/
```

실행에 실패하면 `sudo journalctl -u simsa -n 100 --no-pager`로 오류를 확인합니다. API 키나 도메인 설정을 바꾼 뒤에는 `sudo systemctl restart simsa`를 실행해야 반영됩니다.

### 4. 웹 주소와 HTTPS 연결

도메인의 DNS가 서버를 가리키게 한 뒤 Nginx 설정을 만듭니다. 아래 두 곳의 `simsa.example.go.kr`을 실제 도메인으로 바꿉니다.

```bash
sudo tee /etc/nginx/conf.d/simsa.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name simsa.example.go.kr;
    client_max_body_size 60m;

    location / {
        proxy_pass http://127.0.0.1:5190;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF
sudo nginx -t
sudo systemctl enable --now nginx
```

SELinux가 적용된 서버에서 Nginx 접속에 502 오류가 나면 `sudo setsebool -P httpd_can_network_connect 1`을 실행하고 다시 확인합니다. 방화벽에서는 웹 접속용 80·443번만 허용하고 **5190번은 외부에 열지 않습니다**.

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

**외부 사용자에게 공개하기 전에 HTTPS를 적용하세요.** 공인 도메인이고 80번 포트로 인증할 수 있다면 다음과 같이 인증서를 발급합니다. 기관 내부망에서는 기관이 제공하는 인증서와 HTTPS 프록시 설정을 사용하세요.

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d simsa.example.go.kr
sudo certbot renew --dry-run
```

인증서 발급 중 HTTP를 HTTPS로 보내는 옵션을 선택합니다. 브라우저에서 `https://실제-도메인/`으로 접속해 첫 로그인과 화면 표시를 확인합니다. 인증서 발급이 끝나기 전에는 실제 계정과 자료를 입력하지 마세요.

### 5. 운영 중 확인·업데이트·백업

```bash
sudo systemctl status simsa --no-pager
sudo journalctl -u simsa -f
sudo systemctl restart simsa
```

코드를 업데이트할 때는 먼저 아래처럼 **서비스를 멈추고 전체 데이터 폴더를 백업**합니다. 내 컴퓨터에서 1단계의 전송 명령을 다시 실행한 뒤, 서버에서 새 코드를 복사하고 패키지를 설치해 서비스를 시작합니다.

```bash
sudo systemctl stop simsa
SIMSA_BACKUP_FILE=/root/simsa-$(date +%F-%H%M%S).tar.gz
sudo tar -C /var/lib -czf "$SIMSA_BACKUP_FILE" simsa
sudo tar -tzf "$SIMSA_BACKUP_FILE" > /dev/null
sudo ls -lh "$SIMSA_BACKUP_FILE"
# 내 컴퓨터에서 1단계의 rsync 전송 명령을 실행한 뒤 서버에서 계속합니다.
sudo rsync -a /tmp/simsa/ /opt/simsa/
sudo chown -R root:root /opt/simsa
sudo /opt/simsa/.venv/bin/python -m pip install -r /opt/simsa/requirements.txt
sudo systemctl start simsa
```

백업 파일은 서버 밖의 접근 제한된 보관 장소에도 복사하세요. `/var/lib/simsa`의 DB와 `keys.bin`은 **항상 함께** 보관해야 합니다. 운영 자료를 초기화하거나 다른 DB로 바꾸면 기존 계정·사업·문서가 사라질 수 있으므로 백업을 확인한 뒤 작업하세요. 서버에 실제 설치해 검증하기 전에는 운영 환경별 방화벽, 인증서, Python 패키지 설치 결과를 별도로 확인해야 합니다.

참고: [Rocky Linux의 EPEL·CRB 설정](https://docs.rockylinux.org/guides/update_versions/), [EPEL의 Python 3.13 패키지](https://packages.fedoraproject.org/pkgs/python3.13/python3.13/), [Rocky Linux의 인증서 설정](https://docs.rockylinux.org/guides/security/generating_ssl_keys_lets_encrypt/).

## 개발과 확인에 관한 참고

- 제안요청서는 HWPX로 등록합니다. 업체 제안서는 HWPX, PDF, PPTX를 지원합니다. 파일 종류에 따라 원본 화면 표시 방법이 다를 수 있습니다.
- 문서 질문의 대화 내용은 DB에 저장하지 않습니다.
- 이전 통합 작업과 당시 검증 내용은 [통합 기록](docs/INTEGRATION_2026-10-18.md)에 있습니다. 그 기록은 현재 버전의 전체 인수검증을 뜻하지 않습니다.
- 팀 저장소: [DaeUng79/5topilot_team](https://github.com/DaeUng79/5topilot_team)

## 만든 사람

| 기관 | 팀원 | 담당 분야 |
| --- | --- | --- |
| 경기도청 | 원준석 | 기획, 평가위원 등록·선정 |
| 양산시 | 오대웅 | 문서 처리, 요구사항 분석, 챗봇 |
| 외교부 | 김유진 | 평가·결과 처리 |
| 방위산업청 | 현수환 | 웹 화면 |
