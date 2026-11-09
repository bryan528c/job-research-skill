# 실제 출처 계약 — 2026-11-09

원본·개인 상태는 공개 배포하지 않는다. 다음은 실제 Python 수집기와 private SQLite로 검증한 범위다.

| 출처 | 실제 적재/검증 | 한계 |
|---|---|---|
| [KRX](https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13) | 2,765행/1페이지 | 상장 범위. 영문 포함 코드 74개 누락 결함 수정. 상장=중견 판정 금지 |
| [DART 회사개황](https://dart.fss.or.kr/dsae001/main.do) | 공개 downloadExcel.do, 119,967 원본행→119,912 출처 ID | 법인/사업자번호 충돌 4건 분리 보존, completeness=partial. 한국 모든 법인 아님 |
| [공정위 소속회사](https://www.egroup.go.kr/egps/wi/stat/kap/psitnCmpnySumryList.do) | 2026 지정년/36페이지, 3,539 관계→3,521 ID | 겹친 소속 관계 18개 보존. 그룹 소속≠개별법인 규모 |
| [중견 확인서](https://www.mme.or.kr/PGMV0110.do) | 2026 발급년/41페이지, 4,084 발급→4,002 사업자 ID | 중복 82건. 발급취소 포함 가능, 현재 중견 전체 명단 아님 |
| OpenDART corpCode/고용24 API | 기존 parser/worker 유지 | 키 미설정으로 실인증 not_run. 다른 키 없는 실제 경로는 실행 |
| [SK Careers](https://www.skcareers.com/Recruit) | 브라우저 더보기 116/116과 native 공개 검색116건 일치, 실제 상세/지원 로그인 경로 | /Recruit/GetRecruitList 공개 검색만 read-only POST allowlist. 지원서 POST 없음. 일부 변형 상세 host 대기 |
| Ninehire/Applyin | sitemap/목록→SSR·JSON 상세, 실제 이미지 열람→개별 직무 | 혼합 공채 분해 전 추천 차단. sitemap≠모집목록 완전성 |
| Linkareer/사람인/잡코리아 | 공개 HTML 목록·실제 상세 GET, 공개 HTML Apollo 상태/JSON-LD 파싱 | visible links만으로 플랫폼 전체 완료 처리 안 함. 페이지 끝/이미지/지원 상태는 별도 검수 |
| 롯데그룹/Greeting | 독립 누락 감사 후 실제 현재목록 13/13·9/9 적재, 상세·이미지 검수 큐 확장 | 전체 그룹/모든 ATS 대응은 미완료. 과거 Greeting landing의 만료 링크를 현재 공고로 승격하지 않음 |
| 한화/LG/그 밖의 그룹·ATS | 실제 발견 링크를 discovery/host 큐로 유지 | JS shell·전용 상세/지원 검증 미완료. 비공개 API·로그인·캡차 우회 없음 |
| Greenhouse/Ashby | 기존 공개 API 어댑터 유지 | 이 해외 경로로 한국 시장 검증을 대신하지 않음 |

네 명부 출처 ID 130,200개는 한국의 고유 기업 수가 아니다. 원본행·적재 ID·공식 식별자 alias·
충돌·미확정 법인·채용 채널을 구분한다. 동일 공식 식별자로만 연결하며 이름·브랜드 유사성으로
합치지 않는다. 새 platform employer도 법인 미확정 레코드로 보존한다.

명부는 total 변화·반복 페이지·마지막 페이지·첫 페이지 재검사를 검증한다. source snapshot
complete는 해당 범위만 뜻하고 national_coverage는 unknown이다. HTTP는 공개 IP pinning,
redirect 재검사, 크기/시간 상한, robots와 backoff를 적용한다. SK 검색 외 POST는 거부한다.
공개 DART 엑셀과 인증키가 필요한 OpenDART corpCode는 별개다.
