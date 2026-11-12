# Implementation Plan: 만든 말을 실무 용어로 바꾸기 (판 → 버전 · 판 요약 → 매니페스트 등)

> 작성/운영 규칙(SoT): `/impl-plan` 스킬(`~/.claude/skills/impl-plan/SKILL.md`)을 반드시 참고하세요.  
> (이 템플릿을 수정하거나 새로운 양식의 계획서를 만들 때도 해당 스킬을 포인터로 두고 준수합니다.)

**상태**: ✅ Done

---

> 상태는 🟡 Draft / 🔄 In Progress / ✅ Done. Done 조건과 기록 규칙은 `/impl-plan` 「3) 스킵 및 완료 규칙」이며 `~/.claude/hooks/plan_lint.py` 가 저장 때 검사한다.

---

**작성일**: 2026-11-12 08:55
**마지막 업데이트**: 2026-11-12 10:09
**관련 범위**: 갱신(update · edition · revision · new_days · catalog) · 내보내기 · 합성 검증 표(leveraged/comparison · products) · 문서 · 데이터 파일 이름 · 사용처 quant 의 문서 4곳과 사본
**관련 문서**: `~/.claude/docs/실무_용어.md` (쓰는 말의 정본) · 전역 `~/.claude/CLAUDE.md` 「실무 용어를 쓴다」

---

## 1) 목표(Goal)

- [x] 목표 1: 살아있는 문서 · 코드 · 테스트 · 사용자에게 보이는 문구의 만든 말을 `~/.claude/docs/실무_용어.md` 의 쓰는 말로 바꾼다 — 잔여 검사에 남는 줄이 3장 「바꾸지 않는 것」과 정확히 같다
- [x] 목표 2: 식별자 · 파일 이름을 그 영어 대응어로 맞춘다 (3장 「식별자 · 파일 이름」 표)
- [x] 목표 3: 데이터는 이름과 라벨만 바뀐다 — 시세 · 계열 · 합성 CSV 바이트 같음, 매니페스트 · `assumptions.csv` 는 이름 · 라벨만 (매니페스트는 `--no-fetch` 로 다시 써 받는 자료 31개의 상태가 「미수집」 — 3장 데이터/결과 영향에 적고 승인받음)
- [x] 목표 4: 사용처 quant 의 문서 4곳과 사본 이름을 맞춘다

## 2) 비목표(Non-Goals)

- **실물 · 합성 · 대용은 이름을 그대로 둔다** — 2026-11-12 결정. 업계 뜻과의 충돌은 전역 용어표 3절이 맡는다
- 이미 실무 용어인 말: 판정 · 기준일 · 기준가 · 수정주가 · 분배 · 첫날 · 끝날 · 가공 · 고정 · 비정상 · 받아들임 · 제외 · 대조
- 매니페스트 JSON 의 키(기준일 · 파일 · 종목 · 첫날 · 끝날 · 행 수 · 상태 · 분배 기록 첫날 · 분배 대조 어긋난 날)와 허용 목록 CSV 헤더(`종목,날짜,검사,사유,근거`) — 쓰는 말이라 그대로
- 실행 명령 · CLI 옵션(`--exclude` · `--accept` · `--no-fetch` · `--end`)
- 판정 · 가공 동작 — 이름만 바꾼다
- 「계열」 단독(QQQ 계열 · 계열 파일 등)과 「머리말」 — 「하루 한 값 계열」 구와 CSV 의 「머리」만 바꾼다
- 부사 「새로」(새로 받은 · 새로 더한) — 상태 라벨 「새로」만 바꾼다
- 완료된 계획서 `docs/plans/PLAN_quant_data_split.md` — 계획서 수정 규칙(체크리스트 · 진행 로그 외 수정 금지)
- verify-lab · research-lab — 판 요약 · 새로 붙는 날 · 패스 목록이 0회(3장 측정)
- 새로 받기 — 갱신은 `--no-fetch` 만 돌린다
- git 처리

## 3) 배경/맥락(Context)

### 현재 문제점 / 동기

- 사용자(2026-11-12): 「새로 누른날, 판 이런게 너무 익숙하지 않아. 버전?같은건 어때? 실제로 실무에서 사용하는 단어로 쓰고 싶어. 그리고 다른 단어도 그런것 있는지 점검」
- 점검에서 실무 용어가 따로 있는 만든 말이 「판」 · 「판 요약」 · 「새로 붙는 날」 · 「패스 목록」 · 「흔들림」 · 「짝」 등으로 나왔다. 「판」 단독만 318회 · 30개 파일이다(HEAD 기준, 계획서 · storage 제외, 판정 · 판단 · 판독 · 판별 · 판매 · 판다(판다스)를 뺀 정규식 집계)
- 쓰는 말의 대응은 전역 `~/.claude/docs/실무_용어.md` 에 두었다 — 기행기소 프로젝트도 참조하고 다듬는다(2026-11-12 사용자 결정). 이 계획은 그 표대로 quant-data 를 바꾼다
- 글자 규칙이 막거나 되돌릴 수 없는 결과에 물리는 설계 — 해당 없음(판정 규칙을 새로 만들지 않는다)

### 결정 기록 (2026-11-11 ~ 12 — 이 계획의 기준, 다시 묻지 않는다)

| 항목 | 결정 |
|---|---|
| 말의 대응 | 전역 용어표 1 · 2절 전부 |
| 파일 · 식별자 | 한글 말과 맞춘다 — 영어 대응어로. quant 문서 4곳과 사본 이름도 함께 |
| 실물 · 합성 · 대용 | 이름 유지, 전역 용어표 3절에 충돌 메모 |
| 합성 문서 2장 용어 표 | 그 자리에 둔다 — 그 저장소 코드 경로를 가리키는 정의라 전역에 둘 수 없다. 쓰는 말만 맞춘다 |
| 원본가 | 「원시 ○○」(가격 · 종가 · 시가 · 시세 · 값)를 「원본가 · 원본 ○○」로 통일 |

### 말 바꾸기 규칙 — 문맥으로 가르는 말

일괄 치환하지 않는다. 파일마다 문맥을 보고 아래 기준으로 바꾼다.

