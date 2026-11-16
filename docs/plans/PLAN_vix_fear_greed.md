# Implementation Plan: VIX · 공포탐욕지수 받기 추가 (verify-lab 하락_단계_매수 용)

> 작성/운영 규칙(SoT): `/impl-plan` 스킬(`~/.claude/skills/impl-plan/SKILL.md`)을 반드시 참고하세요.  
> (이 템플릿을 수정하거나 새로운 양식의 계획서를 만들 때도 해당 스킬을 포인터로 두고 준수합니다.)

**상태**: ✅ Done

---

> 상태는 🟡 Draft / 🔄 In Progress / ✅ Done. Done 조건과 기록 규칙은 `/impl-plan` 「3) 스킵 및 완료 규칙」이며 `~/.claude/hooks/plan_lint.py` 가 저장 때 검사한다.

---

**작성일**: 2026-11-16 11:40
**마지막 업데이트**: 2026-11-16 12:50
**관련 범위**: catalog · update(받기 묶음) · sources · tests · docs/research
**관련 문서**: `CLAUDE.md` · `docs/research/시세_받기_판정.md` · `docs/COMMANDS.md`

---

## 1) 목표(Goal)

- [x] 목표 1: 야후 `^VIX` 를 지수(`YAHOO_INDEX` · 덧붙이기)로 받는다 — `storage/prices/^VIX_raw.csv`
- [x] 목표 2: CNN 공포탐욕지수를 공개 결합본(GitHub `whit3rabbit/fear-greed-data` 의 `fear-greed.csv`)에서 계열(`Date,Value` · 덧붙이기)로 받는다 — `storage/series/fear_greed_daily.csv`
- [x] 목표 3: 기존 사본을 바꾸지 않고 두 자료만 더한 갱신을 기준일 2026-11-10 으로 돌려 매니페스트에 올린다 (verify-lab 이 받는 사본은 그대로 — TLT · SPTL 수정주가는 「배당 반영」으로 바뀜, 진행 로그)

## 2) 비목표(Non-Goals)

