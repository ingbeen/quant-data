# Implementation Plan: VIX · 공포탐욕지수를 고정으로 — 공포탐욕지수 받기 코드 삭제

> 작성/운영 규칙(SoT): `/impl-plan` 스킬(`~/.claude/skills/impl-plan/SKILL.md`)을 반드시 참고하세요.  
> (이 템플릿을 수정하거나 새로운 양식의 계획서를 만들 때도 해당 스킬을 포인터로 두고 준수합니다.)

**상태**: ✅ Done

---

> 상태는 🟡 Draft / 🔄 In Progress / ✅ Done. Done 조건과 기록 규칙은 `/impl-plan` 「3) 스킵 및 완료 규칙」이며 `~/.claude/hooks/plan_lint.py` 가 저장 때 검사한다.

---

**작성일**: 2026-11-17 16:49
**마지막 업데이트**: 2026-11-17 17:39
**관련 범위**: catalog · update(받기 묶음) · scripts/update · sources · tests · docs/research · docs/DEFERRED_FINDINGS
**관련 문서**: `CLAUDE.md` · `docs/research/시세_받기_판정.md` · `docs/DEFERRED_FINDINGS.md` · `docs/COMMANDS.md`

---

## 1) 목표(Goal)

- [x] 목표 1: `^VIX` · `FEAR_GREED` 의 갱신 방식을 **고정**으로 바꾼다 — 갱신이 두 자료를 받지도 판정하지도 않는다. 저장 파일 둘과 매니페스트 항목은 남긴다
- [x] 목표 2: **공포탐욕지수 받기 코드를 지운다** — `sources/fear_greed.py` · `Fetchers.fear_greed` · `_fetch_and_judge` 의 공포탐욕지수 분기 · `_FETCHABLE_KINDS` 의 이름 · `scripts/update.py` 연결과 그 테스트. 저장 파일을 읽는 데 쓰는 것(`Kind.FEAR_GREED` · `FEAR_GREED_DATA_PATH` · `_form_of` 의 이름)은 남긴다
- [x] 목표 3: 결정 문서에 Q39 를 더하고 죽은 경로 · 낡은 서술을 고친다. 미룬 지적 ①(공포탐욕지수 끝날) · ③(VIX 뉴욕 18:00)을 「덧붙이기로 풀기 전에 볼 것」으로 문서에 옮기고 대기열에서 지운다

## 2) 비목표(Non-Goals)

- **storage 를 쓰지 않는다** — 데이터 파일 · 매니페스트 바이트 그대로. 매니페스트 두 항목의 상태(지금 「신규」)는 다음 갱신이 「고정」으로 쓴다. `--no-fetch` 로 지금 바꾸지 않는다 — 그 실행은 고정이 아닌 자료의 상태를 모두 「미수집」으로 쓴다(`update._idle_status`)
- 갱신 · 내보내기를 돌리지 않는다
- verify-lab · quant 의 파일 — 읽기만 한다. 두 저장소의 받을 파일 목록에 두 파일이 없다(2026-11-17 확인)
- Q37 · Q38 행을 고치지 않는다(사용자 결정 2026-11-17)
- 미룬 지적 ②(계열 검사의 날짜 결측)를 고치지 않는다 — 공포탐욕지수 받기를 가리키는 문장만 고친다
- `_first_fetch_names` 의 「고정 자료 파일이 없는데 받는 함수가 없습니다」 경로의 테스트 — 이번 변경 전부터 없었고 공포탐욕지수만의 일이 아니다. 매니페스트 항목까지 함께 지워야 닿는다
- `docs/plans/PLAN_vix_fear_greed.md` — Done 계획서(그때의 기록)

## 3) 배경/맥락(Context)

### 현재 문제점 / 동기