| 지금 | 바꿀 말 | 가르는 기준 |
|---|---|---|
| 판 (갱신이 남긴 데이터 상태) | 버전 | 반쯤 갱신된 판 → 반쯤 갱신된 버전 |
| 옛 판 | 이전 버전 | |
| 첫 판 | 최초 수집 · 첫 버전 | 처음 받는 일이면 「최초 수집」, 그때의 데이터면 「첫 버전」 |
| 판 (가정만 바꾼 계산) | 시나리오 | 채택 · 상한 없음 · 가산금리 0 · 배당 보정 시나리오 |
| 순수판 · 호주달러 판 등 변형 계열 | 문맥대로 | 「전 구간 스케일 시계열」 · 「호주달러 값」처럼 무엇인지 쓴다 |
| 판 요약 | 매니페스트 | |
| 새로 붙는 날 (검사) | 신규 일자 (검사) | |
| 패스 목록 | 허용 목록 | |
| 흔들림 · 흔들림 상한 · 흔들림뿐 | 노이즈 · 허용 오차 · 노이즈뿐 | |
| 설명되는 변화 · 기록으로 설명되는 변화 (라벨) | 배당 반영 | 예외는 「바꾸지 않는 것」 5 |
| 짝 · 짝 대조 · 짝 없음 · 짝 지수 | 벤치마크 · 벤치마크 대조 · 벤치마크 없음 · 벤치마크 지수 | |
| 짝 차이 (검사) | 추적 차이 | |
| 두 출처 (대조 · 검사) | 교차 확인 | 검사 이름: 두 출처 일치 → 교차 확인 일치, 두 출처 차이 → 교차 확인 차이 (처음 「교차 검증」 → 국내 퀀트 · ML 의 cross-validation 과 겹쳐 2026-11-12 리뷰 1회차 뒤 사용자 결정으로 바꿈) |
| 머리 (CSV) · 머리줄 | 헤더 · 헤더 줄 | 「머리말」은 그대로 |
| 열쇠 | 키 | |
| 몫 | ○○ 용 · ○○ 부분 | 자료를 가리키면 「용」, 일의 부분을 가리키면 「부분」 |
| 하루 한 값 계열 (구) | 일별 시계열 | 「하루 한 값인 계열」 · 「하루에 값 하나인 계열」 포함 |
| 원인 블록 · 원인 줄 | 진단 출력 · 진단 줄 | |
| 상태 라벨 「새로」 · 「받지 않음」 | 신규 · 미수집 | 라벨일 때만 |
| 원시 가격 · 원시 종가 · 원시 시가 · 원시 시세 · 원시 값 | 원본가 · 원본 종가 · 원본 시가 · 원본 시세 · 원본 값 | 「원시 그대로」 같은 구도 「원본가 그대로」처럼 |

### 식별자 · 파일 이름

| 지금 | 바꿀 이름 |
|---|---|
| `storage/edition.json` | `storage/manifest.json` |
| `storage/records/pass_list.csv` | `storage/records/allowlist.csv` |
| 사용처 사본 `quant_data_edition.json` | `quant_data_manifest.json` |
| `src/quant_data/edition.py` | `src/quant_data/manifest.py` |
| `EDITION_PATH`(constants · export) · `EDITION_FILE_NAME` | `MANIFEST_PATH` · `MANIFEST_FILE_NAME` |
| `read_edition` · `write_edition` · export 의 `_read_edition` | `read_manifest` · `write_manifest` · `_read_manifest` |
| `_check_edition_matches_files` · `_edition_entries` | `_check_manifest_matches_files` · `_manifest_entries` |
| `STATUS_EXPLAINED` · `RevisionKind.EXPLAINED` | `STATUS_DIVIDEND_ADJUSTED` · `RevisionKind.DIVIDEND_ADJUSTED` |
| `PASS_LIST_PATH` · `PASS_LIST_COLUMNS` · `PassEntry` · `load_pass_list` | `ALLOWLIST_PATH` · `ALLOWLIST_COLUMNS` · `AllowlistEntry` · `load_allowlist` |
| `Dataset.pair` · `pair_name` 등 벤치마크를 뜻하는 `pair` | `benchmark` (값 두 개의 묶음 같은 다른 뜻이면 그대로) — 단 `Dataset` 필드는 미국 벤치마크와 비트코인 교차 확인 상대를 함께 담아 `reference`(비교 대상), 비트코인 쪽 `check_coin_cross` 인자 · `_reference_series` 도 `reference` (2026-11-12 리뷰 1회차 뒤 사용자 결정) |
| `check_pair` · `Check.PAIR` · `PAIR_TOLERANCE_PER_LEVERAGE` | `check_tracking_difference` · `Check.TRACKING` · `TRACKING_TOLERANCE_PER_LEVERAGE` |
| `check_kr_two_sources` · `check_coin_two_sources` · `Check.KR_TWO_SOURCES` · `Check.COIN_TWO_SOURCES` · `COIN_TWO_SOURCES_TOLERANCE` | `check_kr_cross` · `check_coin_cross` · `Check.KR_CROSS_CHECK` · `Check.COIN_CROSS_CHECK` · `COIN_CROSS_CHECK_TOLERANCE` |
| `DISPLAY_VARIANT` 등 시나리오를 뜻하는 `variant` | `DISPLAY_SCENARIO` 등 `scenario` |
| 테스트 함수 · 클래스 이름 | 같은 대응 |

그대로 두는 이름: `new_days.py` · `appended_days` · `NewDayFailure`(new days = 신규 일자) · `REVISION_NOISE_TOLERANCE` · `revision.py`

### 데이터 값이 바뀌는 곳

- 매니페스트 상태 값 — 흔들림뿐 → 노이즈뿐 · 설명되는 변화 → 배당 반영 · 새로 → 신규 · 받지 않음 → 미수집
- 허용 목록의 검사 칸 값 — 짝 차이 → 추적 차이 · 두 출처 일치 → 교차 확인 일치 · 두 출처 차이 → 교차 확인 차이. 지금 파일은 헤더 한 줄뿐이라 옮길 행이 없다
- `storage/validation/assumptions.csv` 헤더 첫 칸 「판」 → 「시나리오」(`products.py:94` 의 `DISPLAY_VARIANT`)
- `RevisionKind` 값 — 흔들림뿐 → 노이즈뿐 · 기록으로 설명되는 변화 → 배당 반영(로그 · 진단 출력에만 쓰임)

### 착수 전 측정 (2026-11-12 — 읽기만)

