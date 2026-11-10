# Changes

## 0.3.0-alpha.3 (development branch)

- LG/Hanwha 공개 JSON, CJ/Doosan 공개 목록·상세, Jobflex 상세, Gabia 공개 ATS 수집을 추가했다. 신청·인증 API는 허용하지 않는다.
- 공채 공통 경력·고용 조건, 개별 직무·법인·지원 경로·근무지·원본 관측 시각을 보존한다.
- 이미지 재검수의 변경 감지·lease 차단, 원문이 사라진 종료 공채의 기존 직무 상태 전달, 한국 날짜 경계와 보고 누락 검사를 보강했다.
- 영문 포함 상장 코드, 중단된 단일 명부 재시작, 전체 alias component의 공식 식별자 충돌 검사를 수정했다.
- 명부·산업·기업집단별 실제 관측과 미확정 채널의 페이지 감사를 추가하고, 중요한 확인·원문 공백·미래 인재풀의 보고 원장을 각각 대조한다.
- Greeting의 회사/장소 표시와 실제 주소, 직무별 경력·고용 메타를 구분하고, 커스텀 도메인의 관측 상세와 한글 이미지 경로를 처리한다.
- 목록에 직접 등장하지 않는 공채 파생직무를 허위 누락 작업으로 만들지 않고, 부모 불발견은 별도 재검수로 남긴다.
- 실제 국내 원문·이미지·과거 후보 재검수 결과와 합성 회귀·규모·패키지 검사를 별도로 기록했다. 전국 조사 완료나 정식 릴리스가 아니다.

## 0.2.0-rc.2

- Work의 실제 설치 검증기가 거부한 최상위 compatibility 필드를 본문으로 옮겼다. 기능/권한 제약은 유지했다.
- 실제 조사에서 길어진 제외 기록이 기본 보고에 붙지 않도록 보고 참고지침을 명확히 했다. 후보 수 상한은 추가하지 않았다.
- 설치기에서 원본 루트와 프로젝트 상위 경로의 심볼릭 링크 우회를 거부한다.
- 합성 출처 명령의 실제 반환 기록 및 기록-판정 정합성 검사를 추가했다. 정답을 보지 않는 새 세션과 별도 평가자를 사용했다.
- 배포 원본 해시를 재생성하고, 출처/ZIP/버전/참고파일/단일파일 지침을 확인하는 검증기를 추가했다.
- 별도 검증 브랜치와 GitHub Actions 검사 구성을 준비했다. 승인된 개인 공개 저장소 생성과 원본 소스 원격 쓰기를 실제 확인했다. 최신 배포 결과는 docs/github-readiness.ko.md에 기록한다.
- 소유자의 2026-11-06 승인에 따라 MIT 라이선스를 원본·설치 ZIP·한 파일 지침에 적용했다. RC 공개 승인과 실제 원격 게시 여부는 구분한다.
- 실환경 미실행이 남아 RC를 유지한다. 기존 예약·알림은 변경하지 않았다.

## 0.2.0-rc.1

Cross-host packaging and explicit runtime verification boundaries; direct job/application
links; optional report-scoped same-chat/new-chat application planning; autonomous research
with collection/screening/report-loss reconciliation; offline validation/render/handoff
helpers; safe local installation; synthetic fixture tools and grader; local code tests.
No claim of live three-host compatibility or exhaustive real-world recall. No GitHub push,
public release, owner license selection or scheduler changes performed.

## 0.1.1-draft

Coverage accountability and omission checks added; 12 static checks and 40 unexecuted
behavioral definitions. Preserved in the delivered prior archive, not silently rewritten.

## 0.1.0-draft

Memory-first adaptive research, short outputs, 9 static checks and 28 scenario definitions.