- verify-lab 이 2026-11-17 하락_단계_매수를 우위 없음으로 조사 등급으로 내리고, 코드 · 산출물 · VIX · 공포탐욕지수 사본을 지웠다(verify-lab `17667cb`, 그 저장소 `docs/조사/하락_단계_매수.md` §14 Q14). 이 저장소는 두 자료를 「verify-lab 용 하락_단계_매수의 신호 — 덧붙이기」로 계속 받는다(`catalog.py:152-154`)
- **두 자료를 읽는 곳이 없다** — 2026-11-17 조사 범위: quant-data 안 `git grep`(가공에서 읽는 곳 0) · verify-lab 받을 파일 목록 · `storage/market/` · 사본 매니페스트 · `.py`(조사로 내린 사유 주석 1줄뿐) · quant 목록과 저장소 전체 grep 0 · 워크스페이스의 나머지 16개 폴더 0. 보지 못한 곳: 다른 PC 의 커밋 안 된 파일 · 워크스페이스 밖
- **받기를 이어 가면 쓰는 곳 없는 자료가 갱신 전체를 멈출 수 있다** — 결합본이 빈 날을 채우거나 지난 값을 바꿈 · 출처가 사라짐(받기 예외) · 야후가 VIX 휴장일 봉을 지움 · VIX 그날 봉의 뉴욕 18:00 기준(`시세_받기_판정.md` 6.12 · `docs/DEFERRED_FINDINGS.md`). 멈추면 아무 파일도 쓰지 않아 SPY · BTC · 합성도 새로 받지 못한다(Q17). 아직 일어난 적은 없다 — 2026-11-17 결합본(HTTP 200)을 받아 저장 파일과 대조: 겹친 3,965일 중 저장 자릿수로 다른 날 0, 응답에만 있는 날은 저장 끝날 뒤 4일뿐
- `시세_받기_판정.md` 가 지금 없는 verify-lab `docs/검증/하락_단계_매수/설계.md` 를 가리킨다(94 · 271행). 281행 · `DEFERRED_FINDINGS.md:16` 이 「쓰는 쪽(verify-lab 하락_단계_매수)」을 현재형으로 적었다

### 결정 (사용자 2026-11-17 「추천대로」)

| 항목 | 결정 | 택하지 않은 안 |
|---|---|---|
| 받기 | **고정으로 두고 공포탐욕지수 받기 코드만 지운다**. 데이터 · 매니페스트 항목은 남긴다 — 2011-01-03 ~ 2021-01-29 복원본은 결합본 말고 얻을 곳이 없다(6.12) | 그대로 받기(멈춤 위험) · 고정이되 코드 유지(평소 갱신에서 돌지 않는 src 97줄 — Q35 처럼 남기는 안) · 데이터까지 삭제 |
| 결정 기록 | Q37 · Q38 은 그대로, 3.3 에 **Q39** | Q37 · Q38 행 안에 덧붙임(결정 내용이 바뀐 행에 쓰는 관행이라 맞지 않음) · 새로 씀(근거 소실) |
| 미룬 지적 ① · ③ | 「덧붙이기로 풀기 전에 볼 것」으로 8장에 옮기고 대기열에서 지운다 — 고정 펀드 · 금 선물의 18:00 을 6.11 · 8장 「고정을 풀기 전에 잰다」로 둔 선례 | 대기열에 둠(받지 않아 닿지 않는 지적이 판단 대기로 남음) |
| 진행 | 문서와 코드를 한 계획서로 — 3.3 · 2장 · catalog 머리말이 같은 사실을 말한다 | 문서 먼저 따로 |

### 「고정」 · 받는 함수 없음이 코드에서 하는 일 (2026-11-17 확인)