- 「판」 단독이 든 «줄» 수가 많은 파일(git grep -c): `tests/test_update.py` 60 · `docs/research/시세_받기_판정.md` 27 · `src/quant_data/update.py` 26 · `docs/research/합성_시세_연장.md` 25 · `tests/test_export.py` 19 · `src/quant_data/export.py` 12 · `tests/test_leveraged_comparison.py` 10 · `src/quant_data/edition.py` 8 · `scripts/update.py` 7 · `src/quant_data/leveraged/comparison.py` 6 · `docs/COMMANDS.md` 5 (나머지 19개 파일은 4회 이하)
- 형제 저장소(계획서 제외 문서 · 코드): 판 요약 · 새로 붙는 · 패스 목록 0회. quant 의 「받은 판」 3회는 아래 quant 4곳과 겹친다. quant 의 「첫 판」 4회는 모두 「첫 판단」이다
- quant 코드는 `quant_data_edition.json` 을 읽지 않는다(grep 0건) — quant 쪽 바꿀 곳은 문서 4곳(루트 `CLAUDE.md:54-55` · `docs/COMMANDS.md:26` · `:136` · `src/qbt/CLAUDE.md:80`)과 사본 이름
- quant 가 받는 파일은 합성 8개뿐(`quant/storage/stock/quant_data_files.txt`) — 이번에 값이 바뀌는 파일이 아니다
- 갱신은 이전 매니페스트에서 첫날 · 끝날 · 행 수(대조)와 분배 기록 첫날(이월)만 읽고 상태 값은 읽지 않는다(`update.py` 의 `_edition_entries` · `_check_edition_matches_files`) — 파일 이름만 옮긴 뒤 `--no-fetch` 로 다시 쓰면 된다
- 지금 판 요약의 상태: 가공 17 · 고정 55 · 흔들림뿐 31 (103개)
- 잔여 검사 정규식(Phase 5)을 지금 파일에 돌림 — git grep 576줄 · 파이썬 `re` 576줄로 같다(한글 괄호식이 git grep 에서 제대로 동작). 걸린 낱말에 다른 뜻(짝수 · 출판 등)이 없다 — 앞에 한글이 붙은 「판」은 「순수판」 하나
- quant 는 시세를 고정 경로 상수로만 읽고 폴더를 훑지 않는다(`src/qbt/common_constants.py`) — 사본 이름을 바꿔도 읽기에 닿지 않는다
- 테스트는 실제 `storage/` 를 읽지 않는다(임시 폴더 · 상수 대조만) — Phase 1 의 그린이 Phase 2 의 파일 옮김에 기대지 않는다
- 품질 검증은 Ruff · PyRight · Pytest 뿐이라 문서 안의 경로 · 이름은 검사하지 않는다 — 문서는 잔여 검사와 Phase 3 의 실재 확인이 지킨다

### 바꾸지 않는 것 — 잔여 검사의 기대값

바꿀 말이 든 「」 인용을 전수 조사(git grep)해 가른 결과다. 아래만 남기고 나머지 「」(코드 메시지 · 라벨 · 절 제목을 가리키는 것)는 함께 바꾼다.

1. `docs/research/시세_받기_판정.md` Q2 의 「판 번호만 커밋」 — 옛 결정 이름
2. 같은 문서 Q31 의 (처음 「같은 자산의 다른 ETF 를 먼저 재고, 약하면 종목 자체 하루 변동 범위 + 패스 목록」) — 처음 안의 원문
3. 같은 문서 4장의 「판 것만」과 `docs/research/합성_시세_연장.md` 의 「폭락한 날 종가에 판 두 번」 — 「팔다」(2회차 리뷰 뒤 더함: 「매도한」으로 바꿨던 것을 요청 밖 변경이라 되돌림)
4. `docs/research/합성_시세_연장.md` 의 「상한 판 3배 연복리 19.96% → 20.56%」 — quant 의 다른 문서(`전략_검증_보고서.md` N.19) 인용
5. `docs/research/시세_받기_판정.md` 결정 14 의 「응답의 배당 · 분할 기록으로 설명되는 변화」와 바로 아래 「분할을 「설명되는 변화」에서 「비정상」으로 옮기고(Q23)」의 「설명되는 변화」 둘 — 그때의 분류는 분할도 담아, 「배당 반영」으로 바꾸면 결정을 틀리게 옮긴다. 같은 줄의 「흔들림」은 뜻이 같아 「노이즈」로 바꾼다. 6.1 · 5.1 표 · 6.9 · 그 밖의 「설명되는 변화」는 배당만 가리켜 「배당 반영」으로 바꾼다. 남기는 까닭은 근거 승격으로 문서 머리 「읽는 법」에 한 문장을 두고, 그 문장도 이 말을 적는다

잔여 검사의 기대 출력은 위 1 ~ 5 의 일치 **8건**이다(3 이 둘 · 5 가 셋). 같은 줄에 바꿀 말이 함께 있으면(Q2 줄의 「판 요약」 · Q31 줄의 「짝」 · 합성 문서 그 줄의 「배당 보정 판」) 그 말은 바꾼다 — 검사는 줄이 아니라 일치 단위(`-o`)로 본다

함께 바꾸는 「」의 예: `docs/DEFERRED_FINDINGS.md` 「판 요약에 없는데 파일이 있음」(코드 메시지) · `시세_받기_판정.md` 「판 요약과 데이터 파일을 …」(안내 메시지) · 「첫 판」 · 「새로」(라벨) · 「코인 두 출처」(3.2 절 제목과 함께) · 「TLT 2026-10-31 판 — …」(6.2 와 함께) · 6.9 의 「기록으로 설명되는 변화」(Q23 뒤의 라벨이라 배당 반영) · 테스트의 「판 요약」 · 「짝 없음」 · 「QQQ,2026-11-06,짝 차이」 등

### 영향받는 규칙(반드시 읽고 전체 숙지)

> 아래 문서에 기재된 규칙을 **모두 숙지**하고 준수합니다.

- `.claude/plan-config.json` — 이 저장소의 검증 명령·자동 포맷·근거 승격 목적지 (**값의 SoT**)
- 루트 `CLAUDE.md` — 특히 「계획서 규약 — 이 프로젝트의 설정」 절 (값이 아니라 **판단 근거**)
- 전역 `~/.claude/CLAUDE.md` — 「실무 용어를 쓴다」 · 「수술적 변경」 · 「주석은 코드가 못 하는 말만 한다」 · 「문서」 · 「원본을 가공하지 않는다」
- `~/.claude/docs/실무_용어.md`
- `~/.claude/rules/python.md` · `~/.claude/rules/python-tests.md`
- quant 루트 `CLAUDE.md` · `src/qbt/CLAUDE.md` — quant 문서를 고치기 전에 `Read` 로 연다(다른 저장소 규칙은 자동으로 실리지 않는다)

## 4) 완료 조건(Definition of Done)

> Done은 "서술"이 아니라 "체크리스트 상태"로만 판단합니다. (정의/예외는 `/impl-plan` 스킬)

- [x] 잔여 검사(Phase 5 의 명령)의 일치가 「바꾸지 않는 것」 1 ~ 5 의 8건과 정확히 같다
- [x] 옛 식별자 · 파일 이름 grep 0건(코드 · 테스트 · 문서) — 다른 뜻이라 남긴 `pair` 자리는 진행 로그에 위치와 함께
- [x] 데이터: `--no-fetch` 뒤 diff 가 매니페스트(이름 · 상태 라벨) · `assumptions.csv` 헤더 한 줄 · 허용 목록 이름뿐이고, 매니페스트 103개 항목의 첫날 · 끝날 · 행 수가 이전 파일과 같다
- [x] 내보내기를 임시 폴더로 돌려 `quant_data_manifest.json` 이 생기고 합성 8개가 quant 사본과 바이트 같다
- [x] quant 문서 4곳을 맞췄다 (사용자 커밋 `c635f8e` 에 들어감)
- [x] quant 사본 교체(내보내기 · 옛 사본 삭제) — 실행 때 승인: 승인 · 반영 (2026-11-12 09:39)
- [x] 코드 리뷰 실행 및 결과 기록 (마지막 Phase 의 Validation 에 적는다)
- [x] 품질 검증 통과 (마지막 Phase 의 Validation 에 passed/failed/skipped 수를 적는다)
- [x] 자동 포맷 적용 완료 (마지막 Phase에서 실행)
- [x] 문서 업데이트 — README · 루트 `CLAUDE.md` · `docs/COMMANDS.md`(변경 있음 — 설명 · 파일 경로만, 명령 · 옵션 그대로) · 두 연구 문서 · `docs/DEFERRED_FINDINGS.md`(자리 · 함수 이름)
- [x] 근거 승격 완료 — 이 계획서를 지금 삭제해도 잃을 정보가 없다 — 말의 대응 · 근거 · 확정일과 바꾸는 법(문맥 가름 · 「」 인용 · 조사 · 줄바꿈 · `--untracked`)은 전역 `~/.claude/docs/실무_용어.md`, 결정 14 의 옛 분류 이름을 남기는 까닭은 `docs/research/시세_받기_판정.md` 「읽는 법」, 라벨 · 파일 이름 · 검사 이름의 계약은 테스트 5개가 고정
      (결정 근거·실측 수치를 `.claude/plan-config.json` 의 `evidence_home` 이 정한 폴더로 이관. 그 폴더를 요청할 때만
      고치는 저장소면 반영안을 제안하고 「제안함 — 승인 · 반영 / 보류」로 적는다. `/impl-plan` 스킬 "근거 승격" 참고)