- 하이일드 스프레드(ICE · Moody's) — 사용자 결정 2026-11-13 으로 진행하지 않는다
- FRED `VIXCLS` — 출처는 야후 `^VIX` 로 정했다(사용자 결정 2026-11-13 Q5)
- 공포탐욕지수를 CNN 엔드포인트에서 직접 받는 것 — 2021-02-01 전 구간이 없고(결합본 README), CNN 페이지는 조사 환경에서 HTTP 451 이었다
- verify-lab 쪽 측정 코드 — verify-lab `docs/plans/PLAN_drawdown_tiers.md`

## 3) 배경/맥락(Context)

### 현재 문제점 / 동기

- verify-lab 에 새 매매법 「하락_단계_매수」(검증 등급)를 세운다 — S&P 500 낙폭 · VIX · 공포탐욕지수가 극단으로 갈수록 그 뒤 성적이 좋았는지를 단계별로 잰다. 결정 경위(Q1 ~ Q12, 2026-11-13 ~ 16)는 verify-lab 계획서 Notes
- 받기는 이 저장소가 맡는다(루트 `CLAUDE.md`). 지금 카탈로그에 VIX 도 공포탐욕지수도 없다
- **VIX 는 하루 급등락이 크다** — FRED `VIXCLS` 1990-01-02 ~ 2026-11-11(값 9,315개)에서 ±50% 를 넘은 날이 10일, 최대 2018-02-05 +115.60%. 이 저장소의 시세 검사는 급등락을 보지 않고(`prices.py` · 결정 Q26), 지수는 벤치마크가 없어 신규 일자 검사도 걸리지 않는다(`new_days.py`) — **그대로 받힌다**
- **공포탐욕지수는 CNN 이 과거 시계열을 내지 않는다.** 공개 결합본이 2011-01-03 ~ 2021-01-29 를 복원본(고정)으로, 2021-02-01 ~ 를 CNN 피드로 매일(평일 23:00 UTC) 다시 만든다. 조사(2026-11-13)에서 내려받아 잰 값:
  - 결합본 3,967행 2011-01-03 ~ 2026-11-12, 2021-02-01 이후 1,453행은 결합본에 든 CNN 피드 파일과 전부 일치(상관 1.0000 · 평균절대차 0.00)
  - README 는 "Data from 2021-02-01 is accurate, however before that date data is not accurate." 라고 적었지만, archive.org 주간 스냅샷(508행 2012-05-25 ~ 2022-04-22)과 대조하면 복원본 427일 상관 0.9247 · 평균절대차 5.01 · 같은 다섯 구간 329/427, CNN 피드 60일 상관 0.9036 · 평균절대차 6.68 · 34/60 — 복원본이 스냅샷과 맞는 정도가 CNN 피드와 비슷하다
  - 값 0.0 인 날이 있다(2014-10-13) — 계열 검사(`series.py`)는 부호를 보지 않아 받힌다
  - 데이터 라이선스는 확인하지 못했다. 출처 표기로 쓴다(사용자 결정 2026-11-13 Q3)

### 갱신 범위 — 기존 사본을 바꾸지 않는 방법

- 지금 매니페스트 기준일은 2026-11-10 이고 verify-lab 사본도 같다. **`--end 2026-11-10` 으로 돌리면** 덧붙이기 자료는 기존 끝날 뒤를 받지 않고(`update._cut`) 새 자료 둘만 그날까지 받힌다
- 다시 받음 자료(SPY · QQQ · DIA 등)는 응답을 판정한다 — 그 사이 배당 기록이 새로 생겼으면 수정주가 과거 행이 바뀔 수 있다. 바뀌면 verify-lab 이 기존 매매법을 다시 돌려야 한다(그쪽 계획서 Phase)

### 영향받는 규칙(반드시 읽고 전체 숙지)

> 아래 문서에 기재된 규칙을 **모두 숙지**하고 준수합니다.

- `.claude/plan-config.json` — 이 저장소의 검증 명령·자동 포맷·근거 승격 목적지 (**값의 SoT**)
- 루트 `CLAUDE.md` — 판정 원칙 · 누가 무엇을 정하는가 · 계획서 규약
- `docs/research/시세_받기_판정.md` — 2장 자료별 갱신 방식 · 3장 결정 · 5장 판정 규칙
- `docs/COMMANDS.md` — 갱신 · 내보내기
- 테스트를 추가/수정하므로 `tests/conftest.py` 와 이웃 테스트(`test_coinmetrics.py` · `test_update.py` · `test_catalog.py`)의 관용, 전역 `~/.claude/rules/python-tests.md`

## 4) 완료 조건(Definition of Done)

> Done은 "서술"이 아니라 "체크리스트 상태"로만 판단합니다. (정의/예외는 `/impl-plan` 스킬)

- [x] 카탈로그에 `^VIX`(지수 · 덧붙이기)와 `FEAR_GREED`(새 종류 · 덧붙이기)가 있고 갱신이 둘을 받는다
- [x] 공포탐욕지수 받기 함수가 0 ~ 100 밖의 값 · 중복 날짜 · 결측에서 멈춘다(테스트)
- [x] 회귀/신규 테스트 추가 — 받기 함수(네트워크 없이 픽스처) · 카탈로그 · 갱신 분기
- [x] 갱신 `--end 2026-11-10` 실행 — 새 파일 둘과 매니페스트 외의 데이터 파일이 바뀌지 않았음을 `git status --short storage/` 로 확인(바뀌었으면 그 목록을 진행 로그와 verify-lab 계획서에 넘긴다)
- [x] 코드 리뷰 실행 및 결과 기록 (마지막 Phase 의 Validation 에 적는다)
- [x] 품질 검증 통과 (마지막 Phase 의 Validation 에 passed/failed/skipped 수를 적는다)
- [x] 자동 포맷 적용 완료 (마지막 Phase에서 실행)
- [x] 필요한 문서 업데이트 — `docs/research/시세_받기_판정.md` 2장 표 · 3장 결정(Q37 · Q38) · 6장 측정(공포탐욕지수 출처 대조) / `docs/COMMANDS.md` 변경 없음 / 루트 `CLAUDE.md` 변경 없음
- [x] 근거 승격 완료 — 이 계획서를 지금 삭제해도 잃을 정보가 없다
- [x] 미룬 지적 옮김 — 3건을 `docs/DEFERRED_FINDINGS.md` 로(공포탐욕지수 끝날 준비 검사 · 계열 검사의 날짜 결측 · VIX 의 뉴욕 18:00 기준 미측정). 거른 지적은 진행 로그 표
- [x] plan 체크박스 최신화(Phase/DoD/Validation 모두 반영)

## 5) 변경 범위(Scope)

### 변경 대상 파일(예상)

- `src/quant_data/catalog.py` — `Kind.FEAR_GREED` 추가, `CATALOG` 에 `_index("^VIX")` · 공포탐욕지수 한 줄(verify-lab 용 묶음 주석 아래)
- `src/quant_data/sources/fear_greed.py` (새 파일) — 결합본 CSV 를 받아 `Date,Value` 로 바꾸고 범위를 검사. 이웃 `coinmetrics.py` 처럼 `urllib`
- `src/quant_data/update.py` — `Fetchers` 에 `fear_greed` 칸, 계열 받기 분기(`KRX_INDEX · KRX_NAV · COINMETRICS` 묶음)와 `_form_of` 의 계열 묶음에 `FEAR_GREED`, 실제 받기 묶음을 만드는 자리
- `src/quant_data/constants.py` — 저장 경로 상수가 필요하면(이웃 `AUD_USD_DATA_PATH` 관용)
- `tests/test_fear_greed.py` (새 파일) · `tests/test_catalog.py` · `tests/test_update.py`(가짜 받기 묶음에 칸 추가)
- `storage/prices/^VIX_raw.csv` · `storage/series/fear_greed_daily.csv` (갱신이 만든다) · `storage/manifest.json`
- `docs/research/시세_받기_판정.md`
- `docs/COMMANDS.md`: **변경 없음** — 갱신 · 내보내기 명령이 그대로다

### 데이터/결과 영향

- 새 파일 둘이 매니페스트에 오른다. 기존 파일은 `--end 2026-11-10` 으로 바뀌지 않는 것이 목표이고, 바뀌면 진행 로그에 남긴다
- 공포탐욕지수 저장 자릿수는 6 — `Dataset.decimals` 기본값(`ROUND_INPUT_PRICE`)이고 결합본의 값(정수 또는 소수 13자리)을 6자리로 저장한다

## 6) 단계별 계획(Phases)

### Phase 0 — 받기 함수의 계약을 테스트로 먼저 고정(레드)

**작업 내용**:

- [x] `tests/test_fear_greed.py` — 결합본 모양의 작은 CSV 픽스처(헤더 `Date,Fear Greed,Rating`)로: `Date,Value` 두 열 · 오름차순 · 값 그대로(Rating 은 버림) / 0 ~ 100 밖이면 `ValueError` / 중복 날짜 · 결측이면 `ValueError` / 헤더가 다르면 `ValueError`
- [x] `tests/test_catalog.py` — `^VIX` 가 지수 · 덧붙이기 · `^VIX_raw.csv`, 공포탐욕지수가 `FEAR_GREED` · 덧붙이기 · `fear_greed_daily.csv`

**Validation**: 새 테스트가 레드인 것을 확인(모듈 · 종류 없음) — 2026-11-16 `ModuleNotFoundError: quant_data.sources.fear_greed` 로 수집 단계 실패 확인

---

### Phase 1 — 받기 · 카탈로그 · 갱신 분기(그린)

**작업 내용**:

- [x] `sources/fear_greed.py` — 결합본 URL 하나를 상수로, 받기 · 변환 · 검사
- [x] `catalog.py` — 종류 · 두 줄 · 모듈 docstring 의 덧붙이기 자료 문장
- [x] `update.py` — `Fetchers` 칸 · 계열 분기 · `_form_of` · 실제 받기 묶음
- [x] `tests/test_update.py` — 가짜 받기 묶음에 `fear_greed` 를 더하고, 계열 분기가 새 종류를 계열로 저장하는지

**Validation**: `poetry run pytest tests/test_fear_greed.py tests/test_catalog.py tests/test_update.py` 통과 — 2026-11-16 113 passed

---

### Phase 2 — 실제 갱신(기준일 2026-11-10)

**작업 내용**:

- [x] `poetry run python scripts/update.py --end 2026-11-10` — 멈추면 진단을 읽어 원인과 추천을 보고하고 멈춘다(제외 · 받아들이기는 사람만)
- [x] `git status --short storage/` — 바뀐 파일 목록이 새 파일 둘 + `manifest.json` 뿐인지. 그 밖이 바뀌었으면 목록을 진행 로그에 적는다
- [x] 받은 두 파일의 첫날 · 끝날 · 행 수를 매니페스트에서 옮겨 진행 로그에 적는다(공포탐욕지수 2011-01-03 시작 · VIX 1990-01-02 시작이 기대값)

**Validation**: 갱신 종료 코드 0 · 위 목록 확인 — 2026-11-16 종료 코드 0, 목록은 진행 로그

---

### 마지막 Phase — 문서 정리 및 최종 검증

**작업 내용**

> 🔴 **체크박스와 상태를 먼저 확정하고, `/commit` 은 맨 마지막에** — 이유는 `/impl-plan` 「5) Commit Messages」.

