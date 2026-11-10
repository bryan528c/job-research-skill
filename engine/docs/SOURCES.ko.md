# 실제 출처 계약 — 2026-11-10

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
| LG Careers/한화인 | 공개 JSON 읽기 목록79/75와 모든 상세, 실제 개별123/66직무 | 11/10 목록79/73, 새1개 상세까지 확장. EDITOR의 숨은 stale unit은 업무로 사용하지 않음 |
| Jobflex/큐셀 | 필터 없는 실제15페이지142카드, 현재6개 포스터/15직무 | 접수중 필터5개 누락을 반증. 공개 nonsecret tenant selector만 사용 |
| 세스코·하이컨시·제이시스·가비아 | 공식84/11/28/13 전체목록·상세136개, 세스코 이미지74 실제 판독 | Ninehire 부서는 법인 아님. Greeting 개별 CTA/근무지, Gabia 공개 site-info/list/detail 계약. 제이시스 이미지1은 robots 차단 |
| 한화오션 | 실제 연결11상세·포스터2·공개 모집분야 표·41직무 | 전체 Ocean 목록 아님. 별도 신입 회차/7차단경로도 추적 |
| CJ/두산 | CJ14페이지138목록·상세138, 두산28목록·상세28/67저장직무 | CJ 현재107/종료31 구분. 부모/포털/Pool은 개별 공석 수와 다름. 빈칸 후속 자격행 보존 |
| 현대자동차 | 정상 브라우저6페이지54목록/마지막 이동 종료 확인 | 전체 상세/지원 검수 미완료. 실제54경로를 host frontier로 보존, 접속 대기 우회 없음 |
| 올리브영·사세 | 실제 공개 SSR200/7과 상세200/7, 위치/경력/고용 메타 분리 | 올리브영 실제 UI끝200·사이트맵200과 대조. 사세7도 실제 사이트맵과 일치 |
| CJ올리브네트웍스 독립 공홈 | 정상 공개 UI4페이지35행(현재32/마감3)과 개별 CJ ID 대조 | 기존 CJ 범위와 중복. 기본 native UA 차단과 OpenAI 도구 명시 허용을 구분, UA를 위장하지 않음 |
| Greenhouse/Ashby | 기존 공개 API 어댑터 유지 | 이 해외 경로로 한국 시장 검증을 대신하지 않음 |

네 명부 출처 ID 130,200개는 한국의 고유 기업 수가 아니다. 원본행·적재 ID·공식 식별자 alias·
충돌·미확정 법인·채용 채널을 구분한다. 동일 공식 식별자로만 연결하며 이름·브랜드 유사성으로
합치지 않는다. 새 platform employer도 법인 미확정 레코드로 보존한다.

명부는 total 변화·반복 페이지·마지막 페이지·첫 페이지 재검사를 검증한다. source snapshot
complete는 해당 범위만 뜻하고 national_coverage는 unknown이다. HTTP는 공개 IP pinning,
redirect 재검사, 크기/시간 상한, robots와 backoff를 적용한다. 검토한 읽기 route 외 POST는 거부한다.
공개 DART 엑셀과 인증키가 필요한 OpenDART corpCode는 별개다.

LG/Hanwha의 POST는 정확히 검토한 익명 읽기 JSON route만 허용한다. SK 공개 검색 외 임의
POST나 지원서 제출은 구현하지 않는다. Jobflex/Gabia/CJ는 관측한 공개 읽기 계약을 쓴다.
`universe-audit`의 분모/실제 관측 귀속/미확정 채널과 그룹·ATS 별도 범위를 대조한다.
[후속 실제 검증](VALIDATION.20261110.ko.md)을 이전 날짜의 기록과 구분한다.