- [x] 미룬 지적 옮김 — 해당 없음(옮길 것 없음 — 거른 지적은 진행 로그의 코드 리뷰 1회차 · 2회차 항목에 기준 번호와 함께). 고치지 않은 리뷰 지적을 거르는 기준으로 걸러 `deferred_findings` 파일로 옮겼다. 계획서 없이 읽히게 썼다.
      거른 지적은 진행 로그에 기준 번호와 함께 남기고 Done 보고에 표로 냈다
      이 계획서가 그 파일의 항목을 고쳤다면 그 항목을 지웠다
      (둘 다 없으면 「해당 없음」. `/impl-plan` 의 `review.md` 「미룬 지적 옮기기」 참고)
- [x] plan 체크박스 최신화(Phase/DoD/Validation 모두 반영)

## 5) 변경 범위(Scope)

### 변경 대상 파일(예상)

목록은 착수 전 집계로 잡은 것이다 — 완료 기준은 목록이 아니라 잔여 검사다.

- `src/quant_data/`: `update.py` · `edition.py`(→ `manifest.py`) · `constants.py` · `export.py` · `new_days.py` · `revision.py` · `catalog.py` · `domestic.py` · `products.py` · `cli.py` · `leveraged/comparison.py` · `leveraged/synthetic.py` 와 그 밖에 잔여 검사가 잡는 파일
- `scripts/update.py` · `scripts/export.py`
- `tests/`: `test_update.py` · `test_export.py` · `test_new_days.py` · `test_revision.py` · `test_catalog.py` · `test_leveraged_comparison.py` · `test_leveraged_synthetic.py` · `test_prices.py` · `test_proxy_series.py` · `test_products.py` · `test_leveraged_simulation_cost_model.py` · `test_gold_proxy.py` · `test_cli.py` 와 그 밖에 잔여 검사가 잡는 파일
- 문서: `README.md` · 루트 `CLAUDE.md` · `docs/DEFERRED_FINDINGS.md` · `docs/research/시세_받기_판정.md` · `docs/research/합성_시세_연장.md`
- `docs/COMMANDS.md`: **변경 있음** — 실행 명령 · CLI 옵션은 그대로, 설명 문구와 파일 경로(`storage/manifest.json` · `storage/records/allowlist.csv`)만
- 데이터: `storage/edition.json` → `storage/manifest.json`, `storage/records/pass_list.csv` → `storage/records/allowlist.csv`, `storage/validation/assumptions.csv`(헤더)
- quant: 루트 `CLAUDE.md` · `docs/COMMANDS.md` · `src/qbt/CLAUDE.md`, `storage/stock/quant_data_edition.json` → `quant_data_manifest.json`(실행 때 승인)

### 데이터/결과 영향

- 시세 · 계열 · 합성 CSV 의 값은 바뀌지 않는다 — 동작을 바꾸지 않고, Phase 2 의 바이트 대조로 확인한다
- 매니페스트는 `--no-fetch` 로 다시 쓰므로 받는 자료의 상태가 「미수집」이 된다 — 지난 받기의 「흔들림뿐」 기록은 git 이력에 남고, 다음 받는 갱신이 다시 적는다
- `assumptions.csv` 는 헤더 첫 칸만 바뀐다
- quant 사본: 이름 · 상태 라벨 · 적힌 커밋 번호가 바뀐다

## 6) 단계별 계획(Phases)

### Phase 0 — 테스트를 새 이름 · 라벨로 먼저 바꾼다(레드)

데이터에 남는 라벨(매니페스트 상태 · 허용 목록 검사 이름 · `assumptions.csv` 헤더)과 메시지는 사용자 · 사용처가 읽는 계약이라 테스트로 먼저 고정한다.

**작업 내용**:

- [x] 테스트의 import · 식별자 · 라벨 기대값 · 메시지 `match` · docstring 의 말을 3장 표대로 바꾼다 (테스트 함수 · 클래스 이름 포함)
- [x] Given / When / Then 의 값과 판정 기대는 바꾸지 않는다 — 이름과 라벨만

**Validation**:

- [x] 바꾼 테스트 파일의 pytest 가 옛 이름 · 옛 라벨 때문에만 실패한다 — 수집 오류 5(없는 이름: `quant_data.manifest` · `MANIFEST_PATH` · `SCENARIO_ADOPTED` · `COIN_CROSS_CHECK_TOLERANCE` · `RevisionKind.DIVIDEND_ADJUSTED`), 실패 4(`Dataset.benchmark` 없음 2 · 메시지 「헤더」 2), 266 passed

---

### Phase 1 — 소스의 이름 · 라벨 · 문구(그린)

**작업 내용**:

- [x] `edition.py` → `manifest.py` (파일 옮김), 3장 「식별자 · 파일 이름」 표대로
- [x] 라벨 · 사용자에게 보이는 메시지 · docstring · 주석의 말을 3장 「말 바꾸기 규칙」대로 — 일괄 치환하지 않고 파일마다 문맥을 본다
- [x] 경로 상수: `MANIFEST_PATH` = `storage/manifest.json`, `ALLOWLIST_PATH` = `storage/records/allowlist.csv`, export 쪽 같은 값
- [x] `RevisionKind.EXPLAINED` 가 배당만 담는지(Q23 — 분할은 비정상) 코드로 확인한 뒤 `DIVIDEND_ADJUSTED` 로 — 분할 기록은 진단 줄(issues)에 들어가 비정상이 되고(`revision.py` 의 `_kind`), 배당 반영은 진단 줄이 없을 때만 나온다

**Validation**:

- [x] Phase 0 에서 바꾼 테스트 파일 pytest 그린 — 바꾼 테스트 파일 전부 433 passed

---