- [x] `docs/research/시세_받기_판정.md` — 2장 표의 덧붙이기 칸에 VIX · 공포탐욕지수(verify-lab 하락_단계_매수), 3장 결정 Q37(VIX 를 야후 지수로 — FRED 는 CBOE 저작권 표기 · 야후는 기존 지수와 같은 경로) · Q38(공포탐욕지수를 공개 결합본에서 · 덧붙이기 · 6자리 · 범위 0 ~ 100 · 라이선스 미확인과 출처 표기), 6장 측정에 결합본 대조 수치(위 Context)
- [x] `docs/COMMANDS.md` 변경 없음 확인
- [x] 자동 포맷 적용 (`poetry run black .`)
- [x] 변경 기능 및 전체 플로우 최종 검증
- [x] Validation 절에 `/code-review` 와 품질 검증 **실행 결과**를 적는다
- [x] DoD 체크리스트 최종 업데이트 및 체크 완료
- [x] 전체 Phase 체크리스트 최종 업데이트 및 상태 확정
- [x] 🔴 **마지막에 `/commit` 을 실행하고 그 후보를 «이 계획서» 의 `#### Commit Messages` 절에 옮긴다** —
      대화에만 내면 그 절이 빈 채로 남는다. **커밋은 사용자가 한다 — 후보만 낸다**

