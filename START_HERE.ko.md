# 처음 사용하기

## 일반 사용자는 세 가지만

**1. 내 환경에 맞게 한 번 불러오기**

- ChatGPT: 실제 계정의 Plugins → Skills → Create/Upload를 사용할 수 있으면 `dist/job-research-upload-root.zip`을 사용한다. 메뉴가 없다면 아래 대체판으로 시작한다. Work/Codex 배포에는 `dist/job-research-openai-plugin.zip`도 포함했다. 공개 디렉터리에 자동 등록되는 파일은 아니다.
- Claude: Customize → Skills의 업로드에서 `dist/job-research-claude.zip`을 선택한다. 코드 실행/조직 허용이 필요할 수 있다. Cowork/원격 세션은 로컬 폴더 복사만으로 설치됐다고 보지 않는다.
- Gemini: 실제 계정의 Customize → Skills 업로드에서 `dist/job-research-upload-root.zip`을 선택한다. 지역·계정·정책·배포 시점에 따라 메뉴가 다르면 지침/파일 대체 경로를 쓴다.
- Codex·Claude Code·Gemini CLI: 아래 개발 환경 안내를 따른다.

**네이티브 메뉴가 없거나 ZIP을 못 읽으면:** `portable/JOB_RESEARCH.md` 한 파일을 채팅에 첨부하거나 허용된 맞춤 지침/Gem/프로젝트 지침에 넣고 “이 지침에 따라 나한테 맞는 공고 찾아줘”라고 한다. 이는 설치·자동 호출·장기 기억을 보장하는 방식이 아니다.

**2. 한 문장으로 요청하기**

> 나한테 맞는 채용공고 찾아줘. 필요한 정보는 기존 메모리에서 먼저 확인하고 결과는 짧게 보여줘.

웹 도구가 없으면 현재 공고 탐색은 할 수 없다. 공고 원문/URL을 제공해 분석하거나 검색 가능한 환경을 사용한다.
다른 AI의 메모리까지 자동으로 읽지는 않는다. 모르는 개인 사실만 필요한 순간 짧게 물어본다.

**3. 보고를 보고 원하는 행동만 고르기**

공고/지원 URL을 열어본다. 후속 준비가 필요하면 “2번 지원 준비”라고 한다.
다른 대화/AI에서 이어가려면 “2번 새 채팅용 프롬프트”라고 한다.
후속 준비 없이 보고만 받아도 된다. 매번 긴 프롬프트를 출력하지 않는다.

## 확인된 실행 범위

2026-11-06 이 작업의 ChatGPT Work 계정에서 개인 스킬 저장 후 새 세션의 명시 호출,
참고파일 읽기 및 공개 채용 원문 검색을 확인했다. ZIP 업로드 UI와 자동 선택은 별도 미검증이다.
Claude/Gemini 및 각 CLI의 로딩·검색·메모리는 이 결과로 대신하지 않는다.
검증되지 않은 메뉴를 찾느라 멈추기보다 위 한 파일 대체 경로를 사용할 수 있다.

## 개발 환경

소스 압축을 풀고 그 폴더에서 실행한다. 설치기 기본 동작은 경로 확인이며 `--apply`가 실제 복사 승인이다.

```sh
python scripts/install_skill.py --host codex --scope project --apply
python scripts/install_skill.py --host claude-code --scope project --apply
python scripts/install_skill.py --host gemini-cli --scope project --apply
```

세 명령을 모두 실행할 필요는 없다. 쓰는 환경 하나만 선택한다.
기존 동명 스킬이 있으면 덮어쓰지 않고 중단한다. 기존 버전과 비교 후 별도 백업/교체를 승인한다.
Gemini CLI의 자체 설치 방법도 가능하다: `gemini skills install ./skills/job-research`.
Codex는 `$job-research`, Claude Code는 `/job-research`, Gemini CLI는 스킬 목록/활성화를 확인한 뒤 자연어로 요청한다.
명령이나 UI가 현재 버전과 다르면 공식 문서와 실제 도움말을 먼저 확인한다.

## 첫 실행 확인

스킬 이름/버전과 참고파일 읽기가 가능한지, 공개 페이지를 실제로 읽는지 확인한다.
관찰된 직접 URL을 눌러 보고, 선택한 한 공고만 지원 준비로 이어지는지 확인한다.
메모리·저장·예약은 각각 가능한 것만 확인한다. 원격 설치 성공을 로컬 복사 결과에서 추정하지 않는다.
[공식 근거와 환경별 범위](docs/compatibility.ko.md)