### Phase 2 — 데이터 파일 이름과 실데이터 동작 확인

**작업 내용**:

- [x] 파일 옮김: `storage/edition.json` → `storage/manifest.json`, `storage/records/pass_list.csv` → `storage/records/allowlist.csv` (git 처리는 사용자)
- [x] `docs/COMMANDS.md` 의 받지 않는 갱신(`--no-fetch`)을 돌린다 — 5.6초, 21개 파일 씀
- [x] 결과 대조 — 이전 매니페스트(git 의 `storage/edition.json`)와 새 매니페스트의 항목 수 · 경로 · 첫날 · 끝날 · 행 수 · 분배 기록 첫날을 파이썬으로 견준다

**Validation**:

- [x] 종료 코드 0, `git status` 의 storage 변경이 `edition.json` → `manifest.json` · `pass_list.csv` → `allowlist.csv`(바이트 같음) · `assumptions.csv` 헤더 한 줄(「판」 → 「시나리오」)뿐 — 다시 쓴 합성 · 국내 수정주가 CSV 는 바이트 같음
- [x] 매니페스트 103 → 103개, 경로 순서까지 같고 상태 밖 필드(종목 · 첫날 · 끝날 · 행 수 · 분배 기록 첫날 · 분배 대조 어긋난 날) 차이 0 · 키 집합 같음. 상태: 흔들림뿐 31 → 미수집 31, 고정 55 · 가공 17 그대로

---

### Phase 3 — quant-data 문서

**작업 내용**:

- [x] `README.md` · 루트 `CLAUDE.md` · `docs/COMMANDS.md` · `docs/DEFERRED_FINDINGS.md` · 두 연구 문서를 3장 규칙대로 — 「바꾸지 않는 것」 1 ~ 5 는 자리표시로 막고 적용
- [x] `docs/DEFERRED_FINDINGS.md` 의 「자리」(함수 이름 · 줄 번호)를 새 코드에 맞춘다 — 함수 이름은 맞춤. 줄 번호는 Phase 5 의 black(`new_days.py` +4 · `update.py` +9줄) 뒤에 맞춤: `update.py:511` → `:514`(호출 자리 — HEAD 에서도 이미 `:507` 로 어긋나 있었음), `:291 · :311 · :335` → `:293 · :313 · :337`. 그 뒤 비교 대상 이름 변경으로 `catalog.py` docstring 이 한 줄 늘어 `:155-157` → `:156-158`. 같은 항목의 `catalog.py:94 · :96` · `products.py:71` 은 이 계획 전부터 어긋나 있던 값이라 고치지 않음(2회차 리뷰 지적 — 이름이 함께 적혀 있어 찾을 수 있다)

**Validation**:

- [x] 문서가 가리키는 경로 · 함수 이름이 실재한다 — 바뀐 줄의 백틱 경로(`storage/manifest.json` · `storage/records/allowlist.csv` 등)와 새 이름(`_check_manifest_matches_files` · `check_coin_cross` · `assumption_scenarios`) 모두 있음

---

### Phase 4 — 사용처 quant

**작업 내용**:

- [x] quant 루트 `CLAUDE.md` · `src/qbt/CLAUDE.md` 를 `Read` 로 연다 — quant 루트 `CLAUDE.md` 「결과 비교 중일 때 quant-data 갱신 · 내보내기를 함부로 다시 돌리지 않습니다」가 실제 내보내기의 승인 근거
- [x] 문서 4곳: 「받은 판」 → 「받은 버전의 매니페스트」(파일을 가리키므로), `quant_data_edition.json` → `quant_data_manifest.json` — quant 작업 트리의 커밋 안 된 변경 16개(다른 계획 `PLAN_epsilon_to_backtest`)와 겹치는 파일 없음
- [x] 내보내기를 임시 폴더(scratchpad)로 — quant 의 목록 파일을 복사해 두고 `docs/COMMANDS.md` 「내보내기」 명령의 `--to` 만 그 폴더로
- [x] (실행 때 승인) quant 로 내보내기 — quant 의 데이터를 바꾸는 실행 — 2026-11-12 09:39 사용자 승인, 내보내기 전 `storage/stock/` 사본을 떠 두고 실행
- [x] (실행 때 승인) quant 의 옛 사본 `storage/stock/quant_data_edition.json` 삭제 — 같은 승인

**Validation**:

- [x] 임시 폴더에 `quant_data_manifest.json` 이 생기고, 합성 8개가 quant 사본과 바이트 같다(`cmp`) — 실제 quant 로 내보낸 뒤에도 8개 모두 내보내기 전 사본과 같음
- [x] quant 의 문서 · 코드에 `quant_data_edition` · 「받은 판」 0건 — 문서 4곳은 사용자 커밋 `c635f8e` 에 이미 들어갔고, quant 작업 트리에 남은 변경은 사본 교체 둘(`D quant_data_edition.json` · `?? quant_data_manifest.json`)뿐

---

### Phase 5(마지막) — 잔여 검사 및 최종 검증

**작업 내용**

> 🔴 **체크박스와 상태를 먼저 확정하고, `/commit` 은 맨 마지막에** — 이유는 `/impl-plan` 「5) Commit Messages」.

- [x] 잔여 검사 — 저장소 루트에서 아래 명령. 일치가 「바꾸지 않는 것」 1 ~ 5 의 8건과 정확히 같다
      `git -c core.quotepath=off grep --untracked -n -o -I -E '판([^정단독별매다]|$)|새로 붙는|패스 목록|패스[가는를]|흔들림|설명되는 변화|설명된 변화|짝|두 출처|교차 ?검증|열쇠|몫|원인 (블록|줄)|원시|하루 한 값(인)? 계열|하루에 값 하나인 계열|머리([^말]|$)|「새로」|「받지 않음」|"새로"|"받지 않음"' -- . ':!docs/plans' ':!storage'`
      (「판다」는 「판다스」(pandas), 「하루 한 값」은 「하루 한 값으로 쓴다」 같은 평문이 걸려 뺐다 — 2026-11-12 Phase 0 에서 확인.
      `--untracked` 는 옮긴 파일(`manifest.py` 등)이 커밋 전이라 git grep 이 건너뛰는 것을 막는다 — Phase 1 에서 4줄이 빠졌던 것을 확인)
