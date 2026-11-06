# Job Research

**“나한테 맞는 공고 찾아줘.” → 근거 있는 짧은 추천과 직접 링크 → 선택한 공고만 지원 준비.**

`0.2.0-rc.2` · 개발 프리뷰 · ChatGPT Work 명시 호출/실제 웹조사 일부 검증 · 다른 호스트 미실행

## 가장 쉬운 시작

[한국어 빠른 시작](START_HERE.ko.md)에서 쓰는 환경 하나만 선택한다.
스킬 설치가 없는 환경은 `portable/JOB_RESEARCH.md` 한 파일을 첨부하고 같은 요청을 한다.
일반 사용자는 설문, JSON, 데이터베이스, Python, API 키를 준비할 필요가 없다.
이미 알고 있는 관련 정보는 접근 가능한 AI 메모리에서 먼저 확인하고, 꼭 필요한 개인 사실만 질문한다.

> 나한테 맞는 채용공고 찾아줘. 핵심만 보여줘.
> 지난번 이후 바뀐 곳과 곧 마감하는 곳을 알려줘.
> 2번 지원 준비하자.
> 2번을 다른 AI에서 이어갈 수 있는 새 채팅용 프롬프트로 줘.

마지막 두 행동은 선택이다. 공고 링크를 열어보기만 해도 된다.

## 보여주는 결과

기준일과 한 줄 결론 → 마감순 공고·개인 근거·중요 주의점 → **공식 공고/실제 지원 URL** → 다음 행동.
변화 없는 기록, 조사 통계, 장문 프롬프트는 매번 출력하지 않는다.
간결함 때문에 중요한 공고·마감·경고를 숨기거나 top-N으로 잘라내지 않는다.
[합성 보고 예시](skills/job-research/assets/report-examples.ko.md)

## 누락을 줄이는 방법

검색 방법은 자율적이다. 고정 기업 수/검색 횟수/플랫폼/도구 순서를 채우지 않는다.
대신 **수집 누락 → 잘못된 제외 → 요약 중 누락**을 구분해 확인한다.
오래된 모집 중 공고, 다른 직무명, 혼합 공채의 직무별 자격, 재공고, 미탐색 산업과
반복 이월 영역을 점검하고, 다른 경로에서 새 기회가 나오면 그 분기를 추가 조사한다.
무누락·전국 전수조사·합격률은 보장하지 않는다. 기록 검사는 실제 웹 조사 증명이 아니다.

## 환경 호환성

공통 Agent Skills 폴더 + OpenAI 플러그인 포장 + Claude 업로드 ZIP + Gemini 루트 ZIP + 한 파일 대체판을 제공한다.
네이티브 설치, 현재 웹검색, 메모리 접근, 저장, 예약, 결과 전달은 서로 다른 기능이다.
제품명만으로 권한을 추정하지 않는다. 계정/버전/조직 정책별 실제 동작을 확인해야 한다.
[환경별 설치와 검증 상태](docs/compatibility.ko.md)

## 이 패키지가 포함하는 것과 포함하지 않는 것

포함: 실행 지침·참고자료, 선택형 프롬프트 인계, 오프라인 검수/보고/설치 보조 코드,
합성 사례, 패키지 검사, 평가용 고정 공고와 기록 평가기, 재현 가능한 배포 스크립트.
미포함: 자체 크롤링 서버, 플랫폼 간 메모리 공유, 공통 인증, 자동 지원서 제출,
독립 예약 서버, 비용 발생 API, 영구 데이터베이스. 기존 예약은 설치로 변경되지 않는다.

## 검증 및 공개

[실제 검증 결과](docs/validation.md)와 [검토·한계](docs/final-review.ko.md)를 확인한다.
정적/단위/합성 데이터 테스트와 실제 모델·실제 시장 성능을 분리한다.
행동 평가 정의 64건은 실행 결과가 아니다. 별도 새 세션에서 수행한 실제 모델 사례와 도구 기록은 검증 문서에 구분했다. 평가 정답은 설치 패키지에 넣지 않는다.
이 버전은 실환경 미검증 부분을 명시하는 개발 프리뷰로만 소개해야 한다.
개인 메모리·지원 기록·이력서·토큰은 포함하지 않는다. [개인정보](PRIVACY.md) · [보안](SECURITY.md)
[MIT 라이선스](LICENSE) · 소유자가 RC 공개를 승인했다. [배포 상태](docs/github-readiness.ko.md)

## 개발자/Work에 넘길 때

[WORK_HANDOFF.ko.txt](WORK_HANDOFF.ko.txt)를 이 소스 ZIP과 함께 전달한다.
기본 검사: `python -m unittest discover -s tests -v`
재빌드: `python scripts/build_release.py`
배포 무결성 확인: `python scripts/verify_release.py`
보조 코드만 Python 3.10+ 표준 라이브러리를 사용한다. 일반 사용자는 실행할 필요가 없다.

## English

Memory-first, adaptive job research with brief linked decisions and optional selected-job
application planning. Native skill formats and a self-contained instruction fallback are
included. Host capabilities remain separate; cross-provider memory, exhaustive recall,
account eligibility and live runtime compatibility are not promised. See
[English quick start](QUICKSTART.en.md) and the validation record before publishing.