- 고정은 받지 않고 판정하지 않는다 — `update.py:232`
- 매니페스트 대조는 고정에도 건다 — `update.py:307-323`. 파일을 `_form_of` 의 모양으로 읽으므로(`update.py:319` → `_read_for_period`) 공포탐욕지수는 계열로 읽혀 `validate_series`(중복 날짜 · 결측)를 지난다 — **`_form_of` 의 이름은 남긴다**. 이 동작을 지키는 테스트는 지금 `TestFearGreed.test_existing_file_is_checked_as_series` 하나다(`_sync_manifest` 는 검사 없이 매니페스트를 적고, 「중복 날짜」는 갱신의 매니페스트 대조가 낸다)
- 받는 함수가 없는 종류를 고정이 아닌 방식으로 두면 받기 전에 멈춘다 — `update.py:264-265`. 받기 코드를 되살리지 않고 덧붙이기로 되돌리는 실수를 막는다
- 받지 않은 고정 자료의 매니페스트 항목은 지금 파일로 기간을 재고 상태 「고정」 — `update.py:660-664 · 679-681`
- 파일과 매니페스트 항목이 둘 다 없으면 「받는 함수가 없습니다 — git 이력에서 되살리세요」로 멈춘다 — `update.py:356-358`(Perth 금값 · 호주달러 환율 · 운용비율과 같은 처리)
- `ff3306d` 는 공유 함수 본문을 바꾸지 않았다 — 공포탐욕지수가 쓰는 계열 판정 함수는 KRX 지수 · NAV · Coin Metrics 가 쓰던 것이다. 계열 덧붙이기 판정은 `test_series.py` 와 `test_update.py` 의 `TestCoin` 이 따로 시험한다
- VIX 전용 코드는 표 한 줄뿐이다 — 받기 · 판정은 야후 지수 공용 경로
- 매니페스트 항목 순서는 표 순서다(`update.py:652` → `manifest.write_manifest` 「받은 순서」) — 표에서 줄을 옮기면 다음 갱신의 매니페스트 diff 에 순서 변경이 섞인다

### 기대값 — 요구사항에서 (구현 전에 나열)

- 정상: 표의 `^VIX` · `FEAR_GREED` 방식이 고정이고, 종류 · 파일과 다른 자료의 방식은 그대로다
- 정상: 받는 함수 없는 고정 공포탐욕지수 — 갱신이 멈추지 않고, 받기 호출 0, 파일 바이트 그대로, 매니페스트 항목의 첫날 · 끝날 · 행 수 그대로 · 상태 「고정」. 값 0 인 날을 넣는다(경계 — 결합본에 실재, 2014-10-13)
- 실패: 고정 공포탐욕지수 파일에 중복 날짜 → 받기 전에 `ValueError`(중복 날짜), 받기 호출 0
- 실패: 공포탐욕지수를 덧붙이기로 둔 표 → 받기 전에 `ValueError`(받는 함수), 받기 호출 0
- 불변조건: 실제 storage 에서 갱신의 받기 전 검사(표 검사 · 매니페스트 대조 · 최초 수집 판정)가 예외 없이 지나고 최초 수집 대상이 없다 — 읽기만 하는 확인
- 불변조건: storage 바이트 그대로(`git status --short storage/` 빔). 사용처 목록에 두 파일이 없어 내보내기 결과도 그대로
- 불변조건: src · scripts 에서 `fear_greed` · `FEAR_GREED` 가 남는 곳 = `Kind.FEAR_GREED` · `FEAR_GREED_DATA_PATH`(정의 · catalog import) · catalog 표 한 줄 · `_form_of`

### 영향받는 규칙(반드시 읽고 전체 숙지)

> 아래 문서에 기재된 규칙을 **모두 숙지**하고 준수합니다.

- `.claude/plan-config.json` — 이 저장소의 검증 명령·자동 포맷·근거 승격 목적지 (**값의 SoT**)
- 루트 `CLAUDE.md` — 판정 원칙 · 결정 · 근거가 있는 곳 · 계획서 규약
- `docs/research/시세_받기_판정.md` — 2장 · 3장(Q20 · Q35 · Q37 · Q38) · 6.11 · 6.12 · 8장
- `docs/DEFERRED_FINDINGS.md` 머리말 · `/impl-plan` 의 `review.md` 「미룬 지적 옮기기」
- `docs/COMMANDS.md` — 갱신 · 내보내기
- 전역 `~/.claude/rules/python.md` · `~/.claude/rules/python-tests.md`, 이웃 테스트(`test_update.py` 의 `TestFixedFiles` · `TestCatalogCheck` · `TestCoin`)의 관용

## 4) 완료 조건(Definition of Done)

> Done은 "서술"이 아니라 "체크리스트 상태"로만 판단합니다. (정의/예외는 `/impl-plan` 스킬)