- [x] 옛 식별자 · 파일 이름 grep 0건 — 같은 경로 범위(코드 · 테스트 · 문서)에서 `edition` · `EDITION` · `pass_list` · `PASS_LIST` · `PassEntry` · `two_sources` · `TWO_SOURCES` · `PAIR` · `variant` · `VARIANT`, 그리고 벤치마크를 뜻하는 `pair`
- [x] 필요한 문서 업데이트 — `docs/COMMANDS.md` 변경 있음(Phase 3)
- [x] 자동 포맷 적용 (`poetry run black .`) — 이름이 바뀌며 생긴 import 정렬은 `ruff check --select I --fix`
- [x] 변경 기능 및 전체 플로우 최종 검증 — Phase 2 · 4 의 대조를 최종 코드로 다시: `--no-fetch` 재실행 뒤 storage 전체 바이트 같음(`diff -rq`), 임시 폴더로 다시 내보낸 9개(합성 8 · 매니페스트)가 quant 사본과 바이트 같음
- [x] Validation 절에 `/code-review` 와 품질 검증 **실행 결과**를 적는다
- [x] DoD 체크리스트 최종 업데이트 및 체크 완료
- [x] 전체 Phase 체크리스트 최종 업데이트 및 상태 확정
- [x] 🔴 **마지막에 `/commit` 을 실행하고 그 후보를 «이 계획서» 의 `#### Commit Messages` 절에 옮긴다** —
      대화에만 내면 그 절이 빈 채로 남는다. **커밋은 사용자가 한다 — 후보만 낸다**

**Validation**:

> 순서는 `/code-review` → 품질 검증이다. 고칠 것 · 회차 상한 · 수정분 검증은 `/impl-plan` 의 `review.md` 가 정한다.

- [x] `/code-review xhigh` **1회차** (발견 27건 — 저장소 11 + 저장소 밖 서브에이전트 16 — 버그 5 [무거움 4 · 가벼움 1] · 그 외 22 · 조치: 무거움 2 수정(라벨 고정 테스트 · 추적 차이 「하루」), 무거움 2 · 가벼움 1 거름, 그 외 중 이 계획의 치환 오류 5곳 고침 · 용어표 사실 정정 7 반영 · 결정 5 사용자에게 올림 — 진행 로그의 코드 리뷰 1회차 항목)
- [x] `/code-review xhigh` **2회차** (발견 26건 — 저장소 11 + 저장소 밖 서브에이전트 15 — 버그 10 [무거움 2 · 가벼움 8] · 그 외 16 · 조치: 무거움 1 수정(용어표 「원본가」 정의 — 야후 원본가는 분할 반영) · 무거움 1 거름(기준 1), 가벼움 1 수정(파일 이름 · 검사 이름 고정 테스트 — 1회차와 같은 모양) · 3 거름(기준 1 · 2) · 1 받아들임 · 3 사용자에게 올림(전역 규칙 문구), 그 외 중 요청 밖 변경 1 되돌림 · 숫자 1 정정 — 진행 로그의 코드 리뷰 2회차 두 항목. 2회차에 닿는 무거운 버그가 나와 고친 뒤 멈춤 — 3회차는 사용자가 정한다)
- [x] 수정분 검증 (수정 5건 · 발견 7건 — 무거움 0 · 조치: 고치지 않음 — 가벼움 3 · 그 외 4, 거름과 기준 번호는 진행 로그 10:07)
- [x] `poetry run python validate_project.py` (passed=562, failed=0, skipped=0) — Ruff · PyRight 통과, 수정분 검증 뒤 다시 돌린 결과

#### Commit Messages (Final candidates) — 5개 중 1개 선택

> **Done 직전에 `/commit` 을 실행해 이 절을 채운다. 그전에는 비워 둔다** — 추측으로 적은 줄은 그대로 나간다.

1. 수집 / 만든 말을 실무 용어로 변경
2. 수집 / 판 요약 → 매니페스트 · 패스 목록 → 허용 목록 · 새로 붙는 날 → 신규 일자 등 용어 변경
3. 수집 / 매니페스트 · 허용 목록 · 비교 대상으로 식별자와 데이터 파일 이름 변경, 라벨 고정 테스트 추가
4. 수집 / 문서 · 코드 · 테스트 · 상태 라벨의 실무 용어 통일과 내보내는 매니페스트 사본 이름 변경
5. 수집 / 처음 읽는 사람도 뜻을 알 수 있게 조어(판 · 흔들림 · 짝 · 두 출처)를 업계 용어로 정리

## 7) 리스크(Risks)

- **치환 오탐** — 부사 「새로」 · 「QQQ 계열」 · 「머리말」 · 다른 뜻의 `pair` · 「판정」을 같이 바꾸는 것 → 일괄 치환 금지, 파일마다 문맥으로 가르고, 잔여 검사 · diff 검토로 잡는다
- **원문 훼손** — 사용자 발언 · 옛 결정 이름 · 다른 문서 인용을 고치는 것 → 「바꾸지 않는 것」을 잔여 검사의 기대값으로 고정
- **이름만 맞고 동작이 바뀌는 것** — 테스트 기대값은 그대로 두고, 실데이터 `--no-fetch` 결과를 바이트로 대조
- **매니페스트의 상태가 「미수집」이 되는 것** — 받지 않은 갱신이라는 사실 그대로다. 지난 받기의 상태는 git 이력에 있다
- **quant 사본이 커밋 전 quant-data 커밋 번호를 적는 것** — 지금 사본도 같은 모양(커밋 안 된 `storage/edition.json` 을 적음)이고, 다음 내보내기가 맞춘다
- **`docs/DEFERRED_FINDINGS.md` 의 줄 번호가 낡는 것** — Phase 3 에서 새 코드 기준으로 고친다

## 8) 메모(Notes)

- 쓰는 말의 정본은 `~/.claude/docs/실무_용어.md` 다. 이 계획에서 새로 정해야 하는 말이 나오면 멈추고 후보와 근거를 들고 묻는다(전역 「실무 용어를 쓴다」)
- quant 의 커밋 후보는 quant 변경이 생긴 뒤 같은 방식으로 따로 낸다

### 진행 로그 (KST)

