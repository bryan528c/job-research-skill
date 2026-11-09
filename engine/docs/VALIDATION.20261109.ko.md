# 실행 검증 — 2026-11-09 개발 alpha

implemented/local_tested: schema-1 백업/이관, 공식 명부 지속 적재, 법인 식별자 연결/undo,
국내 읽기 경로, 상세·이미지·개별직무 큐, employer frontier, 세션 복원/원래 갭 나이,
AI 평가 입력과 추천-보고 대조, runtime 포함 네이티브 패키지.

live_tested: SOURCES.ko.md의 실제 네 명부와 국내 공개 채용 경로. 원문/해시는 private 저장.
host_integrated: 실제 Codex AI→엔진 DB 호출, 브라우저 목록 끝/상세/지원 경로, 별도 AI
컨텍스트의 session 복원과 OS 프로세스 재열기. 계정 전체 자동 활성화는 아니다.
scheduled_verified: not_run — 기존 개인 예약/알림 변경은 요청 범위에서 금지됐고 새 예약도 없다.

## 구분한 검사

기존 rc.2 96개 기준선은 Windows 기본 임시폴더 권한으로 첫 실행이 실패했다. 허용된 임시폴더와
UTF-8로 분리해 줄바꿈/심볼릭 링크 권한 문제를 확인했다. 현재 root 검사는 runtime 격리 ZIP과
OS 독립 빌드 회귀를 포함한 100개다. 로컬에서는 96개 통과, symlink를 만들 수 없는 4개는
not_run(WinError 1314)이다. Linux CI 결과와 구분하며 assertion을 약하게 바꾸지 않았다.

엔진 검사는 실제 SQLite를 사용한다. 실자료에서 발견한 영문 종목코드 누락, 잘못된 URL,
충돌 행, 이미지-only, 공채 분해, 미확정 employer, 세션/갭 나이 실패를 합성 회귀로 재현한다.
실제 사용자/원문을 공개 fixture로 넣지 않는다.

독립 AI 컨텍스트가 지침을 읽고 private 원본 DB session을 실제 호출했다. 독립 합성 재현에서
찾은 inventory retry→새 cycle 나이 초기화와 assessment 해시 누락을 수정한 뒤 같은 재현
21개가 통과했다. 후보·평가·scope·cursor·원래 생성일·보고·source progress 등 13개 해시와
연속 DB 스냅샷을 대조했다. 다른 worker의 정상 상태 변화는 session 구간 변화와 구분했다.
실제 자료에 개인 event가 없어서 결정 복원은 합성 검증에 한정한다.

합성 10,000기업/250공고 검사는 9,990 미탐색을 partial로 보존·재열기한다. 4개 변이는 실제
결함 주입 시 회귀 실패를 확인한다. 이 수치를 실기업 조사량이나 시장 재현율로 부르지 않는다.
실제 AI가 검증된 개별 직무 124개를 본문에 따라 평가했으며 결과는 private에만 저장한다.
30개 미검증/미분해 레코드는 AI 평가 분모와 구분했다.
독립 경로에서 드러난 롯데/Greeting 현재목록을 추가로 실제 적재하고 상세/이미지 작업으로
확장했다. 새 후보의 미평가·미분해 상태는 이전 평가와 별도로 남긴다.

root/engine unittest, scale/mutation/demo, builder/verify/rebuild, 실사이트와 실제 AI 로그는 별도다.
CI는 Python3.10/3.13×Ubuntu/Windows이며 설정만으로 원격 성공을 주장하지 않는다.
해당 개발 브랜치의 실제 Actions 결과가 최종 원격 검증 근거다.
첫 원격 실행의 엔진 검사는 통과했으나 배포 재빌드는 OS별 Path 정렬과 ZIP creator metadata
차이로 실패했다. POSIX 문자열 정렬과 고정 creator metadata로 수정한 eb6fb10의 실제 원격
Release 4개 job과 Engine 4개 job은 모두 통과했다. 로컬 엔진 검사는 113개 모두 통과했다.
실제 새 cycle에서도 기존 154개 ID·60개 과거 레코드와 미해결 갭 원래 나이를 보존했고
롯데 현재목록 13건을 다시 수집했다. 이는 전국 조사가 완료됐다는 뜻이 아니다.

## 남은 범위

- 공식 출처 ID는 전국 고유 기업 수가 아니다. 충돌 법인, 발급취소 여부, 미탐색 회사/채용 채널이 남았다.
- 국내 모든 그룹/ATS/플랫폼의 페이지·이미지·지원 경로는 미완료. blocked와 queued를 구분해 보존한다.
- OpenDART/고용24 실인증: not_run, 키 미설정. 키 없는 실제 수집은 계속 실행했다.
- 동등 자원/동일 기간 baseline·rc.2·engine 비교와 독립 holdout 시장 성능: not_run, 비교집합/자원 배정을 실행하지 않음.
- Claude/Gemini/ChatGPT 채팅 전용 호스트: not_run, 해당 호스트 실행 연결을 하지 않음.
- 실제 지원 준비는 사용자 선택 대기. 합성 선택→ID 고정→handoff는 실행 검증한다.

main 병합·정식 release·기존 설치본 교체·예약 변경은 하지 않는다. DB·개인 기억·지원 이력·
원문·키·전체 인계 ZIP은 공개 commit/CI artifact/네이티브 ZIP에서 제외한다.