- [x] 표의 `^VIX` · `FEAR_GREED` 가 고정이고 갱신이 두 자료를 받지 않는다(테스트)
- [x] 공포탐욕지수 받기 코드와 그 테스트가 없고, src · scripts 에 남는 이름이 기대값의 자리뿐이다(grep)
- [x] 받는 함수 없는 고정 공포탐욕지수의 정상 · 손상 파일 · 덧붙이기 되돌림이 테스트로 고정됐다
- [x] 실제 storage 에서 받기 전 검사 통과 · 최초 수집 대상 없음(읽기만) · `git status --short storage/` 빔
- [x] 코드 리뷰 실행 및 결과 기록 (마지막 Phase 의 Validation 에 적는다)
- [x] 품질 검증 통과 (마지막 Phase 의 Validation 에 passed/failed/skipped 수를 적는다)
- [x] 자동 포맷 적용 완료 (마지막 Phase에서 실행)
- [x] 필요한 문서 업데이트 — `docs/research/시세_받기_판정.md`(2장 줄 · 3.3 · Q39 · 6.12 · 8장) · `docs/DEFERRED_FINDINGS.md` / `docs/COMMANDS.md` 변경 없음 / 루트 `CLAUDE.md` 변경 없음
- [x] 근거 승격 완료 — 이 계획서를 지금 삭제해도 잃을 정보가 없다 (Q39 · 8장 행이 결정 · 근거 · 남긴 것 · 되살리는 길(커밋 `ff3306d`)을 담는다)
- [x] 미룬 지적 — 대기열 ① · ③ 을 8장으로 옮기고 지웠다 · ② 의 공포탐욕지수 문장을 고쳤다 · 이 계획서의 리뷰 지적: 해당 없음(8건 모두 「그 외」 — 거르는 기준 3, 진행 로그 표)
- [x] plan 체크박스 최신화(Phase/DoD/Validation 모두 반영)

## 5) 변경 범위(Scope)

### 변경 대상 파일(예상)

- `src/quant_data/catalog.py` — 머리말에서 「verify-lab 신호용 VIX · 공포탐욕지수」 구절을 뺀다(`ff3306d` 전 문장으로). `_index` 에 `method` 인자(기본 덧붙이기 — 다른 지수 4곳 호출 그대로). `^VIX` · `FEAR_GREED` 를 고정으로, 묶음 주석을 「조사로 내린 … — 고정(Q39)」으로. **줄 자리는 그대로 둔다**(매니페스트 항목 순서)
- `src/quant_data/update.py` — `_FETCHABLE_KINDS` 의 `Kind.FEAR_GREED` · `Fetchers.fear_greed` · `_fetch_and_judge` 의 공포탐욕지수 분기 삭제. `_form_of` 그대로
- `scripts/update.py` — import 와 `fear_greed=` 두 줄 삭제
- `src/quant_data/sources/fear_greed.py` — 삭제
- `tests/test_fear_greed.py` — 삭제
- `tests/test_update.py` — `FakeSources` 의 `_fear_greed` · `fear_greed=` · docstring 의 `"FEAR_GREED"` 삭제. `TestFearGreed`(덧붙이기 4개)를 고정 테스트 2개로 바꾼다. `TestCatalogCheck` 에 공포탐욕지수 덧붙이기 경우 하나
- `tests/test_catalog.py` — 방식 기대값(`^VIX` · `FEAR_GREED` 를 고정으로). `test_fear_greed_decimals` 삭제 — 저장 자릿수는 받아 쓸 때(`update._write`)만 쓰이는데 받지 않는다
- `docs/research/시세_받기_판정.md` — 34행 · 3.3(제목 날짜 · 첫 문단 · Q39) · 271 · 281행 · 8장 행
- `docs/DEFERRED_FINDINGS.md` — ① · ③ 삭제, ② 의 공포탐욕지수 문장 삭제
- `docs/COMMANDS.md`: **변경 없음** — 갱신 · 내보내기 명령과 옵션이 그대로다
- 루트 `CLAUDE.md`: 변경 없음

### 데이터/결과 영향

- storage 바이트 그대로. 다음 갱신부터 두 자료를 받지 않고, 그 갱신이 매니페스트 두 항목의 상태를 「신규」 → 「고정」으로 쓴다 — 그 갱신의 diff 에 보인다
- 사용처(quant · verify-lab) 목록에 두 파일이 없어 내보내기 결과는 바뀌지 않는다