- 2026-11-12 08:55: 계획서 작성 (Draft)
- 2026-11-12 09:02: 자체 검증 — 1회차에 넷을 고침: ① 「원시 시가 · 원시 시세 · 원시 값」 누락 → 규칙 · 잔여 검사에 「원시」 전체 ② 「판」 집계가 한글 파일명(연구 문서 둘)을 빠뜨린 399회 · 29개 → 319회 · 30개(전역 `CLAUDE.md` Why 줄도 고침) ③ 「바꾸지 않는 것」 5 를 결정 14 의 두 자리로 좁힘(6.1 등은 배당만 가리켜 바꿈) · 잔여 검사를 일치 단위(`-o`)로, 기대 6건 ④ 코드 라벨 문자열(`"새로"` · `"받지 않음"`)을 잔여 검사에 넣음. 2 · 3 · 4회차(일관성 · 실패 복구 · 다른 로직 영향 — 사용처는 고정 경로로만 읽음 · 테스트는 실제 storage 를 읽지 않음) 개선 없음 → 멈춤
- 2026-11-12 09:06: 사용자 승인(「진행」) — 검사 이름 「교차 검증 일치 · 교차 검증 차이」, 「진단 줄」, `--no-fetch` 로 매니페스트 다시 쓰기, `pair` → `benchmark` 그대로 진행. 「진단 줄」은 전역 용어표에 적음
- 2026-11-12 10:52: Done 뒤 사용자 결정(「추천대로」) — `README.md` 「실물 ETF 추적 오차」 → 「실물 ETF 추적 대조」(그 표는 누적 차 RMSE 라 업계의 추적 오차 — 추적 차이의 표준편차 — 와 다름, 뒤의 「펀드 대조」와 맞춤). 검증 ④ 의 「시나리오」는 이름을 두고 전역 용어표 3절에 「한 가정씩 바꾼 것은 업계 말로 민감도 분석」을 적음. 전역 규칙 · 용어표의 후속 다듬기는 저장소 밖이라 이 계획서의 범위 밖 — 리뷰 1회 · 수정분 검증 1회 뒤 문구 6곳을 고치고 멈춤
- 2026-11-12 10:07: 2회차 수정분 검증(맥락 없는 서브에이전트 — 수정 5건의 diff 와 겨냥한 지적만 줌. 사용 한도로 한 번 멈췄다 이어서 끝냄) — 발견 7, 무거움 0. 변형 시험은 scratchpad 사본에서만, 기준선 562 passed
  - 거름(가벼움): 목록 파일 이름 `LIST_FILE_NAME`(`quant_data_files.txt`)도 글자로 고정되지 않음 — 기준 2(바뀌면 내보내기가 `FileNotFoundError` 로 멈춤) / 전역 Why 줄 「판 318회」에 「팔다」 2건(「판 것만」 · 「판 두 번」)이 섞여 만든 말로서는 316회 — 기준 3(문서의 숫자, Done 보고에 올림) / 계획서 3장의 `tests/test_export.py` 줄 수(19 → 판다를 빼면 18) — 기준 3(계획서)
  - 거름(그 외): `test_file_names_are_fixed` 가 클래스 `TestSharedValues`(「따로 둔 값이 같다」)와 주제가 다름 · 검사 이름 테스트가 순서까지 고정 · 용어표 「unadjusted 는 분할도 미조정」은 저장소에 근거 없는 일반 지식 · 「raw」와 「unadjusted」가 업계에서 대개 같은 말이라 충돌이 자리만 옮김
  - 확인된 것: 수정 4 의 야후 Close(분할만 반영) · KRX 원본가(분할 미반영) 는 저장소 서술 · 측정과 맞음(`revision.py:106-107` · `시세_받기_판정.md:114 · :139`), 수정 5 의 318회 · 30개 파일은 HEAD 에서 재현
- 2026-11-12 10:06: 시각 정정 — 이 로그의 09:40 · 09:55 · 10:05 · 10:30 · 10:45 는 시계를 확인하지 않고 적은 시각이었다(뒤의 둘은 그때 아직 오지 않은 시각). 시계로 확인한 시각(09:06 · 09:39 · 10:06)을 경계로 고쳐 적음 — 09:39 로 적은 항목은 09:06 ~ 09:39 사이(사용자 결정은 09:39), 10:06 으로 적은 항목은 09:39 ~ 10:06 사이에 일어났다
- 2026-11-12 10:06: 코드 리뷰 2회차 — 저장소 밖(전역 `CLAUDE.md` · 용어표) 15
  - 고침(버그 무거움): 용어표 「원본가」 정의가 「배당 · 분할을 반영하지 않은 가격」 — 야후 원본가는 분할이 과거에 반영돼 있음(`revision.py:106` · `시세_받기_판정.md:114`), 분할도 미반영은 KRX 뿐 → 「배당을 반영하지 않은 가격 — 분할은 출처마다 다르다」
  - 고침(그 외 — 숫자): 전역 Why 줄 「판 319회」에 「판다스」 1건이 섞임 → 318회(HEAD, 판다 제외 정규식) · 계획서 3장도 · 계획서의 「나머지 18개 파일」 → 19
  - 사용자에게 올림(버그 가벼움 — 전역 규칙의 정책 문구라 사용자 결정): 「새로 쓰는 글에 적용」과 「기존 관용 · 일관성 우선」의 앞뒤 · 「실무 용어로 확인되면 묻지 않음」의 확인 기준 · 「바꿀 때」에 「라벨 · 메시지 · 절 제목을 가리키는 「」는 함께 바꾼다」 빠짐
  - 사용자에게 올림(그 외 — 용어표 다듬기): 「교차 검증」 피할 말의 뜻 한정 · 「바꿀 때」 뜻마다 행선지(비교 대상 · 몫의 부분 · 계열 단독) · 「그대로 쓰는 말」 절 · 낯선 말 조사의 발동 범위 · 시나리오 근거(한 가정씩 바꾼 경우) · 「이상치 검사」 근거가 추적 차이에만 맞음 · 허용 오차 뜻 넓히기 · 미수집 뜻 · `--untracked` 표현과 git 밖(`--no-index`) · 회사 도메인 예외 진입점
- 2026-11-12 10:06: 코드 리뷰 2회차(상한) — 저장소(`/code-review xhigh`) 11
  - 고침: ① 사용처 · 사람이 이름으로 찾는 값이 글자로 고정되지 않음 — 1회차에 고친 「라벨이 상수끼리만 비교됨」과 같은 모양을 그때 diff 전체에서 찾지 못한 것(파일 이름 셋 · 허용 목록 검사 이름 넷) → `test_file_names_are_fixed`(test_export) · `test_check_names_are_fixed`(test_new_days) 추가, 변형 2개(내보낼 매니페스트 이름 오타 · 검사 이름 「교차확인 일치」)에서 각각 1 failed 확인 뒤 사본으로 되돌려 바이트 대조 ② 합성 문서 「종가에 판 두 번」(「팔다」)을 「매도한」으로 바꾼 것은 요청 밖 변경 → 되돌리고 「바꾸지 않는 것」 3 에 더해 기대값 7건으로
  - 거름: 비교 대상의 종류(시세 · 일별 시계열)를 표 검사가 보지 않아, 잘못 적은 표가 받은 뒤 `parse_price_file_name` ValueError 로 멈춤 — 기준 2(잘못된 입력에서 쓰기 전에 멈춤, 이 계획 전부터 있던 검사) / 옛 커밋에서 되살리기 · `UnicodeDecodeError` — 1회차와 같은 지적, 같은 기준(2 · 1) / 다른 사용처 폴더의 옛 `quant_data_edition.json` 이 남음 — 기준 1(사용처는 quant 하나이고 삭제가 그쪽 커밋에 들어감)
  - 받아들임(계획서가 적음): `--no-fetch` 로 받는 자료 31개의 상태가 「미수집」 — 3장 데이터/결과 영향 · 7장 리스크, 사용자 승인 09:06
  - 고치지 않음(그 외): 새 파일이 untracked 라 `git commit -a` 로는 빠짐(커밋은 사용자 — Done 보고에 알림) · `test_scenario_column_label` 은 상수만 봄(표의 열 순서는 보지 않음 — docstring 이 넓게 말함) · 합성 문서 6.11 · 6.12 제목 「긴 기간」이 quant 원문 제목 「긴 판」과 달라 제목으로 찾기 어려움 · `DEFERRED_FINDINGS.md` 의 이 계획 전부터 어긋난 줄 번호
