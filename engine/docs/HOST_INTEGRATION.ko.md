# 호스트 AI와 엔진 연결

## 무엇을 실제로 연결해야 하는가

2026-11-09 개발판: `session`이 기존 run을 복원하고 `summary`/cursor 기반 `packet`으로 읽는다.
`sync-registry`, `reconcile-companies`, `discover`, `collect --details`, `recheck-legacy`,
`capture-detail`, `split-job`이 실제 실행 경로다. 네이티브 ZIP에는 동일 runtime이 포함된다.
체크아웃/네이티브에서 스킬 `scripts/research.py --db <private-path>`를 호출할 수 있다.
이 문서의 이전 기본 프로토콜과 달라진 상태는 Sources/VALIDATION.20261109에서 확인한다.

CLI가 구현되어 있다. 설치된 스킬이 이 CLI를 실제 호출하고 데이터를 읽고 써야 한다.
`SKILL.md`의 문구만 바꾸거나 ZIP을 생성했다고 실행 연결 완료로 처리하지 않는다.

개발 호스트(Codex/Claude Code/Gemini CLI 등)에서 파일 실행 권한이 있으면 로컬 CLI 경로를 쓴다.
채팅 전용 환경에서 실행 권한이 없으면 승인된 실행 환경/도구 연결이 필요하다. 한 파일 지침은
기본 조사 대체판이지 영속 수집 엔진 설치가 아니다. MCP 래퍼는 후속 작업이며 이 alpha에는 없다.

## 내부 프로토콜

호스트가 만든 프로필/관찰/판단 파일은 private temp/state 폴더에 둔다. 사용자가 직접 작성하지 않는다.
커맨드는 `python -m job_research_engine --db <private-path> <subcommand>`이다.

- `profile <id> <facts.json>`: 관련 메모리에서 확인된 최소 사실. 의미 없는 순서 변경 제외 동일 내용은 revision 유지.
- `import-registry <file> --kind ... --registry ... --source-url ... --scope ...`: 모집단 원본 범위를 명시.
- `import-legacy <profile-id> <records.json>`: 과거 후보의 출처/불확실성 그대로 보존.
- `companies --after <cursor>`: 전체 분모를 페이지로 읽음. page-size는 모델 문맥 크기이지 종료 목표가 아님.
- `source <config.json>`: 관찰된 채용 출처를 회사와 연결. 접근 정책과 association evidence를 포함.
- `plan <profile-id> --scope-note ...`: 실제 registry로부터 조사 작업 생성. 진행 중 run은 다시 만들지 말고 복구.
- `collect <run-id> --allow-network`: 승인된 네이티브 어댑터 수행. 인벤토리 커서가 남으면 실제 다음 페이지 처리.
- `next-task <run-id> --kind <type>`: host 할당. 실제 확인 후 ingest/complete-host-task, 실패는 block-task.
- `retry-task <task-id> --reason ...`: 원인을 해결한 뒤 재시도. 이미 저장된 불안정 스냅샷은 새 scan으로 분리.
- `review-packet`: 원문/평가 대기/옛 후보/차단 작업/진행 정보를 호스트에 제공.
- `assess <assessment.json>`: 직무 판단 결과. 최신 content_hash/profile_revision과 원문 observation ID 필요.
- `decision <event.json>`: 실제 사용자 결정/접수 상태. AI의 과거 추측을 확인 사실로 넣지 않는다.
- `audit <record.json>`: 다른 경로 검증 및 새 후보 발견 후 확장. 근거 참조를 실제 도구 흔적과 대조.
- `coverage <run-id>`: 로그 정합성과 미완료 검수. 전국 전체를 찾았다는 지표가 아니다.
- `universe-audit <run-id> --dimension registry|industry|group`: 출처 분모와 실제 법인ID 귀속 관측/미확정 채널을 대조한다. cursor를 끝까지 읽고 그룹 채널 별도 범위를 보존한다.
- `report <run-id> --text-only`: 짧은 링크 보고. 상세 통계는 기본 화면에 노출하지 않음.
- `handoff <report-id> <number> --profile-id ...`: 사용자가 고른 공고만 인계. 최신 모집 재확인 필요 표시.

## 관찰 데이터 예시

소스 등록:
```json
{"kind":"greenhouse","url":"https://boards-api.greenhouse.io/v1/boards/OBSERVED_BOARD/jobs",
 "company_id":"ACTUAL_DATABASE_ID","policy":"public_api",
 "evidence_ref":"ACTUAL_HOST_OBSERVATION_REF","settings":{"employer":"VERIFIED_EMPLOYER"}}
```
위 토큰/이름은 예시일 뿐 실제 수집에 사용하지 않는다. 회사 공식 채용 링크에서 board 연결을 확인한다.