## 6) 단계별 계획(Phases)

### Phase 0 — 결정을 테스트로 먼저 고정(레드)

**작업 내용**:

- [x] `tests/test_catalog.py` `test_method_by_name` — `^VIX` · `FEAR_GREED` 를 고정 기대값으로 옮긴다
- [x] `tests/test_update.py` `TestCatalogCheck.test_bad_catalog_raises` — 공포탐욕지수를 덧붙이기로 둔 줄 → `ValueError`(받는 함수) · 받기 호출 0
- [x] `tests/test_update.py` — `TestFearGreed` 를 고정 테스트로 바꾼다: 정상(위 기대값 — 값 0 포함) · 손상 파일(중복 날짜 — 지금 `test_existing_file_is_checked_as_series` 를 고정 자료 · 받기 대역 없음으로)

**Validation**: `env -u VIRTUAL_ENV poetry run pytest tests/test_catalog.py tests/test_update.py` — `test_method_by_name` 과 공포탐욕지수 덧붙이기 경우가 실패(레드)하고, 고정 테스트 2개는 통과한다(고정 처리는 종류와 무관하게 이미 있다 — 받기 코드를 지운 뒤에도 통과해야 하는 회귀 고정) — 2026-11-17 `2 failed, 101 passed`: `test_method_by_name`(AssertionError) · `test_bad_catalog_raises[fear_greed_not_fixed]`(받기 대역의 `KeyError: 'FEAR_GREED'` — 지금은 받으러 간다) 둘뿐

---

### Phase 1 — 받기 코드 삭제 · 표를 고정으로(그린)

**작업 내용**:

- [x] `catalog.py` — 머리말 · `_index(name, method=Method.APPEND)` · `^VIX` · `FEAR_GREED` 고정 · 묶음 주석
- [x] `update.py` — `_FETCHABLE_KINDS` · `Fetchers` · `_fetch_and_judge` 에서 공포탐욕지수 삭제
- [x] `scripts/update.py` — import · 연결 삭제
- [x] `src/quant_data/sources/fear_greed.py` · `tests/test_fear_greed.py` 삭제, `FakeSources` 정리, `test_fear_greed_decimals` 삭제

**Validation**:

- [x] `env -u VIRTUAL_ENV poetry run pytest tests/test_catalog.py tests/test_update.py tests/test_series.py` 통과 — 2026-11-17 `113 passed`
- [x] `git grep -n -E "fear_greed|FEAR_GREED" -- src scripts` — 기대값의 자리뿐: `catalog.py` import · `Kind.FEAR_GREED` · 표 한 줄, `constants.py` 경로, `update.py` `_form_of` (5줄)
- [x] `env -u VIRTUAL_ENV poetry run python scripts/update.py --help` — 종료 코드 0
- [x] 실제 storage 읽기만 하는 확인 — 표 검사 통과 · 매니페스트 대조 통과 · 최초 수집 대상 `set()` · `^VIX` · `FEAR_GREED` 고정, 고정 아닌 자료(출력 그대로) `['BTCUSD', 'BTC_CapMVRVCur', 'BTC_CapMrktCurUSD', 'BTC_PriceUSD', 'DIA', 'FFR', 'GLD', 'IAU', 'QLD', 'QQQ', 'SPTL', 'SPY', 'SSO', 'TLT', 'TQQQ', 'UPRO', '^DJI', '^GSPC', '^IXIC', '^NDX']`
- [x] `git status --short storage/` 빔

---

### Phase 2 — 문서 정리 및 최종 검증

**작업 내용**

> 🔴 **체크박스와 상태를 먼저 확정하고, `/commit` 은 맨 마지막에** — 이유는 `/impl-plan` 「5) Commit Messages」.

