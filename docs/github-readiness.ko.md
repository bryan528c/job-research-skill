# GitHub 배포 상태 — 2026-11-06

대상: https://github.com/bryan528c/job-research-skill

- 소유자가 RC 공개와 MIT 적용을 승인했다. 개인 계정에 동명 저장소가 없는 것을 API와 생성 화면에서 확인한 뒤 새 **공개** 저장소를 만들었다.
- 생성 후 API에서 소유자·public 표시·admin/push 권한을 확인했다. 원본 소스 49개를 실제 기록하고 브랜치를 생성했다. 메타데이터만으로 쓰기 성공을 추정하지 않았다.
- 원본 소스의 원격 tree `60de2d4a877222ae5e2cf6d545cc620e1e71858d`는 로컬 원본 tree와 동일하다. 원격 보존 커밋은 `5ef077d76c2f153e6f9610e990053691ddff1e7f`다.
- `archive/rc1-handoff`에 원본 소스를 보존하고, `validation/0.2.0-rc.2`에서 검증본을 준비했다. Git 데이터 API로 내용을 기록했으므로 원격 커밋 ID와 원래 로컬 커밋 ID는 다르다. 원본 ZIP과 로컬 이력은 인계 ZIP의 원본 파일 및 Git bundle로도 보존한다.
- MIT는 루트 LICENSE, 네이티브 스킬, 설치 ZIP 3종, 한 파일 지침에 동일하게 포함한다.
- 검증본 90개 파일의 원격 tree `c6f74d2ef72bc9e633bb8d215c620877aeeaf688`도 로컬과 일치했다. 설치 ZIP 3종의 blob 해시를 확인하고 LICENSE를 원격에서 다시 읽었다.
- [PR #1](https://github.com/bryan528c/job-research-skill/pull/1)의 검증 커밋 `de772138604e5aa1462e3cb3db89b8166ee7ebce`에서 [GitHub Actions 실행 42156873339](https://github.com/bryan528c/job-research-skill/actions/runs/42156873339)가 성공했다. Python 3.10·3.13 두 작업에서 96개 검사, 빌드, 배포 무결성 검사, 재빌드 후 무변경 검사가 모두 통과했다.
- 위 증거는 이 문서 갱신 직전의 검증 커밋을 가리킨다. 이후 최종 커밋의 CI·병합·프리릴리스 상태는 PR과 [Releases](https://github.com/bryan528c/job-research-skill/releases)에서 확인한다. 문서에 기록하기 위해 아직 실행하지 않은 다음 단계를 성공으로 선기입하지 않는다.

인증 중 사용한 계정 정보·코드·세션 데이터는 소스와 공개 검증 기록에 포함하지 않았다.
ChatGPT Work 개인 스킬 저장 성공과 GitHub 쓰기는 별도 검증이다. 기존 개인 채용 리서치 예약·알림은 조회하거나 변경하지 않았다.