host-json 페이지는 `jobs`, `terminal`, `next_cursor`, `expected_total`, `inventory_complete`를 포함한다.
`Job`의 필드는 model.py 참조. 별도 원문 도구 응답과 observation reference를 함께 보존한다.
스크린샷/동적 페이지 일부만 읽었으면 inventory_complete=true를 보내지 않는다.

평가 입력:
```json
{"profile_id":"PRIVATE_PROFILE_ID","job_id":"OBSERVED_JOB_ID","decision":"check",
 "reason":"확인된 개인 경험과 주요 업무의 연결","risk":"입사일 미확인",
 "blocking_unknowns":["필수 출근일"],"evidence_ids":["ACTUAL_OBSERVATION_ID"],
 "expected_profile_revision":1,"expected_content_hash":"ACTUAL_HASH"}
```

## 긴 조사 운영

기업목록 점검과 개별 공고 평가를 교차 수행한다. 긴급 마감은 먼저 보호하되 미조사 기업을 끝없이
미루지 않는다. 호스트가 중단되어도 private DB와 run ID를 새 세션에서 읽어 이어간다.
원문/목록/API가 막히면 허용된 다른 경로를 활용하고, 남은 갭을 지우지 않는다.

자원 한도는 checkpoint 사유다. 회사 수/추천 수를 채웠다는 이유로 종료하지 않는다. 플랫폼의
페이지 상한이 있으면 지역·직종 등 실제 지원범위에 맞는 상호보완 partition을 만들고 겹침을 제거한다.
partition 하나를 전체 시장으로 취급하거나 스스로 분모를 줄여 완료율을 꾸미지 않는다.

## 예약

### 개발 검증의 추가 인터페이스

`link-postings LEFT RIGHT --evidence-ref ...`는 실제로 확인한 동일 법인·개별 직무·회차를
연결한다. 제목 유사성이나 같은 회사만으로 호출하지 않는다. 제출/거절 이력과 보고 대표 항목이
연결을 따르므로 잘못 연결했다면 `unlink-postings LEFT RIGHT --reason ...`로 되돌린다.
원래 이벤트와 과거 보고 번호는 삭제하지 않는다. 보고 매핑의 `equivalent_job_ids`도 대조한다.

`amend-deadline RUN JOB EVIDENCE_JSON`은 본문을 새로 읽지 못했지만 현재 공식 헤더의 마감을
확인한 경우다. 입력에는 `deadline`, `expected_content_hash`, `source_url`, `evidence_text`,
`tool_ref`, `observed_at`이 필요하다. 원래 본문 observation과 clock은 유지하며 새 마감
observation을 별도로 저장한다. 재평가에는 둘 다 필요하고 과거 캡처는 최신 마감을 덮지 못한다.
일반 사용자에게 파일 작성을 요구하지 않고 호스트가 실제 도구 관측에서 만든다.

`engine/tools/compare_runs.py`는 비공개 독립 기준표와 실제 실행 export를 대조한다. 정확한
`[posting URL, individual role key]`를 사용하고 수집·판정·보고·중복·마감/링크·미확인을 나눈다.
`natural_unseeded`와 `direct_seeded`/`host_followthrough`를 섞지 않는다. 이 도구는 표본 작성의
독립성이나 AI 판단의 정확성을 인증하지 않는다. 실험 절차와 남은 조건은11월13일 검증 문서 참조.

이번 패키지는 타이머나 전달 채널을 만들지 않는다. 실제 배포 시 선택한 호스트의 스케줄러가
새 스킬/엔진 버전, private state, 이전 run ID에 접근하는지 확인해야 한다. 새 세션 read-back,
중단 복구, 보고 생성, 전달 확인을 각각 검증한다. 기존 개인 예약/알림은 별도 승인 전 변경하지 않는다.

## 실제 호환성

초기 인계의 Linux-only 상태와 현재 개발 실행은 다르다. 현재 PC는 Windows Python3.13.14와
Codex의 실제 CLI/비공개 DB/브라우저 연결을 실행했다. runtime 포함 개발 ZIP은 격리 추출해
검사한다. Python3.10/3.13×Windows/Linux CI는 해당 commit의 Actions 결과를 확인한다.
Claude/Gemini/채팅 전용 호스트·MCP·예약 전달은 not_run이다. 기존 설치 스킬 교체나 계정
전체 활성화를 했다는 뜻은 아니다.