- [x] `docs/research/시세_받기_판정.md`
  - 2장 34행 — 「2026-11-17 그 매매법이 조사로 내려가 둘 다 고정으로 옮겼다(Q39)」
  - 3.3 제목 날짜 · 첫 문단 — verify-lab `docs/조사/하락_단계_매수.md`, 「잰다」 → 쟀다 · 조사로 내림
  - Q39 행 — 결정 · 근거(Q20 · 멈춤 위험) · 남긴 것(파일 · 매니페스트 · 읽는 데 쓰는 이름) · 지운 것과 되살리는 길(`ff3306d` · 8장) · 택하지 않은 안 · 사용자 2026-11-17
  - 6.12 271행 — verify-lab 그 문서 §15.8 을 가리킴
  - 6.12 281행 — 「쓰는 쪽」 → 쓰던 쪽(그 문서 §14 D5 · §15.3), 판정 ① 멈춤은 덧붙이기로 다시 받을 때의 일 · 지금은 고정(Q39)
  - 8장 — 「덧붙이기로 풀기 전에 볼 것 — VIX · 공포탐욕지수」 행(미룬 지적 ① · ③ 의 내용). 출처는 「2026-11-16 코드 리뷰」처럼 날짜로 적고 계획서 이름을 적지 않는다(영구 문서는 임시 문서를 가리키지 않는다)
- [x] `docs/DEFERRED_FINDINGS.md` — ① · ③ 삭제, ② 의 「공포탐욕지수 받기는 자기 자리에서 막았다(…)」 문장 삭제
- [x] `git grep -n "docs/검증/하락_단계_매수"` — `docs/plans/` 밖 0
- [x] `docs/COMMANDS.md` 변경 없음 확인
- [x] 자동 포맷 적용 (`poetry run black .`) — 1개 파일(`tests/test_catalog.py` — 짧아진 덧붙이기 기대값을 한 줄로)
- [x] 변경 기능 및 전체 플로우 최종 검증
- [x] Validation 절에 `/code-review` 와 품질 검증 **실행 결과**를 적는다
- [x] DoD 체크리스트 최종 업데이트 및 체크 완료
- [x] 전체 Phase 체크리스트 최종 업데이트 및 상태 확정
- [x] 🔴 **마지막에 `/commit` 을 실행하고 그 후보를 «이 계획서» 의 `#### Commit Messages` 절에 옮긴다** —
      대화에만 내면 그 절이 빈 채로 남는다. **커밋은 사용자가 한다 — 후보만 낸다**

**Validation**:

> 순서는 `/code-review` → 품질 검증이다. 고칠 것 · 회차 상한 · 수정분 검증은 `/impl-plan` 의 `review.md` 가 정한다.

- [x] `/code-review xhigh` **1회차** (발견 8건 — 버그 0 [무거움 0 · 가벼움 0] · 그 외 8 · 조치: 고칠 것 0 이라 1회차에서 끝냄. 그 외 8건은 고치지 않음 — 계획서 자신의 기록 수치 1건만 도구 출력으로 바로잡음, 진행 로그)
- [x] 수정분 검증 — 해당 없음 (리뷰 뒤 고친 코드 없음)
- [x] `env -u VIRTUAL_ENV poetry run python validate_project.py` (passed=573, failed=0, skipped=0)

#### Commit Messages (Final candidates) — 5개 중 1개 선택

> **Done 직전에 `/commit` 을 실행해 이 절을 채운다. 그전에는 비워 둔다** — 추측으로 적은 줄은 그대로 나간다.

1. 수집 / VIX · 공포탐욕지수 고정 전환
2. 수집 / VIX · 공포탐욕지수 고정 전환과 공포탐욕지수 받기 코드 삭제
3. 수집 / 조사로 내린 하락_단계_매수 신호 자료의 받기 중단과 데이터 유지
4. 수집 / 쓰는 곳 없는 VIX · 공포탐욕지수로 갱신 전체가 멈출 위험 제거
5. 수집 / VIX · 공포탐욕지수 고정(Q39) · 받기 코드 삭제 · 판정 문서 죽은 경로와 미룬 지적 정리

## 7) 리스크(Risks)

