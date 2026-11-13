# Job Research Engine — 0.3.0a3 development alpha

공식 명부·공개 채용목록·상세·SQLite 작업 큐와 호스트 AI 평가를 연결하는 실제 실행 모듈이다.
사용자는 자연어로 요청한다. Python 3.10+ 표준 라이브러리를 쓰며 별도 서버·유료 API·사용자
작성 JSON은 필수가 아니다. 전국 조사나 모든 국내 ATS 지원이 완료된 제품은 아니다.

## 호스트 실행

체크아웃의 이 폴더에서 `python -m job_research_engine --db <private-path>`를 실행한다.
스킬의 `scripts/research.py`도 같은 코드를 쓴다. 네이티브 개발 ZIP은 runtime을 포함하고
격리 추출 후 실행 검사를 한다. portable Markdown에는 실행 코드가 없다.

```sh
python -m job_research_engine --db /PRIVATE/research.sqlite init
# AI가 관련 메모리로 profile을 작성한다. 일반 사용자에게 JSON을 요구하지 않는다.
python -m job_research_engine --db /PRIVATE/research.sqlite sync-registry krx --allow-network
python -m job_research_engine --db /PRIVATE/research.sqlite sync-registry dart-web --allow-network
python -m job_research_engine --db /PRIVATE/research.sqlite sync-registry ftc --year 2026 --allow-network
python -m job_research_engine --db /PRIVATE/research.sqlite sync-registry mme --year 2026 --allow-network
python -m job_research_engine --db /PRIVATE/research.sqlite reconcile-companies
python -m job_research_engine --db /PRIVATE/research.sqlite session PROFILE "나한테 맞는 공고 찾아줘"
```

## 실제 루프

`session`은 미완료 run을 복원한다. `--new-cycle`은 후보·결정·원래 갭 나이를 이어받는 새 조사다.
`sync-registry`는 원문/해시/행/페이지/범위/중복을 저장하며 예산 중단은 체크포인트다.
`discover`는 공식 식별자로 연결된 홈페이지에서 채용 링크를 발굴한다. 기본 balanced 전략은
기업집단·업종의 실제 시도 범위를 대조해 미탐색 분기를 먼저 열고, 같은 법인의 명부 alias가
이미 시도한 홈페이지를 다시 시작하지 않게 한다. 홈페이지 미상·차단 작업의 원래 나이는 보존한다.
`collect --details --allow-network`는 목록과 상세를 읽고 cursor/total/lease를 검사한다.
반복 `--source-id`로 새로 발견한 분기만 이어갈 수 있다. Ninehire 목록은 실제 페이지/카드 클릭/
마지막 이동 버튼의 host capture로 검증하며, SSR 레이아웃을 빈 공고 목록으로 취급하지 않는다.
`recheck-legacy`는 과거 URL을 재조회하되 회차·지원 결과를 GET 성공만으로 확정하지 않는다.

`packet`의 jobs/tasks/legacy를 cursor로 읽어 호스트가 실제 원문·이미지를 확인한다.
이미지는 `capture-detail`, 공채는 원문 구절을 붙인 `split-job`으로 개별 직무를 만든다.
AI가 본문 핵심업무를 비교해 `assess`, 다른 경로와 중요한 제외를 `audit`, `report`로 추천과
보고를 대조한다. 보고 번호는 report ID에 고정되고 사용자 선택 후에만 `handoff`로 이어간다.
CLI는 AI를 내장하거나 예약·알림을 자동 활성화하지 않는다.

`candidate-audit RUN --report-id REPORT`는 미수집·상세 공백·미평가·제외·보고 누락을 분리한다.
저장 후 발견/재평가된 후보를 과거 보고의 누락으로 오인하지 않는다. 목록 카드가 새로 보였다고
기존 상세 원문·관측 시각·판정을 덮지 않으며, 목록에 달라진 정보는 상세 재검수까지 추천을 막는다.
접수 시작 전 공고는 `upcoming`으로 보존하고, 실제 시작 시각 이후 재검수 작업을 둔다. 타이머는 없다.

독립 출처로 확인한 식별자 오기는 `override-identifier`로 가역 보정한다. 원명부·ID·facts는
바꾸지 않으며 재적재 값이 제3의 값으로 바뀌면 alias·홈페이지 상속을 중단한다. schema3은
동일 시각/바이트라도 서로 다른 실제 출처 URL을 별도 관측으로 보존한다. 구버전 DB는 원본
백업 후 관측 ID·원문·외래키를 보존하며 이관한다.

회사 수·검색 횟수·추천 개수는 완료 조건이 아니다. 등록 출처 ID와 한국의 고유 법인 수는 다르다.
이름만으로 법인을 합치지 않는다. 공식 식별자 alias는 증거와 undo를 보존한다. 플랫폼의 새로운
employer도 법인 미확정 frontier에 추가한다. 미탐색·차단·미평가·보고 누락을 별도로 보존한다.

## 검증

11월13일 개발 검증은 [독립 표본·복원·전문 채널 비교](docs/VALIDATION.20261113.parallel.ko.md)에
실제 수집, 직접 URL 개입, 미확인과 합성 검사를 구분한다. GameJob 개별 공고/관측 iframe과
부분 카테고리 발견, 접수 시작 후 재검수, 근거 있는 동일 공고의 제출 이력·보고 중복 방지,
별도 헤더 마감 보정과 JobKorea 메타데이터 경계를 보강했다. 전문 채널 전체 페이지·운영
호스트/채팅 전달은 미검증이며, 선택형 Docling 실험은 기존 엔진에 통합하지 않았다.

```sh
python -m unittest discover -s tests -v
python tools/scale_check.py
python tools/mutation_check.py
python tools/demo.py
```

합성 규모/변이 검사, 실사이트, 실제 AI, 새 세션, 배포·예약은 다른 검증이다.
[11월10일 지속 실행](docs/VALIDATION.20261110.continuation.ko.md), [11월10일 이전 체크포인트](docs/VALIDATION.20261110.ko.md), [이전 실행 기록](docs/VALIDATION.20261109.ko.md), [Sources](docs/SOURCES.ko.md),
[Architecture](docs/ARCHITECTURE.ko.md), [Host](docs/HOST_INTEGRATION.ko.md),
[Acceptance](docs/ACCEPTANCE.ko.md)를 참조한다. 기존 설치본·예약 변경이나 정식 release는 하지 않는다.
