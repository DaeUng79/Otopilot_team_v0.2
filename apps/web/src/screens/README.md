# screens — 화면 ID별 코드 폴더
기획 폴더 `v2/`의 화면 ID와 **똑같은 이름**으로 나눈다: `<그룹>/<화면ID>-<이름>/`
- 그룹: `entry` · `super-admin`(SA) · `dept-admin`(PM) · `evaluator`(EV)
- 각 폴더 README ↔ `v2/…/화면카드.md`의 "코드 위치"가 서로를 가리킨다.
- 파일 맨 위에 `// <화면ID> · <팀 버튼 ID>`를 적는다. DB 경로·SQL은 넣지 않고 API(버튼의 입력→출력)만 쓴다.
- 공용 부품 안내: [_shared.md](_shared.md)
- 아직 코드는 없다(README만). 기존 앱(`src/pages` 등)에서 옮겨 올 부품은 `v2/_공통/ARCHITECTURE.md` 참고.