- **매니페스트 상태가 다음 갱신까지 「신규」** — 받지 않는데 「신규」로 남는다. 매니페스트 대조는 첫날 · 끝날 · 행 수만 보므로 멈추지 않는다. 다음 갱신 diff 에 상태 두 줄이 보인다 — Done 보고에 알린다
- **되살릴 때 받기 코드는 `ff3306d` 에만 있다** — Q39 · 8장이 그 커밋과 풀기 전에 볼 것을 가리킨다. verify-lab 문서 §19.3 「quant-data 가 그 자료를 더 받지 않게 됐으면 거기에 받기를 되살리는 것이 먼저다」와 맞물린다. 덧붙이기로만 되돌리면 받기 전에 「받는 함수」로 멈춘다(Phase 0 테스트)
- **verify-lab 문서 §15.4 가 이 저장소 「6장」을 가리킨다** — 6.12 는 지우지 않고 두 줄만 고친다
- **`_index` 시그니처 변경** — 호출 5곳 모두 `catalog.py` 안(2026-11-17 grep). 기본값으로 4곳은 그대로
- **`Fetchers` 칸 삭제** — 만드는 곳은 `scripts/update.py` 와 테스트 `FakeSources` 둘(grep). PyRight 가 빠뜨린 곳을 잡는다
- **다른 PC 에 커밋 안 된 사용처가 있으면** — 데이터는 남아 내보내기는 되고 끝날이 2026-11-10 에서 멈춘다

## 8) 메모(Notes)

- 근거 조사(2026-11-17 이 세션) — 결합본 대조는 scratchpad 의 받은 사본과 `storage/series/fear_greed_daily.csv` 를 날짜로 맞춰 6자리로 견줌: 응답 3,969행 · 저장 3,965행 · 겹친 날 3,965 · 다른 날 0 · 응답에만 2026-11-11 · 12 · 13 · 16. 결합본 저장소는 마지막 push 2026-11-17T04:56Z · archived 아님
- `ff3306d` 가 src · scripts 에 더한 것: `sources/fear_greed.py` 89줄 · `update.py` 6줄(+ `_form_of` 1줄 수정) · `scripts/update.py` 2줄 · `catalog.py` · `constants.py`. 테스트: `test_fear_greed.py` 230 · `test_update.py` 98 · `test_catalog.py` 18줄
- 판단 단계의 정정: 「고정으로 바꾼 뒤 `--no-fetch` 한 번이면 매니페스트 두 항목의 상태만 바뀐다」고 했으나, `--no-fetch` 는 고정이 아닌 자료의 상태를 모두 「미수집」으로 쓴다(`update._idle_status`) — 그래서 storage 를 쓰지 않고 읽기만 하는 확인으로 바꿨다
- 고정 자료의 받기 코드를 남기는 관행(Q35 — `download_gold_proxy_sources` 호출 0, KRX 받기는 최초 수집 때만)과 이번 결정은 방향이 반대다 — 사용자가 이번에는 지우는 쪽을 골랐다(2026-11-17)

### 진행 로그 (KST)