- 2026-11-12 09:39: 사용자 결정(리뷰 1회차에서 올린 넷, 모두 추천대로) — ① 「교차 검증」 → 「교차 확인」(검사 이름 「교차 확인 일치 · 교차 확인 차이」, 식별자 `cross_check` 그대로) ② `Dataset.benchmark` → `reference`(비교 대상) — 미국 쪽 `check_tracking_difference` · `_benchmark_prices` 의 「벤치마크」는 그대로 ③ 전역 「실무 용어를 쓴다」에 적용 범위 · 3절 예외 · 실무 용어로 확인되면 묻지 않음을 넣고, 용어표에 「바꿀 때」 절(이 계획서 3장의 문맥 가름을 근거 승격) ④ quant 사본 교체 지금 진행(내보내기 + 옛 사본 삭제). 계획의 전제(말의 대응)가 바뀐 것이라 계획서 3장 표 · 데이터 값 절을 함께 고침
- 2026-11-12 09:39: 코드 리뷰 1회차 — 저장소(`/code-review xhigh`) 11 · 저장소 밖(전역 `CLAUDE.md` · `~/.claude/docs/실무_용어.md` · quant 문서 — 전역 `CLAUDE.md` 는 바꾸기 전 사본이 없어 지금 파일에서 넣은 절을 빼 되살린 원본과 diff) 16
  - 고침(버그 무거움): ① 라벨 고정 테스트 없음 — 상태 값 · 「배당 반영」 매핑 · `assumptions.csv` 헤더를 바꿔도 557 통과 → `test_status_labels_are_fixed` · `test_dividend_adjusted_file_is_marked_in_manifest` · `test_scenario_column_label` 추가, 변형 3개(「노이즈 뿐」 · 매핑을 노이즈뿐으로 · 헤더 「판」)에서 각각 1 failed 확인 뒤 사본으로 되돌려 바이트 대조 ② 용어표 「추적 차이」 정의에 「하루」 누락(레버리지 구간 수익률로 재면 복리 효과까지 셈)
  - 고침(이 계획의 치환 오류 — 계획 규칙의 뜻과 다른 자리에 바꿈): `DEFERRED_FINDINGS.md` 「GC=F 의 다른 짝」(금 사슬의 이웃 고리 → 「금 사슬에서 GC=F 와 이어지는」), 합성 문서 「흔들림」 5곳(52 · 183 · 479 · 569 · 578 — SPY ↔ VFINX 하루 수익률 차이였음 → 「하루 수익률 차이」. 6.13 제목 · 581 은 다시 받기 노이즈라 그대로), 검사식이 놓친 변형(`revision.py` 「기록으로 설명된 변화」 2 · `test_revision.py` 「설명된 변화」 3 · `test_new_days.py` 「근거 없는 패스가」 → 잔여 검사식에 `설명된 변화|패스[가는를]` 추가), `constants.py` 의 식별자를 되풀이한 주석 「# 매니페스트」 지움
  - 반영(그 외 — 용어표 사실 정정): 시나리오 근거(민감도 분석 → 시나리오 분석) · Iceberg manifest list ↔ manifest file · 대용가격 정의 · 대용변수와 합성 시세는 같은 뜻도 있음(3절 머리 「다른 뜻으로도」) · initial ingestion · 「원본」의 원금 오독 · 허용 목록 · 진단 출력 뜻을 저장소 전용에서 일반으로 · 「새로 짓는 식별자」
  - 거름: 매니페스트 이전 이름(`storage/edition.json`)의 옛 커밋에서 되살리면 새 코드가 못 읽고 멈춤 — 버그 가벼움 · 기준 2(막는 쪽으로만: 받기 전에 안내와 함께 멈추고 아무것도 쓰지 않음) / `read_manifest` · export 의 `UnicodeDecodeError` 미처리 — 무거움 모양 · 기준 1(닿지 않음: 이 계획이 옮기기만 한 기존 코드이고 잘린 파일이 있어야 함 — 매니페스트는 갱신이 끝에 한 번 씀) / 기준일이 null 인 매니페스트의 `TypeError` — 기준 1(코드가 늘 날짜 문자열을 쓰므로 손으로 고쳐야 생김)
  - 고치지 않음(그 외): `DEFERRED_FINDINGS.md` 의 이 계획 전부터 어긋난 줄 번호(`catalog.py:94 · :96` · `products.py:71` — diff 밖 기존), quant 사본 교체(Phase 4 실행 승인 대기), 용어표의 「(상태)」 행 · 「○○ 용」 근거 빈칸 · 회사 도메인 예외의 진입점 중복
  - 사용자에게 올림: 「교차 검증」이 국내 퀀트 · ML 에서 cross-validation(quant 의 CSCV 「조합적 대칭 교차검증」)이라 이 말 자체가 충돌 · BTCUSD 의 `benchmark="BTC_PriceUSD"`(Coin Metrics 는 벤치마크가 아니라 교차 확인 상대) · 전역 규칙의 적용 범위(새 글만 · 기존 문서는 요청 때) · 3절 예외 · 이미 실무 용어인 낯선 말은 묻지 않음 · 계획서 3장의 「문맥으로 가르는 말」을 용어표로 근거 승격
- 2026-11-12 09:39: 남긴 `pair`(최종 코드 집계) — `products.py`(`PairSummary` 4 · `pair_summary_record` 2 · `summarize_pair` 2 · `_ProxyPair` 8 · `pairs` 6 · `gold_pairs` 5 · `_gold_pairs` 2 · `pair` 10), `revision.py`(`pair` 4), `synthetic/proxy_comparison.py`(`PairSummary` 4 · `pair` 4 · `summarize_pair` 1 · `pair_summary_record` 1), `tests/test_proxy_comparison.py`(`summarize_pair` 25 등). 벤치마크 파일 6개(catalog · new_days · update 와 그 테스트)에는 0
- 2026-11-12 09:39: 진행 중 발견 — ① 「」 안 낱말을 바꾸면 「」 뒤 조사가 남음(「배당 반영」로) ② 괄호 뒤 조사(`매니페스트({MANIFEST_PATH})이`) — 둘 다 검색식으로 전수 찾아 고침(코드 2 · 문서 3 · 테스트 1) ③ 줄바꿈으로 끊긴 말 2곳(「판 / 요약」 · 「두 출처 / 대조」) ④ 이름을 바꾸며 생긴 import 정렬 5건 → `ruff check --select I --fix`
- 2026-11-12 09:06: `pair` 의 다른 뜻 — `revision.py` 의 `pair`(기존 · 응답 두 표를 합친 것), `products.py` · `synthetic/proxy_comparison.py` 의 `summarize_pair` · `PairSummary` · `_ProxyPair` · `pair_summary_record` · `gold_pairs` · `pairs`(대용 ↔ 실물 쌍), `synthetic/gold_proxy.py` 의 `_PRICE_PAIRS` 는 그대로 둔다. 한글 「짝」은 이 파일들에 없다 — 모두 벤치마크 뜻

---