**Validation**:

> 순서는 `/code-review` → 품질 검증이다. 고칠 것 · 회차 상한 · 수정분 검증은 `/impl-plan` 의 `review.md` 가 정한다.

- [x] `/code-review xhigh` **1회차** (발견 15건 — 버그 8 [무거움 2 · 가벼움 6] · 그 외 7 · 조치: 무거움 2 수정(칸 수가 다른 행 · 빈/다른 형식 날짜) · 가벼움 2 문서화(공포탐욕지수 빈 23일 · VIX 휴장일 봉 2일 — 6.12, 쓰는 쪽 처리는 verify-lab 계획서) · 가벼움 1 미룸(출처 정지 때 끝날 검사 없음) · 가벼움 2 거름(기준 2) · 가벼움 1 은 무거움 수정으로 함께 해소(날짜 오프셋 혼합) · 그 외 1 고침(테스트 approx))
- [x] `/code-review xhigh` **2회차** (발견 12건 — 버그 4 [무거움 0 · 가벼움 4] · 그 외 8 · 조치: 가벼움 1 수정(테스트의 불필요한 `# type: ignore` — PyRight 실패) · 가벼움 3 은 1회차와 같은 지적(미룸 1 · 거름 2) · 그 외 2 고침(주석 간결체 · 날짜 문구 정확도))
- [x] 수정분 검증 (수정 2건 · 발견 2건 — 무거움 0 · 조치: 고치지 않음 — 오류 메시지의 `%Y-%m-%d` 표기 · 테스트 `match` 의 죽은 `YYYY|` 분기, 둘 다 표기)
- [x] `poetry run python validate_project.py` (passed=589, failed=0, skipped=0)