- 2026-11-17 16:49: 계획서 작성 — 결정은 같은 세션의 판단(사용자 「추천대로 진행」)
- 2026-11-17 16:55: 자체 검증 — 1회차(지시 논리 · 누락): 8장 출처 표기를 날짜로(영구 문서 → 임시 문서 참조 방지) 보완. 2회차(다른 로직 영향): `Fetchers(` 생성처 2곳 · `_FETCHABLE_KINDS` 사용처 2곳 · 전체 표로 받기를 도는 테스트 없음(`test_update.py` 에 `^VIX` 0건) — 개선 없음. 3회차(멱등성 · 쌓인 데이터): storage 를 쓰지 않음 · 기존 매니페스트 항목(`^VIX` 의 분배 기록 첫날 None 포함)이 고정의 이월과 맞음 · 되살릴 때 기존 파일이 덧붙이기 판정의 기준이 됨 — 개선 없음. 4회차(개선 · 단순화): 테스트 추가 셋이 모두 기대값 목록에서 나왔고 남는 코드를 지킴 — 개선 없음. 연속 3회 개선 없어 멈춤
- 2026-11-17 17:26: 승인(사용자 「추천대로 진행」) · Phase 0 — 레드 `2 failed, 101 passed`(예측한 둘뿐)
- 2026-11-17 17:30: Phase 1 — 대상 테스트 `113 passed` · src · scripts 의 남은 이름 5줄(기대값 자리) · `--help` 종료 0 · 실제 storage 받기 전 검사 통과 · 최초 수집 대상 `set()` · storage 변화 없음
- 2026-11-17 17:33: Phase 2 문서 — `시세_받기_판정.md` 2장 줄 · 3.3 제목 · 첫 문단 · Q39 · 6.12 두 줄 · 8장 행, `DEFERRED_FINDINGS.md` ① · ③ 삭제 · ② 한 문장. 죽은 경로 · 「쓰는 쪽(verify-lab 하락」 0건(plans 밖). black 1개 파일
- 2026-11-17 17:35: `/code-review xhigh` 1회차 — 발견 8 · 버그 0. 리뷰가 storage 사본에 `run_update(CATALOG, fetch=False)` 를 받기 대역(부르면 실패) 으로 돌려: 받기 호출 없음 · 멈추지 않음 · `^VIX` · `FEAR_GREED` 항목 「고정」 · 첫날 · 끝날 · 행 수 그대로, 실제 storage 와 다른 것은 `manifest.json`(미수집 · 고정 상태)뿐 — 사본은 지움. 거른 지적(모두 기준 3 「그 외」 — 고치지 않음 · 미룬 지적으로 옮기지 않음):

  | # | 지적 | 기준 | 근거 |
  |---|---|---|---|
  | 1 | 계획서 Phase 1 기록의 「미국 ETF 12」가 틀림(실제 11 · 합 20) | 3 (계획서 자신) | 손으로 다시 센 값이었음 — **도구 출력 목록으로 바로잡음**(전역 「숫자는 도구 출력을 그대로」) |
  | 2 | `test_method_by_name` docstring 「2장 표와 같다」인데 2장 표에 `^VIX` · 공포탐욕지수 줄이 없음 | 3 (문서) | 2장 표는 2026-11-11 의 모양이고 그 뒤 변화는 아래 줄로 적는 구조(2장 머리말) — `ff3306d` 때부터 같은 상태 |
  | 3 | 받을 수 있는 종류가 `_FETCHABLE_KINDS` · `Fetchers` · `_fetch_and_judge` 세 곳에 손으로 맞춰져 있음 | 3 (설계 정리) | 하나만 되살리면 받기 도중 `RuntimeError`(내부 불변조건 위반)로 크게 멈춤 — 조용히 틀리지 않음 · 이 diff 전부터의 구조 |
  | 4 | 대기열 ① · ③ 을 Done 전에 지움 · 머리말에 「옮김」 처분이 없음 | 3 (문서 · 절차) | 사용자 결정(2026-11-17)으로 옮긴 것이고, 내용은 같은 diff 의 8장 행에 있음 |
  | 5 | `catalog.py` 묶음 주석 「(조사로 내림)」이 변경 이력처럼 읽힘 | 3 (주석) | 이웃 「조사 전용 … — 고정」처럼 지금 상태로 쓰는 편이 전역 주석 규칙에 맞음 — 사용자에게 보고 |
  | 6 | `test_bad_catalog_raises` docstring 「받기를 지운 공포탐욕지수」가 삭제 이력을 적음 | 3 (주석) | 5 와 같음 — 사용자에게 보고 |
  | 7 | `TestFearGreedFixed` 의 `assert sources.calls == []` 는 실패할 수 없음 | 3 (테스트 정리) | 받으러 가면 `_fetch_and_judge` 가 `RuntimeError` 를 올려 테스트가 어차피 실패 — 계약은 「멈추지 않고 끝남 / ValueError」가 지킴 |
  | 8 | `_index` 의 `method` 기본값이 `_fund`(필수 인자)와 모양이 다름 | 3 (스타일) | 계획서가 호출 4곳을 그대로 두려고 고른 모양 — 사용자에게 보고 |
- 2026-11-17 17:37: 품질 검증 `passed=573, failed=0, skipped=0` · Ruff · PyRight 통과 · `git status --short storage/` 빔
- 2026-11-17 17:39: `/commit` 후보 5개를 옮기고 Done

---
