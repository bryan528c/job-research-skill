# 호환성 및 검증 단계 — 0.2.0-rc.2

기준일: 2026-11-06 KST. `pass`는 아래 해당 단계에만 적용한다. 문서에 경로가 있다는 사실, 파일 복사, 호스트 로딩, 도구 실행, 저장, 예약은 서로 다른 증거다.

| 환경 | 제공/설치 경로 | 실제 로딩·호출 | 웹 조사 | 메모리·저장 | 예약·알림 |
|---|---|---|---|---|---|
| ChatGPT Work (이번 계정) | 개인 스킬 저장·원격 확인 pass; ZIP 업로드 UI not_run | 새 세션 명시 호출과 참고파일 읽기 pass; 자동 선택 not_run | 공개 공식 채용 사이트 검색/열람 pass, 한 회사 범위 | 합성 메모리 파일·현재 대화 이용 pass; 결과 파일 재읽기 pass; 실제 계정 장기기억·조사 상태 저장 not_run | not_run: 사용자 지시대로 기존 설정 불변 |
| ChatGPT Chat / 별도 GPT | 루트 ZIP 또는 한 파일 지침 제공 | not_run: 별도 Chat/GPT 실행 세션이 이 실행기에 없음 | not_run | not_run | not_run |
| Codex CLI | `.agents/skills/job-research/` 복사 시험 pass | not_run: codex 실행파일 없음 | not_run | not_run | not_run |
| Codex 데스크톱·IDE | 공통 폴더/플러그인 제공 | not_run: 해당 앱 실행 환경 없음 | not_run | not_run | not_run |
| Claude 채팅 | 폴더 ZIP 생성·검사 pass | not_run: 인증된 Claude 호출 환경 없음; 실제 UI 미점검 | not_run | not_run | not_run |
| Claude Cowork | 계정 스킬 경로 문서 확인 | not_run: Cowork 세션 없음 | not_run | not_run | not_run |
| Claude Code | `.claude/skills/job-research/` 복사 시험 pass | not_run: claude 실행파일 없음 | not_run | not_run | not_run |
| Gemini 앱 | 루트 ZIP 생성·검사 pass | not_run: 인증된 Gemini 호출 환경 없음; 실제 UI 미점검 | not_run | not_run | not_run |
| Gemini CLI | `.gemini/skills/job-research/` 복사 시험 pass | not_run: gemini 실행파일 없음 | not_run | not_run | not_run |
| 세 공급자 API / 제3자 호스트 | 직접 지침 주입 가능 형태 | not_run: API 인증/별도 런타임 없음; 유료 호출 미실행 | not_run | not_run | not_run |

Work의 제어된 웹 없음/메모리 없음 조건은 기능 제한을 준 행동 시험이다. 해당 계정에 원래 도구가 없다는 증거가 아니다. `/proc` 경로 저장 실패도 의도한 합성 실패 사례이며 서비스 장애 시험이 아니다.

## 제공 형식과 공식 근거

- OpenAI: 공통 skill 폴더와 `.agents/skills`, root `plugin.json` 및 `.codex-plugin/plugin.json` 호환 포장을 제공한다. 공개 디렉터리 등록과 GitHub 업로드는 별개다. 실제 Work 개인 스킬 설치에 사용한 검증기에서는 최상위 `compatibility` 필드가 거부되어 같은 내용을 본문으로 옮겼다. 이것은 모든 표준 호스트가 그 필드를 금지한다는 뜻이 아니다.
- Claude 채팅: 공식 안내의 Customize → Skills → Upload와 폴더 ZIP 구성을 대조했다. 실행 및 조직 정책에 따라 허용 여부가 달라진다. Cowork/클라우드는 로컬 폴더를 복사한 결과로 설치를 증명할 수 없다.
- Gemini 앱: 공식 원문에서 주 폴더의 `SKILL.md`, 폴더/ZIP 업로드를 확인했다. 실제 계정 메뉴·제공 여부는 미확인이다. CLI는 별도 `.gemini/skills` 또는 `gemini skills install` 경로다.
- 단일 파일: `portable/JOB_RESEARCH.md`만 읽는 새 Work 세션에서 제공 공고 분석과 선택 공고 인계를 실행했다. 다른 앱의 첨부 UI·자동 호출·장기기억 성공으로 확대하지 않는다.

## 불가능한 환경의 최소 수동 확인

1. 해당 앱/CLI에서 스킬 또는 단일 파일을 불러오고 실제 읽힌 버전과 참고파일을 확인한다.
2. 합성 인물로 자연어 요청 후 공개 공고와 지원 URL의 실제 열람 기록을 남긴다.
3. 메모리 충분/불충분/없음, 웹 없음, 저장 실패를 각각 구분한다.
4. 선택한 한 공고만 같은 대화 준비 또는 새 대화 인계로 이어간다.
5. 저장은 새 세션 재읽기, 예약은 별도 승인된 일회성 시험과 전달 확인이 있어야 pass로 바꾼다. 기존 개인 예약을 시험용으로 수정하지 않는다.

원문 근거는 [sources.md](sources.md), 실제 결과와 남은 제약은 [validation.md](validation.md)에 있다. **다른 호스트 미검증이 남아 RC/개발 프리뷰다.**