#### Commit Messages (Final candidates) — 5개 중 1개 선택

> **Done 직전에 `/commit` 을 실행해 이 절을 채운다. 그전에는 비워 둔다** — 추측으로 적은 줄은 그대로 나간다.

1. 수집 / VIX · 공포탐욕지수 받기 추가
2. 수집 / verify-lab 하락_단계_매수 신호용 VIX · 공포탐욕지수 덧붙이기 자료 추가와 2026-11-10 기준 첫 수집
3. 수집 / 공포탐욕지수 공개 결합본 받기 함수와 계열 판정 연결, 야후 ^VIX 지수 추가
4. 수집 / 공포탐욕지수 결합본의 헤더 · 칸 수 · 날짜 · 0 ~ 100 범위 검사 받기와 VIX 지수 첫 수집
5. 수집 / 하락 단계 신호 자료(VIX · 공포탐욕지수) 추가 — 결정 Q37 · Q38 · 결합본 대조 · 미룬 지적 3건

## 7) 리스크(Risks)

- **결합본이 과거 값을 바꾸면 갱신이 멈춘다** — 2021-02-01 이후를 매 실행 CNN 피드로 다시 만들므로 CNN 이 지난 값을 고치면 판정 규칙 ①(상대 2e-5 + 반 단위)에 걸린다. 의도한 동작이다(판정 원칙) — 멈추면 사람이 정한다
- **결합본 저장소가 사라지거나 모양을 바꾸면 받기가 실패한다** — 헤더 검사로 즉시 멈추고, 그때까지 받은 파일은 매니페스트에 남는다
- **다시 받음 자료의 수정주가가 바뀔 수 있다** — 2026-11-10 이후 새 배당 기록이 그 전 날짜에 반영되면. Phase 2 에서 목록으로 드러나고 verify-lab 계획서가 기존 매매법 재실행으로 받는다
- 공개 저장소에 CNN 자료의 사본이 커밋된다 — 라이선스 미확인(사용자 결정 2026-11-13 — 출처 표기)
- 실제 산출물로 잴 글자 규칙 판정은 없다(헤더 · 범위는 숫자 검사)

## 8) 메모(Notes)

- 결정 경위: verify-lab 세션 2026-11-13 ~ 16 — Q4 하이일드 진행 안 함 · Q5 VIX 는 야후 `^VIX` · Q3 공포탐욕지수는 관찰 · 격자 축(이후 Q6 에서 격자 축으로 재는 것으로 확정)
- 결합본 URL: `https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv` (README 「Canonical dataset」 — 2026-11-13 확인)
- 야후 `^VIX` 조회(2026-11-13): 9,287행 1990-01-02 ~ 2026-11-12. FRED `VIXCLS` 와 행 수가 달라(FRED 9,617행 · 빈 값 302) verify-lab 쪽 데이터 실측 기록에서 대조한다

### 진행 로그 (KST)

- 2026-11-16 11:40: 계획서 작성 (Draft — 승인 대기)
- 2026-11-16 11:53: 사용자 승인(「진행」) — 착수
- 2026-11-16 11:56: Phase 0 레드(`ModuleNotFoundError`) → Phase 1 그린(대상 테스트 113 passed)
- 2026-11-16 11:57: 갱신 `--end 2026-11-10` 종료 코드 0 · 54개 파일 씀. 매니페스트: `^VIX_raw.csv` 신규 9,285행 1990-01-02 ~ 2026-11-10 · `fear_greed_daily.csv` 신규 3,965행 2011-01-03 ~ 2026-11-10. `git status --short storage/` 로 바뀐 기존 파일: `TLT_adjusted.csv` · `SPTL_adjusted.csv`(둘 다 판정 「배당 반영」 — 판정 원칙이 허용하는 변화) · `TLT_synthetic.csv`(가공) · `validation/summary.csv` · `validation/years.csv`(TLT 검증 표 한 줄씩). **verify-lab 이 받는 파일(SPY · QQQ · DIA 수정주가 · ^GSPC · ^IXIC · BTC 넷)은 바뀌지 않았다** — verify-lab 계획서 Phase 4 는 켜지지 않을 것이 기대값(내보내기 diff 로 확인)
- 2026-11-16 12:00: 문서 — `시세_받기_판정.md` 2장 추가 줄 · 3.3 절(Q37 · Q38) · 6.12 절(VIX 날 수 · 결합본 대조). `docs/COMMANDS.md` 변경 없음. black 적용(변경 없음)
- 2026-11-16 12:20: 리뷰 1회차 분류 —
  | # | 지적 | 종류 | 처리 · 근거 |
  |---|---|---|---|
  | 1 | 공포탐욕지수 빠진 날 검사 없음 | 가벼움(닿음 — 실측 23일: 2020-06-08 ~ 07-08 22일 · 2026-03-12) | 문서화(6.12). 받기에서 막으면 출처가 영구히 없는 날이라 매 갱신이 멈춤 — 쓰는 쪽(verify-lab)이 대상 거래일로 맞추고 셈 |
  | 2 | 끝날이 기준일에 닿았는지 검사 없음(출처 정지 · 23:00 UTC 전 실행) | 가벼움(닿음 — 외부 연계) | 미룸 — 다른 자료의 끝날에 기대는 준비 검사라 설계 결정이 필요 |
  | 3 | 빈 날짜가 NaT 로 남아 `_cut` 에서 조용히 빠짐 | 무거움(위험한 쪽 — 행이 에러 없이 사라짐) | 고침 — 날짜 형식 고정 · NaT 면 멈춤. 근원(`series.validate_series` 가 날짜 결측을 안 봄)은 diff 밖이라 미룸 |
  | 4 | 칸이 많은 행을 pandas 가 인덱스로 돌려 값을 옆 칸에서 읽음 | 무거움(위험한 쪽 — 틀린 값이 에러 없이) | 고침 — csv 로 읽고 행마다 칸 수 검사 |
  | 5 | `read()` 중 타임아웃 등이 ValueError 로 안 바뀜 | 가벼움 | 거름 기준 2(멈추는 쪽 · 안내만 어색) |
  | 6 | 날짜 오프셋 혼합에서 AttributeError | 가벼움 | 3 의 수정으로 ValueError 가 됨(테스트 파라미터) |
  | 7 | VIX 휴장일 봉 | 가벼움(닿음 — 실측 2일: 2026-05-25 · 2026-09-07) | 문서화(6.12) · verify-lab 이 판정일을 대상 거래일로 맞춤 |
  | 8 | 오류 문구에 할 일(`--exclude FEAR_GREED`)이 없음 | 가벼움 | 거름 기준 2 |
  | 9 | 6자리가 루트 `CLAUDE.md` 자릿수 예외에 없음 | 그 외 | 고치지 않음(계열 자릿수의 SoT 는 카탈로그 — Coin Metrics 도 거기만 있음) |
  | 10 | `_form_of` 의 새 종류를 지키는 테스트 없음 | 그 외 | 그 경로는 받지 않은 파일의 매니페스트 기간 읽기뿐이라 막는 결함이 가벼움(변형 1 이 통과로 확인). 판정 경로의 기존 파일 검사 테스트를 더함 — 변형(`load_series` 검사 제거)에서 `DID NOT RAISE` 로 실패 확인 |
  | 11 | 6자리 저장 대 13자리 응답의 노이즈 경로 테스트 없음 | 그 외 | 막는 결함(매 실행 멈춤)은 공유 허용폭(상대 2e-5)을 반올림 반 단위(5e-7) 아래로 바꿔야 생김 — 닿지 않음 |
  | 12 · 13 | 받기 · 계열 분기 블록 복제 | 그 외 | 고치지 않음 |
  | 14 | 실수 목록을 `==` 로 비교 | 그 외 | 고침(전역 테스트 규칙 — 새로 쓴 코드) |
  | 15 | 테스트 docstring 미갱신 · falsy 기본값 | 그 외 | 고치지 않음 |
- 2026-11-16 12:20: 변형 확인 — 칸 수 검사를 「모자람」만 보게: `test_rejects_row_with_extra_field` 실패(`3 columns passed, passed data had 4 columns`) / 날짜 형식 고정 제거: `test_rejects_blank_or_other_date_format` 2 실패 / 셋 다 사본으로 되돌려 `diff -q` 같음 · 대상 테스트 118 passed
- 2026-11-16 12:40: 리뷰 2회차 분류 — ① 불필요한 `# type: ignore`(가벼움 — 품질 검증 실패) 고침 ② 결합본 마지막 행이 나중에 고쳐지면 멈춤 — 계획서 리스크가 받아들인 판정 원칙대로의 멈춤이고, 11-13 과 11-16 에 받은 값이 겹친 3,965일 모두 같음(실측) → 받아들임 ③ 끝날 준비 검사 = 1회차 2 와 같음(미룸) ④ VIX 뉴욕 18:00 기준 미측정 — 야후 동작을 재지 않아 판정할 수 없음 → 미룸 ⑤ `_form_of` 테스트 = 1회차 10 과 같음(그 외) ⑥ read 중 예외 · ⑦ 할 일 안내 = 1회차 5 · 8 과 같음(거름 기준 2) ⑧ 주석 「~다」 → 간결체로 고침(그 외 · 전역 주석 규칙) ⑨ · ⑩ 복제 · 세 곳에 적힌 계열 종류(그 외) ⑪ 날짜 문구가 실제보다 엄격 → 문구 고침(그 외) ⑫ 머리말 목록 미갱신(그 외)
- 2026-11-16 12:45: 수정분 검증(서브에이전트 — diff 와 겨냥한 지적만) — 네 hunk 모두 실행 코드 변화 없음 · 위험 방향 변화 없음 · PyRight 두 파일 0건 · `test_fear_greed.py` 14 passed. 발견 둘(표기)은 고치지 않음
- 2026-11-16 12:45: 미룬 지적 3건 옮김. 거른 지적(옮기지 않음): 1회차 5 · 8(2회차 ⑥ · ⑦) — 기준 2(멈추는 쪽 · 안내만 어색, 지금 산출물 0) / 1회차 11 — 기준 1(공유 허용폭 상대 2e-5 ≫ 반올림 반 단위 5e-7) / 1회차 9 · 10 · 12 ~ 15 · 2회차 ⑤ ⑨ ⑩ ⑫ — 기준 3(그 외) / 2회차 ② — 받아들임(실측 0)
- 2026-11-16 12:45: 품질 검증 passed=589 · failed=0 · skipped=0

---
