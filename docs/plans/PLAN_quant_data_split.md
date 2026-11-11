# Implementation Plan: 1단계 — 데이터 저장소(quant-data) 신설과 quant 의 시세 받기 · 합성 이관

> 작성/운영 규칙(SoT): `/impl-plan` 스킬(`~/.claude/skills/impl-plan/SKILL.md`)을 반드시 참고하세요.  
> (이 템플릿을 수정하거나 새로운 양식의 계획서를 만들 때도 해당 스킬을 포인터로 두고 준수합니다.)

**상태**: 🔄 In Progress

---

> 상태는 🟡 Draft / 🔄 In Progress / ✅ Done. Done 조건과 기록 규칙은 `/impl-plan` 「3) 스킵 및 완료 규칙」이며 `~/.claude/hooks/plan_lint.py` 가 저장 때 검사한다.

---

**작성일**: 2026-11-11 10:58
**마지막 업데이트**: 2026-11-11 14:40
**관련 범위**: 새 저장소 quant-data(받기 · 판정 · 가공 · 내보내기), quant(scripts/data · utils · tqqq 이관과 삭제, 시세 경로, storage/stock · etc, 문서), verify-lab(읽기만 — 수집 대상을 데이터 저장소가 처음 한 번 받아 대조)
**관련 문서**: quant — CLAUDE.md, docs/MEMORY.md, docs/CLAUDE.md, docs/COMMANDS.md, README.md, scripts/CLAUDE.md, src/qbt/CLAUDE.md, src/qbt/utils/CLAUDE.md, src/qbt/tqqq/CLAUDE.md, src/qbt/backtest/CLAUDE.md, tests/CLAUDE.md, docs/research/합성_시세_연장.md · verify-lab — CLAUDE.md, src/verify_lab/CLAUDE.md, scripts/CLAUDE.md, reference/pykrx_실측기록.md, docs/조사/역방향.md §14

---

## 1) 목표(Goal)

- [ ] 목표 1: quant-data 저장소 뼈대 — 사용자가 GitHub 공개 저장소를 만들어 `/Users/yubeen/Workspace/quant-data` 에 받고, 개인 저장소 공통 스택(Python 3.12 · Poetry · Black · Ruff · PyRight · `validate_project.py`)과 `CLAUDE.md` · `docs/COMMANDS.md` · `docs/plans/` · `.claude/plan-config.json` 을 갖춘다. 이 계획서를 그 저장소의 `docs/plans/` 로 옮긴다(Q25)
- [ ] 목표 2: 갱신 명령 — quant 의 받기 · 판정 · 합성을 옮기고 「결정 기록」을 반영한다(전부 성공했을 때만 쓰기 · `--exclude` · `--accept` · 분할도 비정상 · 고정 자료는 받지 않음 · 레버리지 시뮬레이션은 상장 전까지만 · 파일 이름에 가격 기준 · 판 요약)
- [ ] 목표 3: 내보내기 명령(표준 라이브러리만)과 quant 전환 — quant 가 목록 파일대로 받은 사본만 읽고, 전환 뒤 quant 결과의 **수치 필드 차이 0**
- [ ] 목표 4: verify-lab 몫 첫 판 — 수집기가 있는 자료 전부를 데이터 저장소가 새로 받고, verify-lab 의 기존 파일과는 대조만 한다(Q9 · Q13). 국내 수정주가는 KRX 원본가 + 야후 분배 기록으로 만들고 KRX 수정주가와 대조한다(Q14)
- [ ] 목표 5: 문서 — 합성 문서를 나눈다(Q15). 이 계획의 결정과 측정을 quant-data 의 살아있는 문서로 옮긴다

## 2) 비목표(Non-Goals)

- verify-lab 이 데이터 저장소에서 읽도록 바꾸기 — 3단계(Q21). 1단계 동안 verify-lab 은 자기 수집기와 자기 파일을 그대로 쓴다
- 국내 합성(지수로 상장 전 채우기) — 2단계 연구(Q21). 1단계는 합성 코드를 시장 · 상품 표로 두어 끼워 넣을 수 있게만 한다
- 미국 합성 기간 늘리기 — 하지 않는다(Q22, 결정 8 유지)
- quant-notify — 대상 아님(Q3)
- GitHub Actions · 매일 갱신 — 갱신은 필요할 때 로컬에서만(Q5 · Q7)
- 1단계 동안 quant 몫 새로 받기 — 첫 판은 지금 quant 파일(2026-11-06 까지) 그대로다. 결과가 바뀌면 「옮기다 생긴 차이」인지 「새 데이터」인지 가를 수 없다
- 수집기가 지워진 verify-lab 파일 옮기기 — CD91 · DTB3 · USDKRW · USDKRW_CLOSE · 520057 · 530107 과 그 IV · KRDRVFUK2I · KRDRVFUKQI(Q9)
- git 조작 — 저장소 생성 · 커밋 · push 는 사용자가 한다(전역 Git 규칙, Q11)
- 진행 상태 · 인계 문서를 따로 두기 — 이 계획서가 다른 세션의 출발점이다(8장 「다른 세션에서 이어갈 때」, 전역 「개인 프로젝트 공통」)

## 3) 배경/맥락(Context)

### 현재 문제점 / 동기

- 사용자 요청(2026-11-10): 「데이터 다운로드 하는것은 별도의 레포지토리로 분리할까해. 워크스페이스 보면 다른 프로젝트도 비슷하게 데이터를 다운 받는 곳이 많은데, 이걸 통일할 필요가 있어」 · (2026-11-11) 「다운로드 뿐만 아니라. 합성하는것도 공통으로 관리하고 싶어」 · 「나는 국내든 해외든 최대한 1배, 레버리지 등 최대한 긴기간을 테스트해보고 싶어. 단 이를 위해서 tqqq 합성처럼 최대한 정밀하게 해야돼」
- 지금 quant 와 verify-lab 이 같은 미국 ETF 6종(QQQ · SPY · QLD · SSO · TQQQ · UPRO)을 각자 받고, 같은 일을 다른 규칙으로 한다 — 가격 자릿수 6 / 4, 수정주가만 / 원본가 · 수정주가 두 파일, 다시 받을 때 대조 후 멈춤 / 그냥 덮어씀, 마지막 날 뉴욕 18:00 / 한국 날짜 −2일
- 같은 파일 이름이 다른 뜻이다 — quant `QQQ_max.csv` 는 수정주가, verify-lab `QQQ_max.csv` 는 원본가(`QQQ_adjusted_max.csv` 가 수정주가). 합칠 때 잘못 맞추면 원본가를 읽어도 에러가 나지 않는다
- 「다시 받은 시세가 기존 파일과 다르면 원인을 가리는」 방어(quant 결정 14)가 verify-lab 에는 없다

### 결정 기록 (2026-11-10 ~ 11 grilling — 이 계획의 기준, 다시 묻지 않는다)

| # | 항목 | 결정 |
|---|---|---|
| 판정 원칙 | 다시 받은 데이터 | 「수정주가가 배당으로 바뀌는 것 말고는 데이터가 바뀌면 오류다. 정상이면 최신 데이터만 추가된다」(사용자 2026-11-11) |
| Q1 | 목적 | 받기와 합성을 한 저장소에서 관리하고, 사용처는 가져다 쓴다 |
| Q2 | 가져오기 | 데이터 저장소의 **로컬 작업 트리**에서 그대로 가져오고, **사용처가 사본을 결과와 함께 커밋**한다. 판 요약에 데이터 저장소의 커밋 번호와 「커밋 안 된 변경 있음」 여부를 적는다. (처음 (가) 「판 번호만 커밋」 → 로컬 경로 · 사람 push 로 흐름이 바뀌어 11-11 (나)로 바꿈) |
| Q3 | quant-notify | 대상 아님 |
| Q5 | 주기 | 매일 갱신하지 않는다 — 필요할 때 사람이나 AI 가 로컬에서 |
| Q6 | 가격 자릿수 | 6자리 — quant 입력 그대로(전역 4자리 규칙의 예외, quant 루트 `CLAUDE.md` 「가격 반올림 자릿수」). verify-lab 은 3단계 전환 때 측정값이 미세하게 바뀌고, 그 규칙대로 흔적을 남긴다 |
| Q7 · Q11 | 실행 · push | 로컬 실행. commit · push 는 사용자(주기적으로, 또는 다른 PC 로 옮길 때). AI 는 갱신 · 내보내기 명령을 돌리고 결과를 보고한다. (Q11 은 처음 (가) 「AI 가 승인받고 push」 → 11-11 (다)로 바꿈 — 전역 Git 규칙 예외 불필요) |
| Q9 | verify-lab 몫 범위 | 수집기가 있는 자료 전부(2장 비목표의 고아 파일 제외) |
| Q10 | 파일 이름 | 가격 기준을 이름에 넣는다(예: `QQQ_raw` · `QQQ_adjusted`) — 옛 이름을 읽는 코드는 「파일 없음」으로 바로 드러난다 |
| Q12 | 제외 표시 | 실행 끝 경고 + 판 요약 파일(종목별 기간 · 제외 · 받아들임 · 분배 기록 첫날 · 대조 어긋난 날) |
| Q13 | verify-lab 방식 | ① 덮어쓰기 대신 기존과 견줘 저장 ② 조사마다 다른 끝날이 아니라 판 하나로 ③ 첫 판은 새로 받고 verify-lab 기존 파일은 대조에만 |
| Q14 | 국내 수정주가 | KRX 원본가 + 야후 분배 기록으로 만든다(C-2). KRX 수정주가가 있는 구간(최근 3,000거래일)에서 대조해 어긋난 날을 판 요약에 적고 값은 바꾸지 않는다 |
| Q15 | 합성 문서 | 나눈다 — 합성 · 받기 결정과 검증 표는 quant-data 로, 백테스트 몫(결정 10 · 6.11 · 6.12)은 quant 에 |
| Q16 | 비정상 처리 | 멈춘다 → 사람이 확인 → `--exclude 종목`(옛 값 · 옛 끝날 유지) 또는 `--accept 종목`(이번 응답으로 덮어씀)을 지정해 다시 실행. 둘 다 사람이 정한다(AI 가 스스로 지정하지 않는다). 터미널 y / N(결정 14)을 대체 |
| Q17 | 멈춤 범위 | 끝까지 받아 판정하고 비정상을 한 번에 보인 뒤 **아무 파일도 쓰지 않는다**. 받기 실패(예외)는 그 자리에서 멈추고 역시 쓰지 않는다 |
| Q19 | 스크립트 자리 | 데이터 저장소에만 — 갱신 · 내보내기(`--to <사용처 경로>`). 사용처에는 필요한 파일 목록 하나. 내보내기는 표준 라이브러리만(다른 저장소의 `poetry run` 이 엉뚱한 가상환경을 잡는 함정 — 전역 도구 함정 §7) |
| Q20 | 고정 | 쓰는 곳이 없으면 고정이 기본 — 합성 재료 · 검증용 펀드 · 조사 전용 자료는 첫 판 뒤 다시 받지 않는다. 레버리지 시뮬레이션은 상장 전까지만 돌린다(금리 · 운용비율 고정이 가능해지고, 운용비율 손 갱신과 낡음 멈춤이 사라짐). 합성 검증 표는 고정 시점의 기록. **예외 — 나스닥100 지수는 짝 대조(Q29)에 쓰여 「덧붙이기」** |
| Q21 | 단계 | 1단계(이 계획) → 2단계 국내 합성 연구 → 3단계 verify-lab 전환 |
| Q22 | 미국 기간 | 늘리지 않는다(결정 8 유지) — 「1980년도부터 가능하니까 충분해. 닷컴버블, 리먼브라더스도 경험하잖아」 |
| Q23 | 분할 | 비정상으로 멈춘다 — 원인에 「분할로 보이는 변화: 날짜 · 비율(야후 기록)」을 적고, 사람이 운용사 공시와 대조해 `--accept`. 분할 종목을 `--exclude` 하면 다음 갱신에도 계속 멈춘다고 안내한다 |
| Q24 | 이름 · 자리 | `quant-data` · `/Users/yubeen/Workspace/quant-data` (quant 옆 — 내보내기의 기본 경로, 다르면 환경 변수) |
| Q25 | 계획서 자리 | quant `docs/plans/` 에서 시작해 저장소 폴더가 생기면 quant-data `docs/plans/` 로 옮긴다 |
| Q26 | 급등락에 걸린 날 | 저장 거부(`ValueError`)를 없애고 비정상 판정의 하나로 둔다 — 멈춤 → 확인 → 패스 목록(Q29) |
| Q27 | 하루 50% 기준 | 짝 대조(Q29)로 대체한다. 짝이 정해지기 전의 금 · 장기채에만 임시로 남긴다. 50% 의 출처: 2025-11-23 첫 구현 20% → 2025-12-10 커밋 「급등락 임계치 수정 20% -> 50%」(근거 기록 없음) |
| Q28 | 대조 기준 | 국내 수정주가 대조(C-2)의 「어긋난 날」은 퍼센트를 고르지 않고 원 단위 반올림만으로 설명되지 않는 차이로 정한다(결정 14 의 반올림 반 단위와 같은 방식) |
| Q29 | 새로 붙는 날 검사 | **새로 붙는 날만** 검사한다(과거는 판정 규칙의 상대 2e-5 가 지킨다). 국내: KRX ↔ 야후 원본가 **완전 일치**(야후에 그날이 없으면 KRX 공식 등락률 대조만). 미국: **짝 차이** — 대상 하루 수익률 − 배율 × 짝 하루 수익률. 기준을 넘으면 멈추고, 실제 대폭락 · 대폭등이면 **패스 목록**(종목 · 날짜 · 검사 · 사유 · 근거)에 적은 뒤 다시 실행. 패스 목록은 **사람과 AI 모두 적을 수 있다**(사용자 2026-11-11). `--exclude` · `--accept` · 국내 분할 기록은 사람만 |
| Q30 | 짝 차이 기준 | 배율 × 1%p (1배 1%p · 2배 2%p · 3배 3%p) — 2016년 이후 넘은 날 QQQ 2 · SPY 1 · TQQQ 2 · QLD · SSO · UPRO 0, 모두 2020-03 |
| Q31 | 짝이 없는 금 · 장기채 | 같은 자산의 다른 ETF(금 ↔ IAU, 장기채 ↔ 다른 장기국채 ETF)를 짝 후보로 Phase 4 착수 전에 잰다. 약하면 종목 자체 하루 변동 범위 + 패스 목록으로 |
| Q32 | 검증 표 ② ③ | quant 의 지금 `tracking.csv` · `funds.csv` · `fund_years.csv` 를 그대로 옮겨 굳힌다 — Q20 으로 상장 뒤 시뮬레이션이 없어 ② 와 ③ 의 레버리지 4종 행을 다시 만들 수 없다. 계산 함수 `summarize_tracking` · `compare_around` · `yearly_costs` 와 그 테스트 12개는 옮기지 않는다. ① 대용 ↔ 실물 · ④ 가정 판은 생성 때마다 다시 만든다(사용자 2026-11-11 「추천대로」) |
| Q33 | 파일 이름 | `{티커}_raw.csv` · `{티커}_adjusted.csv` · `{티커}_synthetic.csv` — `_max` 를 뺀다(늘 전 기간이라 정보가 없다 — 사용자 2026-11-11). quant 결과의 시세 경로 61개(19파일, 전부 `*_synthetic_max.csv`)가 바뀌고, 옛 이름을 읽는 코드는 모두 「파일 없음」으로 드러난다 |
| Q34 | 새 파일의 새로 붙는 날 검사 | 기존 파일이 없으면 미국 짝 차이는 걸지 않고, 국내 두 검사(KRX ↔ 야후 원본가 · 공식 등락률)는 전 기간에 건다 — 미국은 전 기간 꼬리가 굵고, 국내는 분할을 찾아야 C-2 가 맞다(사용자 2026-11-11 「추천대로」) |
| Q35 | 받기 코드 | FRED 금리 · Perth Mint 금값 · FRED 호주달러 환율을 받는 코드와 그 테스트 23개도 옮긴다(사용자 2026-11-11 「옮겨 둔다」) |
| Q36 | 월별 금리 | **덧붙이기** — 새로 나온 달은 받아 붙이고, 지난 달 값이 바뀌면 판정 원칙대로 멈춘다(사용자 2026-11-11 「신규로 올라온 금리는 적용해줘야돼」 → 「추천대로」). 합성은 Q20 대로 상장일까지만 돌아 새 금리가 합성 값을 바꾸지 않는다 — 파일만 최신으로 둔다. 다른 고정 자료(호주달러 환율 · VFINX · VUSTX · GC=F · 검증용 펀드 · 조사 전용)는 Q20 그대로 |
| 기본값 | 묻지 않고 반영 | 받을 마지막 날은 출처별 지금 규칙(미국 quant 방식 · 국내 한국 날짜 −1일 · 코인 끝나지 않은 UTC 날 제외) · 지수는 받은 시가 · 고가 · 저가 · 종가 그대로(quant QQQ 합성이 나스닥100 지수의 고가 · 저가를 씀 — `proxy_series.py:106-107`) · 국내 수정주가는 6자리 |
| 추천 · 이 계획 승인으로 확정 | 국내 분할 | KRX 원본가의 하루 변화와 KRX 공식 등락률이 어긋나는 날을 「액션(분할 · 병합 등)이 있던 날」로 보고 멈춘다(verify-lab `reference/pykrx_실측기록.md` 8.2 판정 규칙). 사람이 공시를 확인하면 「국내 분할 기록」 파일(사람이 쓰는 파일)에 날짜 · 비율을 적는다 → 다시 실행하면 그날은 설명된 변화로 통과하고, 국내 수정주가가 그날 앞 값에 비율을 입힌다. 원본가 파일은 KRX 값 그대로 둔다 |

### 자료별 갱신 방식

| 방식 | 자료 |
|---|---|
| **다시 받음** — 한 응답에서 수정주가(다시 계산) · 원본가(덧붙이기) | SPY · QQQ · GLD · TLT · TQQQ · SSO · QLD · UPRO(quant) · DIA(verify-lab 중간선거) |
| **덧붙이기** | S&P500 · 나스닥 종합 지수(GSPC · IXIC — verify-lab 중간선거의 측정 대상, GSPC 는 SPY · SSO · UPRO 의 짝), 나스닥100 지수(QQQ · QLD · TQQQ 의 짝 — Q29), 다우 지수(DIA 의 짝 — 새로 받음), 비트코인 Bitstamp 일봉 · Coin Metrics 3종(두 출처 대조 유지), 월별 금리(Q36). 금 · 장기채의 짝 ETF 는 Q31 측정 뒤 정한다 |
| **고정** — 첫 판 뒤 받지 않음 | 합성 재료: VFINX · VUSTX · 금 선물(GC=F) · Perth Mint 금값 · 호주달러 환율 · 운용비율 / 검증용 펀드: UOPIX · ULPIX · RYNVX / 조사 전용: 미국 레버리지 · 인버스 11종(DDM · DOG · DXD · PSQ · QID · SDOW · SDS · SH · SPXU · SQQQ · UDOW), 국내 ETF 9종(069500 · 114800 · 122630 · 229200 · 233740 · 251340 · 252670 · 261240 · 261250), 국내 지수 4종(1001 · 1028 · 2001 · 2203), NAV 2종(261240 · 261250) |
| **가공** — 매번 다시 만듦 | 합성 8종(QQQ · SPY · TLT · GLD · QLD · TQQQ · SSO · UPRO), 국내 수정주가 9종 |

- quant 몫의 고정 자료는 지금 quant 파일이 첫 판이다. verify-lab 몫은 새로 받는다(Q13)
- 국내 합성(2단계)을 만들면 국내 ETF · 지수가 고정에서 「다시 받음 · 덧붙이기」로 옮겨진다 — 갱신 방식은 데이터 저장소의 표 한 곳에서 자료마다 정한다

### 가공 규칙 — 원본을 바꾸는 곳은 여기뿐

- **C-1 미국 수정주가** — 야후 `auto_adjust=False` 응답에서: 종가 = 수정 종가, 시가 · 고가 · 저가 = 원시 값 × (수정 종가 ÷ 원시 종가), 거래량 그대로(quant `stock_downloader.adjust_prices`)
- **C-2 국내 수정주가** — KRX 원본가의 하루 등락을 이어 붙이고, 분배일에만 그 앞 값 전체에 「1 − 분배금 ÷ 전 거래일 원본 종가」를 곱한다(분배금은 야후 기록). 국내 분할 기록이 있으면 같은 방식으로 그 비율을 입힌다. 야후 첫 분배 기록 앞 구간은 원본가 등락 그대로(그만큼 덜 좋게 잡힘)
- **C-3 1배 대용 합성** — QQQ ← 나스닥100 지수, SPY ← VFINX, TLT ← VUSTX. 실물 첫 거래일(이음매) 종가 비율로 대용 가격을 맞추고, 이음매 앞 시가 = 그날 종가(결정 3), 이음매부터 실물 행 그대로(저장 전 검사)
- **C-4 금 사슬** — 1980-01-02 Perth 호주달러 금값 × 호주달러 환율 → 1991-06-20 Perth 달러값 → 2000-08-30 금 선물 → 2004-11-18 GLD. 미국 날짜 d 에 호주 d + 1영업일 값, 사슬 전체에 GLD 보수 연 0.40% 를 뺀다(결정 6 · 13)
- **C-5 레버리지 합성** — QLD · TQQQ ← QQQ 합성, SSO · UPRO ← SPY 합성. 하루 수익 = 기초 등락 × 배율 − 하루 비용(금리 + softplus 가산금리 — 1998-12 까지 상한 1.6% — × (배율 − 1) + 운용비율, 연 거래일 수로 나눔). 상장일 종가 비율로 맞춰 실물에 잇는다. **시뮬레이션은 상장 전까지만**(Q20)

### 판정 규칙 ① — 과거 행 (다시 받을 때)

| 판정 | 조건 | 처리 |
|---|---|---|
| 흔들림뿐 | 겹친 날 네 가격이 모두 상대 2e-5 + 6자리 반올림 반 단위 안 | 기존 행 그대로, 새 날짜만 붙임 |
| 설명되는 변화 | 응답의 **배당** 기록으로 설명됨 | 덮어씀 |
| 비정상 | 그 밖 — **분할 포함**(Q23) · 국내 원본가의 공식 등락률 어긋남 | 아무것도 안 쓰고 멈춤 → `--exclude` / `--accept` / 국내 분할 기록 (사람만) |

- 야후 원본가는 분할만 과거에 반영된다 → 분할 아닌 변화는 모두 오류. KRX 원본가는 분할도 반영하지 않는다 → 과거가 바뀌면 모두 오류, 분할은 그날 하루의 가짜 등락으로 나타난다
- 하루 급등락 50% 검사는 분할 감지 장치로 믿지 않는다 — 2:1 분할 날 시장이 오르면 −49.x% 로 빠져나간다. 국내는 공식 등락률 대조로 잡는다

### 판정 규칙 ② — 새로 붙는 날 (Q26 · Q27 · Q29 ~ Q31)

| 시장 | 검사 | 기준 | 넘으면 |
|---|---|---|---|
| 국내 | KRX 원본가 ↔ 야후 원본가 | **완전 일치**(원 단위). 야후에 그날이 없으면 건너뛰고 공식 등락률 대조만 | 멈춤 → 패스 목록 |
| 국내 | KRX 원본가 하루 변화 ↔ KRX 공식 등락률 | 표기 자릿수의 반 단위(Phase 4 착수 전 측정에서 자릿수 확인) | 멈춤 → 국내 분할 기록(액션) 또는 패스 목록 |
| 미국 | 대상 하루 수익률 − 배율 × 짝 하루 수익률 — 짝: QQQ · QLD · TQQQ ↔ 나스닥100 지수, SPY · SSO · UPRO ↔ S&P500 지수, DIA ↔ 다우 지수 | 배율 × 1%p (Q30) | 멈춤 → 패스 목록 |
| 미국 | 금 · 장기채 | 짝 후보(IAU · 장기국채 ETF)를 잰 뒤 정함. 그전까지 하루 변동 50% (Q27 임시) | 멈춤 → 패스 목록 |

- **패스 목록** — 데이터 저장소의 파일 하나. 한 줄에 종목 · 날짜 · 검사 · 사유 · 근거. 사람과 AI 모두 적는다. AI 가 적을 때는 근거(그날 짝 지수의 변동 · 같은 날 함께 넘은 종목 등)를 함께 적고 추가한 사실을 보고한다. 근거가 없으면 적지 않고 보고만 한다. 데이터 저장소 commit 은 사용자가 하므로 diff 가 검토 자리다
- **저장 거부 없음** — 급등락으로 `ValueError` 를 내던 저장 단계 검사를 없애고, 모든 검사는 「멈춤 → 확인 → 다시 실행」 경로를 탄다(Q26)
- 국내 수정주가 대조(C-2)의 「어긋난 날」은 원 단위 반올림으로 설명되지 않는 차이다(Q28) — 값은 바꾸지 않고 판 요약에 적는다

### 착수 전 측정 (2026-11-10 ~ 11 — 저장소 파일은 읽기만)

측정 코드는 `/private/tmp/claude-501/-Users-yubeen-Workspace-quant/383139c4-e3c7-4fe6-ab71-9b92937796da/scratchpad/` 의 `yahoo_kr_check.py` · `kr_adjust_build.py` · `kr_index_vs_etf.py` · `us_pair_tracking.py` · `us_pair_tracking_2016.py` 다(임시 — 세션이 끝나면 사라질 수 있다. 숫자는 아래가 정본).

**quant ↔ verify-lab 겹치는 6종** — 겹친 날 종가 상대차 최대 0.000266(TQQQ — 초기 0.2 달러대 가격의 4자리 반올림), 중앙 0. 끝날: quant 2026-11-06, verify-lab 2026-10-05(QQQ 만 11-04)

**최신 파일을 옛 끝날로 잘라도 옛 파일이 아니다** — quant git 이력의 판 ↔ 지금 파일을 그 끝날로 자른 것:

- QQQ 2025-12-15 판(끝 2025-12-12): 6,734행 전부 다름, 최신/옛 −1 범위 −0.004678 ~ −0.004675(같은 비율 — 배당 재계산)
- TLT 2026-03-07 판(끝 2026-03-05): 5,938행 전부, −0.026590 ~ −0.022865(비율이 날마다 다름 — 수익률 자체가 바뀜)
- TLT 2026-10-31 판(끝 2026-10-29): 6,103행 중 6,082행, +0.000000 ~ +0.004029(야후 10-01 배당 누락)
- QQQ · SPY 2026-10-31 판 이후: 다른 행 0(결정 14 판정이 흔들림에서 기존 행을 지킴)

**야후 국내 ETF(`.KS`) ↔ KRX** (9종)

- 둘 다 값이 있는 날 원본가 종가 상대차 0(9종 모두). 069500 의 같지 않은 5일은 야후 가격이 빈 행(2007-04-27 등, 거래량 0)
- 야후에 없는 날: 069500 567일(겹친 2007-01-29 ~ 2026-11-04 안), 나머지 대부분 31 ~ 34일
- 야후 시작이 늦음: 069500 2007-01-29(KRX 2002-10-14), 261250 2024-06-19(KRX 2016-12-27)
- 배당 기록 어긋남: 069500 KRX 에만 2022-07-28 · 야후에만 2014-07-30 · 2015-07-30 · 2016-07-28 · 2022-10-27, 229200 KRX 에만 2016-12-22 · 야후에만 2026-04-29, 261250 야후에만 2025-12-24(12-29 와 두 건)

**C-2(KRX 원본가 + 야후 분배) ↔ KRX 수정주가** — 하루 수익률 차이가 0.05%p 넘는 날:

- 069500: 2,999일 중 2일(2022-10-27 +0.293%p · 2022-07-28 −0.221%p), 구간 누적 422.4130% vs KRX 422.0784%
- 229200: 2,679일 중 2일(2026-04-29 +0.138%p · 2016-12-22 −0.058%p), 누적 차 +0.2381%p
- 261240: 0일(최대 0.0103%p), 누적 차 −0.0142%p
- 261250: 1일(2025-12-24 +0.715%p), 누적 차 +1.1972%p
- 어긋난 날은 모두 두 출처의 분배 기록이 다른 날이다. 어느 쪽이 맞는지는 운용사 분배 공시와 대조하지 않았다

**국내 지수 ↔ ETF** (2단계 근거) — 하루 등락 상관 0.98 ~ 0.99, 하루 차이 절대 평균 0.12 ~ 0.36%p. 1배 수정주가가 지수보다 연 +2.25%p(KODEX 200 ↔ 코스피200, 해마다 +1.12 ~ +3.55%p) · +0.56%p(코스닥150). 레버리지 · 인버스는 지수 × 배율과 연 −1.25 ~ +0.86%p, 해마다 −8.14 ~ +12.39%p

**하루 급등락 50% 의 여유** — 받은 실물 시세에서 50% 를 넘은 날 0. 가까운 날: KODEX 레버리지(122630) +46.76%(2026-07-31) · 인버스2X(252670) −42.66%(같은 날) · SDOW +36.08% · TQQQ +35.24%. 합성은 넘는다: UPRO 합성 −61.47%(1987-10-19) · TQQQ 합성 +50.46%(2001-01-03) — 그래서 합성은 이 검사를 끄고 저장한다. 비트코인은 verify-lab 이 75%(실제 최대 +56.1%, 자릿수 오류 ×10 · ÷10 은 걸림)

**짝 차이 (2016년 이후, `us_pair_tracking_2016.py`)** — 대상 하루 수익률 − 배율 × 짝 하루 수익률의 절대값:

- QQQ ↔ 나스닥100: 중앙 0.028%p · 99.9% 0.962%p · 최대 1.60%p(2020-03-13) · 1%p 넘는 날 2
- QLD ↔ 나스닥100 × 2: 중앙 0.048%p · 최대 1.78%p(2020-03-19)
- TQQQ ↔ 나스닥100 × 3: 중앙 0.098%p · 99.9% 2.509%p · 최대 3.23%p(2020-03-13)
- SPY ↔ S&P500: 중앙 0.026%p · 99.9% 0.793%p · 최대 1.04%p(2020-03-16) · 1%p 넘는 날 1
- SSO ↔ S&P500 × 2: 중앙 0.052%p · 최대 1.25%p(2020-02-28)
- UPRO ↔ S&P500 × 3: 중앙 0.076%p · 최대 2.05%p(2020-03-19)
- GLD ↔ 금 선물: 중앙 0.201%p · 99% 1.764%p · 최대 3.60%p — 마감 시각이 달라 약하다
- 전 기간으로 재면 꼬리가 굵다(QQQ ↔ 나스닥100 2000년 6.72%p · 1%p 넘는 날 145) → 새로 붙는 날만 검사한다

**종목 자체 하루 변동 (2016년 이후)** — 99% 지점 SPY 3.78% · QQQ 4.49% · QLD 8.98% · SSO 7.41% · TQQQ 13.36% · UPRO 11.09% · GLD 3.55% · TLT 2.68%. 상위 1% 를 극단으로 빼고 범위를 걸면 종목마다 10년에 28일 멈추고 그 범위 안의 오류는 놓친다 — 짝 차이(TQQQ 3%p 기준 10년 2일)보다 덜 정밀하다(Q29 의 근거)

**분할 기록(야후)** — quant 레버리지 4종 2016년 이후 14건, 날짜로 8개(2017-01-12 · 2017-07-17 · 2018-05-24 · 2020-08-18 · 2021-01-21 · 2021-05-25 · 2022-01-13 · 2025-11-20). SPY · GLD · TLT · DIA · 국내 9종 0건. verify-lab 인버스는 잦다(SQQQ 8건 등 — 고정이라 다시 받지 않음)

**quant 쪽**

- 백테스트 코드(`src/qbt/backtest` · `scripts/backtest`)가 이관 대상 모듈(`tqqq` · `proxy_series` · `proxy_comparison` · `gold_proxy` · `stock_downloader` · `price_revision`)을 import 하는 곳 0건
- `storage/etc` 를 가리키는 것은 `common_constants.py` 의 경로 상수뿐(이관 대상)
- 레버리지 시뮬레이션은 기초의 전 기간을 돈다(`tqqq/synthetic.py:160`) — 상장 뒤 구간은 실물 추적 검증표에만 쓰인다
- 결과 파일의 시세 경로 필드: `signal_data_path` 20 · `trade_data_path` 20 · `signal_path` 8 · `trade_path` 13 — 이름을 바꾸면 이 필드만 달라진다
- 이관 대상 테스트: `test_gold_proxy` · `test_price_revision` · `test_proxy_comparison` · `test_proxy_series` · `test_stock_downloader` · `test_tqqq_*`(6), `test_rounding_policy`(입력 자릿수 부분)
- quant 저장소 압축본 179.08 MiB(`git count-objects -vH`)

### 기존 함수 재사용 — 호출처 (전역 「기존 함수 재사용 전 검증」)

- 옮긴다: 위 이관 대상 모듈 — quant 백테스트 import 0건이라 quant 에서 지운다
- 두 저장소에 둔다: 시세 CSV 읽기 · 검사(`utils/data_loader.load_stock_data` · `validate_price_series`) — quant 는 「합성이 짝 실물보다 먼저 끝나면 멈춤」을 포함해 그대로 두고, quant-data 는 생성에 필요한 만큼 옮겨 쓴다(저장소끼리 import 하지 않는다 — quant-notify 와 같은 관용)
- 다시 쓴다: verify-lab 수집기(`yfinance_collector` · `pykrx_collector` · `bitstamp_collector` · `coinmetrics_collector` · `crosscheck`) — 판정 · 이름 · 자릿수가 달라 그대로 옮기지 않고 quant-data 규칙으로 다시 쓴다. 실측으로 굳은 함정(`auto_adjust` · `raise_errors` 명시, KRX 로그인 순서, 국내 휴장일 0 가격 행, 지수 고가 · 저가가 종가로 채워진 옛 구간)은 옮긴다

### 영향받는 규칙(반드시 읽고 전체 숙지)

> 아래 문서에 기재된 규칙을 **모두 숙지**하고 준수합니다.

- `.claude/plan-config.json` — 이 저장소의 검증 명령·자동 포맷·근거 승격 목적지 (**값의 SoT**)
- quant 루트 `CLAUDE.md` — 「계획서 규약 — 이 프로젝트의 설정」(Scope 에 `README.md`), 「스크립트 실행 규칙」, 「가격 반올림 자릿수」, `docs/MEMORY.md`
- quant `docs/CLAUDE.md` · `scripts/CLAUDE.md` · `src/qbt/CLAUDE.md` · `src/qbt/utils/CLAUDE.md` · `src/qbt/tqqq/CLAUDE.md` · `src/qbt/backtest/CLAUDE.md` · `tests/CLAUDE.md`
- quant `docs/research/합성_시세_연장.md` — 결정 1 ~ 14, 5장 검증 설계, 6.13
- verify-lab 루트 `CLAUDE.md`(측정의 원칙 9 · 14, 「재수집은 이미 나온 결과를 바꿉니다」) · `src/verify_lab/CLAUDE.md`(「시세 컬럼명은 저장된 데이터가 정한다」 · 단일 값 시계열 계약) · `reference/pykrx_실측기록.md` · `docs/조사/역방향.md` §14
- 전역 `~/.claude/CLAUDE.md` — 「개인 프로젝트 공통」 · 「환경 설치」 · 「비밀값은 값을 보지 않는다」 · 「하네스 동작」(다른 저장소의 규칙 문서는 직접 연다)
- 전역 `~/.claude/rules/python.md` · `~/.claude/rules/python-tests.md` · `~/.claude/docs/도구_함정.md` §7(`poetry run` 가상환경)

## 4) 완료 조건(Definition of Done)

> Done은 "서술"이 아니라 "체크리스트 상태"로만 판단합니다. (정의/예외는 `/impl-plan` 스킬)

- [ ] 목표 1 ~ 5 충족 — Phase 마다의 대조 수치를 진행 로그에 숫자로
- [ ] 회귀/신규 테스트 — 옮긴 테스트 그린 + 새 규칙(전부 성공 때만 쓰기 · 제외 · 받아들이기 · 분할 비정상 · 고정 자료 미수신 · 상장 전 시뮬레이션 · 판 요약 · 내보내기 · 국내 수정주가 · 국내 분할 감지 · 새로 붙는 날의 짝 차이 · 국내 두 출처 일치 · 패스 목록)
- [ ] quant 전환 뒤 결과 수치 필드 차이 0 — 경로 필드는 이름 변경분만(진행 로그에 대조 결과)
- [ ] 코드 리뷰 실행 및 결과 기록 (마지막 Phase 의 Validation 에 적는다)
- [ ] 품질 검증 통과 — quant-data · quant 둘 다 (마지막 Phase 의 Validation 에 passed/failed/skipped 수를 적는다)
- [ ] 자동 포맷 적용 완료 (마지막 Phase에서 실행 — 두 저장소)
- [ ] 필요한 문서 업데이트 — quant: `docs/COMMANDS.md` · `README.md` · 루트 `CLAUDE.md` · `scripts/CLAUDE.md` · `src/qbt/CLAUDE.md` · `src/qbt/utils/CLAUDE.md` · `tests/CLAUDE.md` 변경 있음, `src/qbt/tqqq/CLAUDE.md` 삭제 / quant-data: 새로 / verify-lab: 변경 없음(3단계)
- [ ] 근거 승격 완료 — 이 계획서를 지금 삭제해도 잃을 정보가 없다 (결정 기록 · 착수 전 측정을 quant-data 의 살아있는 문서로)
- [ ] 미룬 지적 옮김 — 고치지 않은 리뷰 지적을 거르는 기준으로 걸러 `deferred_findings` 파일로 옮겼다. 계획서 없이 읽히게 썼다.
      거른 지적은 진행 로그에 기준 번호와 함께 남기고 Done 보고에 표로 냈다
      이 계획서가 그 파일의 항목을 고쳤다면 그 항목을 지웠다
      (둘 다 없으면 「해당 없음」. `/impl-plan` 의 `review.md` 「미룬 지적 옮기기」 참고)
- [ ] plan 체크박스 최신화(Phase/DoD/Validation 모두 반영)

## 5) 변경 범위(Scope)

### 변경 대상 파일(예상)

**quant-data (새로)**

- 뼈대: `pyproject.toml` · `poetry.toml` · `pyrightconfig.json` · `pytest.ini` · `validate_project.py` · `.gitignore`(`.env` · `.venv`) · `.claude/plan-config.json` · `.claude/settings.json`
- 문서: 루트 `CLAUDE.md` · `README.md` · `docs/COMMANDS.md` · `docs/plans/`(이 계획서) · `docs/research/`(합성 · 받기 결정과 이 계획의 결정 · 측정)
- 코드: `src/<패키지>/` — 받기(야후 · FRED · Perth Mint · KRX · Bitstamp · Coin Metrics) · 판정 · 가공(C-1 ~ C-5) · 판 요약 · 자료별 갱신 방식 표 · 내보내기(표준 라이브러리만) / `scripts/` — 갱신 · 내보내기 / `tests/`
- 데이터: 첫 판(quant 몫은 quant 파일을 새 이름으로, verify-lab 몫은 새로 받음) · 국내 분할 기록 파일(사람이 쓰는 파일, 처음엔 비어 있음) · 패스 목록 파일(사람 · AI 가 쓰는 파일, 처음엔 비어 있음) · 합성 검증 표
- 패키지 이름은 Phase 0 에서 사용자에게 확인한다

**quant**

- 지움: `scripts/data/download_data.py` · `scripts/data/generate_synthetic.py` · `src/qbt/utils/stock_downloader.py` · `price_revision.py` · `gold_proxy.py` · `proxy_series.py` · `proxy_comparison.py` · `src/qbt/tqqq/`(전체) · 위 「이관 대상 테스트」 · `storage/etc/`(전체) · `storage/results/proxy_validation/` · 고정 · 검증 전용 시세(`^NDX` · `VFINX` · `VUSTX` · `GC=F` · `UOPIX` · `ULPIX` · `RYNVX`)
- 고침: `src/qbt/common_constants.py`(시세 경로 → 새 이름, 이관 경로 상수 정리) · 백테스트 설정의 시세 경로 · 사용처 목록 파일(새로) · `storage/stock/`(내보내기로 받은 사본) · `tests/qbt/test_rounding_policy.py`(출력 자릿수만 남김)
- 문서: 루트 `CLAUDE.md`(「스크립트 실행 규칙」의 `download_data.py` 항목 → 데이터 저장소 갱신 · 내보내기, 「데이터 저장소를 다룰 때 그 저장소 `CLAUDE.md` 를 먼저 연다」, 「가격 반올림 자릿수」의 입력 행) · `docs/MEMORY.md`(필요하면) · `docs/research/합성_시세_연장.md`(백테스트 몫만 남김 — 이름 · 자리는 마지막 Phase 에서 확인) · 이 문서를 가리키는 32개 파일 69줄 · `scripts/CLAUDE.md` · `src/qbt/CLAUDE.md` · `src/qbt/utils/CLAUDE.md` · `tests/CLAUDE.md`
- `docs/COMMANDS.md`: **변경 있음** — 워크플로우 1(합성 시세) · 「시세를 다시 받은 뒤 다시 돌리는 순서」 · 「데이터 다운로드 옵션」이 데이터 저장소의 갱신 · 내보내기로 바뀐다
- `README.md`: **변경 있음** — 데이터 받기 · 합성 소개가 데이터 저장소로 옮겨간다(QBT 계획서 규약)

**verify-lab** — 변경 없음(읽기만). 3단계에서 전환한다

### 데이터/결과 영향

- quant 결과: 수치 필드 차이 0 이어야 한다. 경로 필드(`signal_data_path` 등)는 파일 이름 변경분만 다르다
- 합성 8종: 값이 지금 quant 파일과 같아야 한다(상장 전 시뮬레이션만 돌려도 이음매 비율로 맞추므로 같다 — Phase 2 에서 대조)
- 합성 검증 표: quant 에서 빠지고 quant-data 로 간다. 레버리지 실물 추적 · 펀드 대조는 고정 시점(2026-11-06) 기록으로 굳는다
- verify-lab 결과: 바뀌지 않는다(1단계는 읽지 않음)

## 6) 단계별 계획(Phases)

### Phase 0 — 저장소 뼈대 (사용자 작업 포함)

**작업 내용**:

- [x] 사용자: GitHub 에 공개 저장소 `quant-data` 를 만들고 `/Users/yubeen/Workspace/quant-data` 에 받는다
- [x] 패키지 이름 확인(사용자) · `pyproject.toml` 등 뼈대 작성 — 이웃 저장소(quant · verify-lab)의 같은 파일을 열어 맞춘다
- [x] 의존성 설치 — 저장소 `.venv` 에 격리(전역 「환경 설치」 — 무엇을 어디에 까는지 밝히고 승인받아 실행)
- [x] `.env` 에 KRX 계정을 넣는 것은 사용자(값을 보지 않는다 — `grep -c` 로 개수만 확인)
- [x] 이 계획서를 `quant-data/docs/plans/` 로 옮기고 quant `docs/plans/` 에서는 지운다(Q25). 이후 세션은 quant-data 를 작업 디렉터리로 연다

**Validation**:

- [x] quant-data 의 `.venv` 에서 패키지 import 가 된다(`poetry run python -c "import <패키지>"`) — 품질 검증은 마지막 Phase 에서만 돌린다

---

### Phase 1 — 새 규칙을 테스트로 먼저 고정(레드)

**작업 내용**:

- [x] quant 의 이관 대상 테스트를 옮기고 새 이름 · 경로에 맞춘다
- [x] 새 규칙 테스트: 비정상 · 받기 실패 때 아무 파일도 안 씀(Q17) · `--exclude`(옛 값 유지) · `--accept`(덮어씀) · 분할은 비정상 + 원인 문구(Q23) · 고정 자료는 요청하지 않음(Q20) · 상장 전까지만 시뮬레이션해도 합성 값이 같음 · 판 요약 항목(Q12) · 파일 이름의 가격 기준(Q10)
- [x] 내보내기 테스트: 목록 파일대로만 복사 · 판 요약에 커밋 번호와 「커밋 안 된 변경」 여부 · 목록에 있는데 없는 파일이면 멈춤
- [x] 국내 테스트: C-2 계산(분배 · 분할 입히기) · 공식 등락률 어긋남 → 비정상 · 국내 분할 기록 파일이 있으면 통과
- [x] 새로 붙는 날 테스트(판정 규칙 ②): 짝 차이가 배율 × 1%p 를 넘으면 멈춤 · 패스 목록에 있으면 통과 · 과거 행에는 걸지 않음 · 국내 KRX ↔ 야후 원본가가 1원이라도 다르면 멈춤 · 야후에 그날이 없으면 건너뜀 · 급등락으로 저장이 거부되지 않음(Q26)

---

### Phase 2 — quant 몫 이관과 첫 판(그린)

**작업 내용**:

- [x] quant 의 받기 · 판정 · 합성 코드를 옮기고 Phase 1 규칙을 구현한다(터미널 y / N 제거)
- [x] 첫 판: quant 의 지금 시세 · `storage/etc` 파일을 새 이름으로 데이터 저장소에 둔다(받지 않음)
- [x] 합성 생성을 돌려 8종을 만든다

**Validation**:

- [x] 합성 8종의 값이 quant 의 지금 합성 파일과 같다(가격 · 거래량 다른 값 0 — 진행 로그에 종목별)
- [x] 합성 검증 표가 생긴다 — 대용 ↔ 실물은 quant 의 직전 저장값과 같고, 레버리지 추적 · 펀드 대조는 고정 시점 기록

---

### Phase 3 — 내보내기와 quant 전환

**작업 내용**:

- [x] 착수 전 quant `storage/results/` 를 기준으로 남긴다(scratchpad 사본)
- [x] 내보내기 명령을 구현하고, quant 에 목록 파일을 둔다
- [x] quant 의 시세 경로를 새 이름으로 바꾸고, 이관 대상 코드 · 테스트 · 데이터를 지운다
- [x] 내보내기로 quant `storage/stock/` 을 채우고 quant 러너 전부를 돌린다(COMMANDS 「시세를 다시 받은 뒤 다시 돌리는 순서」 ④ — 워크포워드 약 13분)

**Validation**:

- [x] quant 결과 수치 필드 차이 0, 경로 필드는 이름 변경분만(진행 로그에 파일 수 · 필드 수)
- [x] AppTest 로 대시보드 4종 예외 0건(quant 「스크립트 실행 규칙」)

**quant 커밋 준비** — 사용자 요청(2026-11-11 「다음 세션에서 quant 쪽 수정분 커밋하기 전 검증과 테스트 · 커밋 메시지 추천」). Phase 4 보다 먼저 한다. 품질 검증을 이 자리에서 돌리는 것은 「품질 검증은 마지막 Phase 에서만」 규약의 사용자 요청 예외이고, 마지막 Phase 의 두 저장소 검증은 그대로 한다.

- [x] 결정 질문 한 라운드(사용자에게): ① quant 문서 중 지운 것을 가리키는 줄(진행 로그 13:34 무렵 잰 수 — 인계 「미결」)을 이 커밋에 함께 고칠지, Phase 5 로 미룰지 — 고치면 그 문서들은 quant 루트 · 해당 폴더 `CLAUDE.md` 를 먼저 `Read` 로 연다. 합성 문서 나누기(Q15)는 이름 · 자리를 사용자에게 물어야 해 Phase 5 몫 ② 커밋 전에 `/code-review` 를 돌릴지와 수준(계획서 마지막 Phase 는 두 저장소를 `/code-review xhigh` 로 본다)
- [x] quant-data 의 최신 커밋 뒤 내보내기를 다시 돌린다 — `python3 scripts/export.py --to ../quant/storage/stock`(quant-data 에서). quant `storage/stock/quant_data_edition.json` 에 커밋 번호가 적히고 「커밋 안 된 변경」이 빈 목록인지 본다
- [x] quant 자동 포맷 — quant 에서 `env -u VIRTUAL_ENV poetry run black .`
- [x] quant 품질 검증 — quant 에서 `env -u VIRTUAL_ENV poetry run python validate_project.py` (passed=668, failed=0, skipped=0). 실패는 Phase 3 범위 안에서 고치고 진행 로그에 남긴다(고친 뒤 다시 돌린 결과만 이 줄에)
- [x] ② 에서 하기로 했으면 quant 변경에 `/code-review` — 발견 6건 · 조치 6건 수정 (`/code-review` 대신 `review.md` 의 다른 저장소 방식 1회차 — 버그 0 [무거움 0 · 가벼움 0] · 그 외 6, 그 외 6건은 사용자 결정으로 수정)
- [x] quant 변경을 대상으로 `/commit` → 후보 5개를 바로 아래 「Commit Messages (Phase 3 — quant)」에 옮긴다. **이 계획서 맨 끝 「Commit Messages (Final candidates)」에 넣지 않는다** — 그 절은 Done 직전 마지막 커밋용이고, 거기 후보가 들어가면 계획서 훅이 미완료 체크박스와 함께 턴 종료를 막는다. 커밋은 사용자가 한다

#### Commit Messages (Phase 3 — quant)

1. 데이터 / 시세 받기 · 합성을 quant-data 로 이관
2. 데이터 / 받기 · 합성 코드 삭제와 quant-data 내보내기 사본으로 전환
3. 데이터 / quant-data 가 내보낸 합성 시세 8종 수신과 파일 이름 `_synthetic.csv` 로 변경
4. 데이터 / 받기 · 합성 · 검증 표의 quant-data 이관과 yfinance 의존성 · 문서 정리
5. 데이터 / 시세 관리를 한 저장소로 모으는 quant-data 분리 — 결과 수치 차이 0, 경로 필드만 변경

#### Commit Messages (Phase 3 — quant-data)

1. 문서 / 자릿수 예외 · 합성 소개 · 미룬 지적 대기열 추가
2. 문서 / quant 에서 옮긴 미룬 지적 2건과 전역 4자리 규칙의 예외 추가
3. 문서 / 계획서의 인계 · quant 커밋 준비 기록과 저장소 문서 보강
4. 문서 / 시세 · 월별 금리 6자리 예외, README 합성 소개, 미룬 지적 파일 신설과 계획서 진행 기록 갱신
5. 문서 / quant 에서 지운 규칙 · 지적을 잃지 않게 quant-data 로 이전

---

### Phase 4 — verify-lab 몫 첫 판

**작업 내용**:

- [ ] 착수 전 측정: verify-lab 의 국내 원본가 9종 전 기간에 「원본가 하루 변화 ↔ KRX 공식 등락률」 대조를 돌려 걸리는 날 전부를 진행 로그에 남긴다(`/impl-plan` 「글자 규칙이 막거나 …」 — 멈추는 판정이라 먼저 잰다). 공식 등락률의 표기 자릿수도 확인한다. 탈출구는 국내 분할 기록 파일 · 패스 목록
- [ ] 착수 전 측정(Q31): 금 ↔ IAU, 장기채 ↔ 장기국채 ETF 후보의 짝 차이를 2016년 이후로 잰다 — 다른 짝(SPY ↔ S&P500 최대 1.04%p 등)만큼 촘촘하면 짝으로 넣고, 아니면 종목 자체 하루 변동 범위 + 패스 목록으로 간다. 결과를 진행 로그에, 결정은 사용자에게 확인
- [ ] 미국 ETF 20종 원본가 · 수정주가(한 응답), GSPC · IXIC · 다우 지수, 국내 원본가 9종 · 지수 4종 · NAV 2종, Bitstamp · Coin Metrics(두 출처 대조)를 받는다
- [ ] 국내 수정주가 9종을 만들고(C-2) KRX 수정주가 구간과 대조해 판 요약에 적는다
- [ ] verify-lab 기존 파일과 대조한다(값은 바꾸지 않음 — 기간 · 다른 행 · 자릿수 차이를 진행 로그에)

**Validation**:

- [ ] 갱신 명령이 종료 코드 0 으로 끝나고 판 요약에 모든 자료의 기간이 있다
- [ ] 국내 수정주가 대조 결과가 착수 전 측정(069500 2일 · 229200 2일 · 261240 0일 · 261250 1일)과 같은 모양이다

---

### Phase 5(마지막) — 문서 정리 및 최종 검증

**작업 내용**

> 🔴 **체크박스와 상태를 먼저 확정하고, `/commit` 은 맨 마지막에** — 이유는 `/impl-plan` 「5) Commit Messages」.

- [ ] 합성 문서를 나눈다(Q15) — quant 에 남길 백테스트 몫의 문서 이름 · 자리는 사용자에게 확인. 가리키는 69줄을 고친다
- [ ] quant-data 문서: 루트 `CLAUDE.md`(판정 원칙 · 갱신 방식 표의 자리 · 비정상 처리 절차 · AI 가 `--exclude` · `--accept` · 국내 분할 기록을 정하지 않는다 · 패스 목록은 AI 도 적되 근거를 같은 줄에 남기고 보고한다 · KRX 아이디가 표준출력에 찍힘) · `docs/COMMANDS.md` · `README.md` · `docs/research/`(결정 기록 · 착수 전 측정 — 근거 승격)
- [ ] quant 문서: Scope 의 목록. `docs/COMMANDS.md` 변경 있음
- [ ] 자동 포맷 적용 — 두 저장소(`poetry run black .`)
- [ ] 변경 기능 및 전체 플로우 최종 검증 — 갱신(고정 자료 미수신 확인) → 내보내기 → quant 러너
- [ ] Validation 절에 `/code-review` 와 품질 검증 **실행 결과**를 적는다
- [ ] DoD 체크리스트 최종 업데이트 및 체크 완료
- [ ] 전체 Phase 체크리스트 최종 업데이트 및 상태 확정
- [ ] 🔴 **마지막에 `/commit` 을 실행하고 그 후보를 «이 계획서» 의 `#### Commit Messages` 절에 옮긴다** —
      대화에만 내면 그 절이 빈 채로 남는다. **커밋은 사용자가 한다 — 후보만 낸다**

**Validation**:

> 순서는 `/code-review` → 품질 검증이다. 고칠 것 · 회차 상한 · 수정분 검증은 `/impl-plan` 의 `review.md` 가 정한다.

- [ ] `/code-review xhigh` **1회차** (발견 \_\_건 — 버그 \_\_ [무거움 \_\_ · 가벼움 \_\_] · 그 외 \_\_ · 조치: \_\_)
- [ ] 수정분 검증 (수정 \_\_건 · 발견 \_\_건 — 무거움 \_\_ · 조치: \_\_ — 마지막 회차에 고친 것이 없으면 「해당 없음」)
- [ ] `poetry run python validate_project.py` — quant-data (passed=\_\_, failed=\_\_, skipped=\_\_)
- [ ] `poetry run python validate_project.py` — quant (passed=\_\_, failed=\_\_, skipped=\_\_)

#### Commit Messages (Final candidates) — 5개 중 1개 선택

> **Done 직전에 `/commit` 을 실행해 이 절을 채운다. 그전에는 비워 둔다** — 추측으로 적은 줄은 그대로 나간다.

- [ ] (미작성 — `/commit` 을 실행하고 후보 5개를 **이 자리에** 번호 붙은 줄로 옮긴 뒤 이 줄을 지운다)

## 7) 리스크(Risks)

- **옮기다 생긴 미세 차이** — 합성 · 결과가 마지막 자리에서 달라질 수 있다 → Phase 2 · 3 의 대조가 「차이 0」을 기준으로 잡는다. 차이가 나면 원인을 찾기 전에 다음 Phase 로 가지 않는다
- **경로 필드 변화** — 파일 이름을 바꿔 결과의 경로 필드가 달라진다(의도된 차이). 대조는 수치 필드와 경로 필드를 나눠 센다
- **국내 분할 감지는 멈추는 판정** — 실제 산출물로 먼저 잰다(Phase 4 첫 항목). 오탐이면 국내 분할 기록 파일 · 진행 로그로 탈출
- **AI 가 패스 목록을 적어 진짜 오류를 덮을 수 있다**(Q29 — AI 작성 허용) → 근거(짝 지수의 그날 변동 · 함께 넘은 종목)가 있을 때만 적고 근거를 같은 줄에 남긴다. 추가할 때마다 보고하고, 데이터 저장소 commit 은 사용자가 하므로 그 diff 가 검토 자리다
- **짝이 같은 출처(야후)다** — 미국 짝 대조는 야후 안의 두 시세를 견주는 것이라 야후가 두 시세를 같이 틀리면 못 잡는다. 독립된 두 번째 미국 출처는 1단계 범위 밖(미확인)
- **KRX 로그인 아이디가 표준출력에 찍힌다**(verify-lab `collect_pykrx.py` · quant-notify 실측) — 로컬 실행이라 공개 로그는 없다. 실행 로그를 문서 · 커밋에 붙일 때 그 줄을 뺀다
- **야후 조회 한도(429)** — Phase 4 는 받을 것이 많다. 받기 실패는 그 자리에서 멈추고 아무것도 쓰지 않는다 → 시간을 두고 다시, 또는 사용자가 `--exclude`
- **계획서를 quant-data 로 옮긴 뒤 quant 를 고칠 때** — 계획서 훅은 작업 디렉터리 기준이라 quant 에서는 이 계획서를 보지 못하고 확인창을 띄울 수 있다. 그때 이 계획서 이름을 대고 진행한다
- **다른 저장소의 규칙이 자동으로 실리지 않는다**(전역 「하네스 동작」) — quant-data 세션에서 quant 를 고칠 때 quant 루트와 해당 폴더 `CLAUDE.md` 를 직접 연다

## 8) 메모(Notes)

### 다른 세션에서 이어갈 때

1. 작업 디렉터리를 이 계획서가 있는 저장소로 연다 — Phase 0 의 이관 전에는 quant, 뒤에는 quant-data
2. 이 계획서 전체를 읽는다. 「결정 기록」은 사용자가 정한 것이라 다시 묻지 않는다
3. 진행 로그의 마지막 줄과 첫 미완료 체크박스에서 시작한다
4. 다른 저장소의 파일을 고치기 전에 그 저장소의 루트 · 해당 폴더 `CLAUDE.md` 를 `Read` 로 연다
5. 착수 전 측정 스크립트(scratchpad)는 사라졌을 수 있다 — 숫자는 3장 「착수 전 측정」이 정본이다
6. 아래 「인계」를 읽고 그 「다음 할 일」부터 — 인계는 진행 로그를 대신하지 않는다. 근거 · 수치는 진행 로그가 정본이다

### 인계 (2026-11-11 14:24 기준)

**세션** — Claude Code 세션 ID `4fd9cbe7-248b-477f-8160-d904ca00d435` (작업 디렉터리 `/Users/yubeen/Workspace/quant-data`). 그 세션의 scratchpad 는 `/private/tmp/claude-501/-Users-yubeen-Workspace-quant-data/4fd9cbe7-248b-477f-8160-d904ca00d435/scratchpad/` — 세션이 끝나면 사라질 수 있고, 남길 숫자는 모두 진행 로그에 옮겼다. 거기 남은 것: `quant_results_baseline/`(quant HEAD `0c74948` 의 `storage/results` 895개) · `compare_results.py`(결과 대조) · `apptest_dashboards.py`(대시보드 4종) · `quant_head/`(quant HEAD 를 `git archive` 로 푼 사본) · `quant_poetry.lock.before` · 러너 로그

**진행 상황**

| Phase | 상태 | 한 줄 |
|---|---|---|
| 0 뼈대 | 끝 | 저장소 · 공통 스택 · `.venv` · `.env`(KRX 계정) |
| 1 레드 | 끝 | 테스트 파일 21개(`tests/`) — quant 이관 테스트 + 새 규칙 테스트 |
| 2 그린 | 끝 | `src/quant_data/` 파이썬 파일 26개(`__init__.py` 4 포함) · `scripts/update.py` · `scripts/export.py` · 첫 판(받지 않음) — 합성 8종이 quant 와 바이트 같음 |
| 3 quant 전환 | 전환 끝 · **커밋 준비 남음** | quant 가 합성 8종만 내보내기로 받음, 결과 수치 차이 0 · 경로는 이름 변경분 61개 · 대시보드 4종 예외 0. 커밋 전 검증 · 커밋 메시지 후보가 남음(Phase 3 끝 체크박스) |
| 4 verify-lab 몫 첫 판 | **안 함** | 다음 할 일 |
| 5 문서 · 최종 검증 | 안 함 | Phase 4 뒤 |

**작업 트리**

- quant-data: 첫 커밋 `ae0e12c init`(99개 파일 — storage 36 · 테스트 21 포함). 그 뒤 이 계획서만 바뀜
- quant: **커밋 전** — 삭제 58 · 수정 43(결과 31 포함) · 새 파일 10(`storage/stock` 의 합성 8 · `quant_data_files.txt` · `quant_data_edition.json`). 결과 diff 의 고원 CSV 12개는 11-08 시세 반영분이다(진행 로그 13:52 — 옮기다 생긴 차이 아님)
- quant 의 `storage/stock/quant_data_edition.json` 은 quant-data 커밋 전에 내보내 「커밋: null · 커밋 안 된 변경 9」다 → quant 를 커밋하기 전에 quant-data 에서 `python3 scripts/export.py --to ../quant/storage/stock` 을 다시 돌리면 `ae0e12c` 와 「커밋 안 된 변경 없음」이 적힌다(그사이 quant-data 데이터를 고치지 않았다면 시세 파일은 그대로)

**결정된 사항** — 3장 「결정 기록」 표 Q1 ~ Q36 이 정본이다(다시 묻지 않는다). 이 세션에서 더한 것: Q32 검증 표 ② ③ 굳힘 · Q33 파일 이름 `_max` 뺌 · Q34 새 파일은 미국 짝 대조 안 함 · Q35 금리 · Perth · 환율 받기 코드 옮겨 둠 · Q36 월별 금리 덧붙이기, 그리고 quant `yfinance` 의존성 제거(사용자 2026-11-11 「빼줘」). 함께 낸 가정 다섯(진행 로그 12:17)과 테스트로 굳힌 설계 판단(진행 로그 12:44)에는 사용자 이의가 없었다

**미결 사항**

- **Q31 금 · 장기채의 짝** — Phase 4 착수 전에 금 ↔ IAU, 장기채 ↔ 다른 장기국채 ETF(후보 미정 — 고를 때 사용자에게 보인다)의 2016년 이후 짝 차이를 재고, 짝으로 넣을지 「종목 자체 하루 변동 범위 + 패스 목록」으로 갈지 **사용자 결정**. 그전까지 GLD · TLT 는 하루 변동 50%(`new_days.TEMP_DAILY_MOVE_LIMIT`)
- **국내 공식 등락률의 표기 자릿수** — `new_days.OFFICIAL_RATE_DECIMALS = 2` 는 자리만 잡아 둔 값이다. Phase 4 첫 측정(국내 9종 전 기간의 원본가 하루 변화 ↔ 공식 등락률)에서 실제 자릿수를 보고 고친다. 걸린 날 전부를 진행 로그에 남기고, 분할 · 병합으로 보이는 날은 사람이 공시를 확인해 `storage/records/kr_actions.csv` 에 적는다(AI 는 적지 않는다)
- **국내 · 코인을 갱신에 잇는 코드가 아직 없다** — 함수는 있다(`domestic.build_kr_adjusted` · `krx_mismatch_days` · `load_kr_actions`, `new_days.check_kr_two_sources` · `check_kr_official_rate`). 없는 것: KRX · Bitstamp · Coin Metrics 받기(`sources/`), `catalog.Kind` 의 국내 · 코인 종류, `update` 가 국내 자료를 판정(Q34 — 새 파일이어도 국내 두 검사는 전 기간)하고 C-2 를 가공하는 연결, 판 요약의 「대조 어긋난 날」 열쇠, KRX 원본가 파일에 공식 등락률 열(`constants.COL_CHANGE_RATE`)을 남길지. verify-lab 수집기의 실측 함정(KRX 로그인 순서 · 국내 휴장일 0 가격 행 · 지수 고가 · 저가가 종가로 채워진 옛 구간 · `uint32` 언더플로)은 3장 「기존 함수 재사용」대로 옮긴다
- **verify-lab 몫 자료가 갱신 방식 표에 없다** — `catalog.CATALOG` 는 quant 몫과 짝 지수 둘뿐이다. 3장 「자료별 갱신 방식」의 verify-lab 몫(DIA · 다우 지수 · 나스닥 종합 · 레버리지 · 인버스 11종 · 국내 ETF 9 · 지수 4 · NAV 2 · Bitstamp · Coin Metrics 3)을 더한다. 레버리지 · 인버스 11종은 분할이 잦아(SQQQ 8건) 첫 판 뒤 고정이다
- **첫 갱신이 quant 몫도 받는다** — 인자 없는 `update.py` 는 다시 받음 · 덧붙이기 자료 전부를 받으므로 SPY 등 8종의 원본가 파일이 처음 생기고 수정주가가 판정된다(기준일까지 새 날짜가 붙음). quant 결과를 다시 돌릴지는 그때 사용자가 정한다
- **quant 문서가 낡았다(Phase 5)** — 지운 스크립트 · 패키지 · 옛 이름을 가리키는 줄: `_synthetic_max` 126 · `qbt/tqqq` 82 · `download_data` 59 · `합성_시세_연장` 58 · `scripts/data` 43 · `generate_synthetic` 38 · `storage/etc` 21 · `proxy_validation` 19 (진행 로그 13:34 무렵 잰 수, 파일 중복 포함). 특히 quant `docs/COMMANDS.md` 워크플로우 1 · 「시세를 다시 받은 뒤 다시 돌리는 순서」 · 「데이터 다운로드 옵션」, `src/qbt/utils/CLAUDE.md` 의 지운 모듈 줄, `docs/DEFERRED_FINDINGS.md` 의 `download_data.py --end` 지적(지운 코드에 대한 것 — quant-data 로 옮길지 지울지 정한다)
- **quant 가상환경에서 더 지운 패키지** — `poetry sync` 가 잠금 파일 밖 패키지까지 지웠다(진행 로그 13:52). quant 코드에는 영향이 없다. 사용자가 그 가상환경에서 손으로 쓰던 것이 있으면 다시 설치한다
- **품질 검증을 아직 돌리지 않았다** — quant-data · quant 모두 Ruff · PyRight · 전체 pytest 는 Phase 5 에서. 파일 단위 pytest 만 돌렸다(quant-data 전부 통과 · quant 고친 5파일 86개 통과)

**먼저 할 일 — quant 커밋 준비** (Phase 3 끝의 「quant 커밋 준비」 체크박스가 정본이다. 6장 Phases 의 첫 미완료 체크박스가 여기다 — 1장 목표 · 4장 완료 조건의 체크박스는 Done 때 닫는 칸이라 시작점이 아니다)

1. 사용자에게 결정 두 가지를 한 라운드로 묻는다 — quant 문서를 이 커밋에 함께 고칠지 · 커밋 전 `/code-review` 를 할지와 수준
2. 다시 내보내기(커밋 번호가 판 요약에 적히게) → quant `black` → quant `validate_project.py`(실패는 고치고 진행 로그에) → (정했으면) `/code-review`
3. quant 변경을 대상으로 `/commit` → 후보를 Phase 3 의 「Commit Messages (Phase 3 — quant)」에 옮긴다 — 최종 후보 절에 넣지 않는다. 커밋은 사용자가 한다
4. 이 계획서의 변경(인계 · 진행 로그)은 quant-data 쪽 커밋 대상이다 — 그것도 사용자가 한다

**다음 할 일** (Phase 4 — quant 커밋 준비 뒤)

1. verify-lab `CLAUDE.md` · `src/verify_lab/CLAUDE.md` · `reference/pykrx_실측기록.md` 8.2 · `src/verify_lab/data/*_collector.py` 를 `Read` 로 연다
2. 착수 전 측정 ① — verify-lab 의 국내 원본가 9종(`storage/market/{코드}_max.csv`)에 KRX 공식 등락률을 받아 전 기간 대조: 걸린 날 전부 · 공식 등락률 자릿수 → 진행 로그. 측정 코드는 scratchpad(KRX 로그인 시 아이디가 표준출력에 찍힘 — 로그를 옮길 때 그 줄을 뺀다)
3. 착수 전 측정 ② — Q31 짝 후보의 2016년 이후 짝 차이 → 진행 로그 → **사용자에게 결정 질문**
4. 측정 결과로 국내 · 코인 받기와 갱신 연결을 테스트 먼저(Phase 1 방식) 구현하고, verify-lab 몫을 갱신 방식 표에 더한다
5. 갱신을 돌려 verify-lab 몫 첫 판을 받고, 국내 수정주가 대조 · verify-lab 기존 파일과의 대조를 진행 로그에 남긴다(Phase 4 Validation)

### 2단계(국내 합성 연구)로 넘길 것

- 1배: 코스피200(1990-01-03 ~) · 코스닥150(2010-01-04 ~) 으로 상장 전 채우기 — 지수에 배당이 빠져 1배 ETF 보다 연 +2.25%p · +0.56%p 낮다(착수 전 측정). 배당을 넣을 출처(코스피200 배당 포함 지수 등)는 미확인
- 레버리지 · 인버스: 선물로 운용 — 비용 모형(금리 · 배당 · 보수)이 필요하다. 재료: verify-lab 의 CD91(1995-01-03 ~, 수집기 지워짐) · 「선물_대_레버리지_ETF」 조사(CD91 가정 시 선물 쪽 연 +1.8 ~ +3.2%p). 1990 ~ 1994 금리 출처 필요, 코스피200 선물은 1996-05 시작
- C-2 의 분배 기록 어긋남(069500 2022-07-28 · 10-27 등)을 운용사 분배 공시로 판정

### 진행 로그 (KST)

- 2026-11-11 10:58: 계획서 작성(🟡 Draft) — 2026-11-10 ~ 11 grilling 의 결정 Q1 ~ Q25 와 착수 전 측정을 담음. 사용자 승인 대기
- 2026-11-11 11:17: 사용자 질문(「지금 단순히 오류검증을 퍼센트로 하고 있어? 어떤 근거로 … 수치는 어떻게 정해진거야?」)에서 새로 붙는 날의 검사가 하루 50% 하나뿐이고 그 숫자의 근거 기록이 없음을 확인 → 결정 Q26 ~ Q31 추가(사용자 「언급 없는 것은 추천대로 · Q29 추천대로 하되 AI 도 패스목록을 작성할 수 있도록 허용」). 고친 곳: 결정 기록 표(Q20 예외 · Q26 ~ Q31) · 자료별 갱신 방식(나스닥100 지수 고정 → 덧붙이기, 다우 지수 추가) · 판정 규칙 ② 신설 · 착수 전 측정(50% 의 여유 · 짝 차이 · 종목 자체 하루 변동) · Phase 1 · Phase 4 · DoD · Scope · Risks. 사용자 승인 대기
- 2026-11-11 11:40: 사용자 승인(「진행」) → 🔄 In Progress. Phase 0 착수 — `/Users/yubeen/Workspace/quant-data` 없음 확인, 사용자의 저장소 생성 · 받기와 패키지 이름 답을 기다림. 이웃 패키지 이름: quant `qbt` · verify-lab `verify_lab` · quant-notify `notify` · research-lab `research_lab`
- 2026-11-11 11:45: 사용자가 `gh repo create quant-data --public --clone` 으로 `ingbeen/quant-data` 를 만들어 받음(커밋 없음). 패키지 이름 `quant_data`(사용자 「추천대로」). 계획서를 quant `docs/plans/` 에서 이 저장소로 옮김(`mv` — quant 쪽은 삭제로 보인다, 커밋은 사용자). 뼈대 작성: `pyproject.toml`(의존성은 verify-lab 구성 — pandas · yfinance · pykrx · python-dotenv, Ruff · Black 은 quant 의 최신 설정) · `poetry.toml` · `pyrightconfig.json`(verify-lab 의 include 에 quant 의 `reportUnnecessaryTypeIgnoreComment: error`) · `pytest.ini`(quant 것 + `norecursedirs = storage .venv`) · `.gitignore` · `.python-version`(3.12.13) · `.vscode/settings.json`(무시 대상) · `.claude/plan-config.json`(이웃과 같은 값) · `validate_project.py`(quant 것, 커버리지 경로만) · `src/quant_data/__init__.py` · `CLAUDE.md` · `README.md` · `docs/COMMANDS.md`. 넣지 않은 것: freezegun(쓸 테스트가 생기면) · 테스트 헬퍼 isort 설정 · `.claude/settings.json`(quant 처럼 없음). 의존성 설치는 사용자 승인 대기
- 2026-11-11 11:49: 사용자 승인(「승인」) → 의존성 설치. quant · verify-lab 의 잠긴 버전이 서로 같아(pandas 2.3.3 · numpy 2.5.2 · yfinance 0.2.66 등) Phase 2 의 「합성 값이 같다」 대조에서 라이브러리 차이를 빼려고 verify-lab `poetry.lock` 을 시작점으로 복사 → `env -u VIRTUAL_ENV poetry env use ~/.pyenv/versions/3.12.13/bin/python` → `poetry lock` → `poetry install`. 결과: `.venv/bin/python` 에서 `import quant_data` 성공, 잠긴 버전 11종(pandas · numpy · yfinance · pykrx · python-dotenv · black · ruff · pyright · pytest · pytest-cov · pandas-stubs)이 verify-lab 과 모두 같음, scipy · freezegun · plotly 는 잠금에서 빠짐(0). Phase 0 에서 남은 것은 `.env` 의 KRX 계정(사용자 — Phase 4 전까지)
- 2026-11-11 11:56: 사용자가 `.env` 를 만듦 — `KRX_ID` · `KRX_PW` 가 각각 채워진 줄 1(`grep -c '^KRX_ID=.\+'`, 값은 보지 않음 — verify-lab `krx_credentials.py` 와 같은 이름), `.gitignore` 26행이 무시하고 `git status` 에 나오지 않음. **Phase 0 완료.** 다음 세션은 quant-data 를 작업 폴더로 열어 Phase 1 부터
- 2026-11-11 12:07: Phase 1 착수 — 이관 대상 소스(quant `stock_downloader` · `price_revision` · `data_loader` · `proxy_series` · `gold_proxy` · `tqqq/*` · `scripts/data/*`)와 이관 대상 테스트 12파일 259개를 읽음(`gold_proxy` 20 · `price_revision` 29 · `proxy_comparison` 33 · `proxy_series` 27 · `stock_downloader` 32 · `rounding_policy` 1 · `tqqq_data_loader` 33 · `tqqq_leveraged_comparison` 21 · `tqqq_simulation_core` 21 · `tqqq_simulation_cost_model` 29 · `tqqq_simulation_outputs` 4 · `tqqq_synthetic` 9). 결정 기록 때문에 기대가 뒤집히는 테스트: `test_price_revision` 의 분할 기록 → 설명되는 변화(Q23), `test_stock_downloader` 의 급등락 저장 거부(Q26) · 터미널 y/N `TestConfirmOverwrites` 4(Q16) · 받자마자 저장(Q17). 확인한 사실 셋 — ① Q20(상장 전까지만 시뮬레이션)이면 검증 ② `tracking.csv` 와 ③ `fund_years.csv` 의 레버리지 4종 행이 상장 뒤 시뮬레이션을 써서 다시 만들 수 없다(quant 에서 `proxy_validation` 을 읽는 코드는 생성 스크립트 밖 0건) ② quant 결과 19개 파일의 시세 경로 61개가 전부 `storage/stock/*_synthetic_max.csv` ③ verify-lab `pykrx_collector` 는 KRX 공식 등락률을 저장하지 않는다(`KRX_COLUMN_MAP` 이 버림). 테스트가 인터페이스를 고정하므로 쓰기 전에 사용자 결정을 기다림 — 검증 표 ② ③ 처리 · 파일 이름의 `_max` · 새 파일에 새로 붙는 날 검사를 거는가
- 2026-11-11 12:17: 사용자 답 → 결정 기록 Q32 ~ Q35 추가. 함께 낸 가정 다섯(패키지 배치 `constants` · `logger` · `cli` · `prices` · `revision` · `new_days` · `catalog` · `sources/` · `synthetic/` · `domestic` · `update` · `edition` · `export` / 저장 폴더 `storage/prices` · `series` · `records` · `validation` · `edition.json` / `--accept` 는 판정 규칙 ① 만 넘기고 판정 규칙 ② 는 패스 목록 · 국내 분할 기록으로만, `--exclude` 는 그 종목 판정 전부를 건너뜀 / 내보내기는 `--to <받는 폴더>` 의 `quant_data_files.txt` 를 읽고 같은 폴더에 `quant_data_edition.json` 을 쓰며 「커밋 안 된 변경」은 내보낸 파일로 잼 / 이관 목록 밖이지만 quant `test_data_loader` 의 읽기 · 검사 부분과 `test_logger` · `test_cli_helpers` 도 옮김)에는 이의 없음. 받기 코드를 옮기는 질문 중 사용자 「신규로 올라온 금리는 적용해줘야돼」 — Q20 의 「금리 고정」과 갈림. 금리를 덧붙이기로 바꾸는 범위(호주달러 환율 · VFINX 등 다른 고정 자료에도 같은 원리를 거는가)를 확인 대기
- 2026-11-11 12:44: 사용자 「추천대로 진행」 → 결정 기록 Q36 추가, 자료별 갱신 방식 표에서 월별 금리를 고정 → 덧붙이기로 옮김. **Phase 1 완료(레드)** — `tests/` 에 테스트 파일 20개 · `def test_` 372개(파라미터 펼치기 전, `test_cli` 의 중첩 함수 1 포함)와 `conftest.py`(`sample_stock_df` · `sample_ffr_df`). 이웃(verify-lab · quant-notify)처럼 `tests/` 한 층. 레드 확인: `py_compile` 20개 통과(문법 오류 0), 파일마다 `pytest --collect-only` 가 모두 `ModuleNotFoundError: quant_data.constants`(conftest 첫 import)에서 멈춤. 테스트가 요구하는 모듈 20개 — `constants` · `logger` · `cli` · `prices` · `revision` · `new_days` · `catalog` · `domestic` · `update` · `edition` · `export` · `sources.yahoo` · `synthetic.{proxy_series, proxy_comparison, gold_proxy}` · `leveraged.{constants, monthly_data, simulation, synthetic, comparison}`(가정 1 에서 바꾼 것: 레버리지를 `synthetic/` 아래가 아니라 `quant_data.leveraged` 로 — `synthetic.leveraged.synthetic` 이름 겹침을 피함. 금 원본 받기는 quant 처럼 `gold_proxy` 한 모듈에). 옮긴 것: `gold_proxy` · `proxy_series` · `proxy_comparison` · `tqqq_simulation_core` · `tqqq_simulation_cost_model` · `logger` · `cli_helpers` 는 import 만 바꿈, `tqqq_data_loader`(→ `test_leveraged_monthly_data` — FRED 받기 5개를 받기 · 저장 · 덧붙이기 판정으로 나눔, Q17 · Q36), `tqqq_synthetic`(→ `save_leveraged_synthetics` 를 쓰지 않는 `build_leveraged_synthetics` 로, 시뮬레이션은 이음매 날까지 — 상장 뒤 금리 없이 만들어지고 전 기간 시뮬레이션과 값이 정확히 같음을 새로 고정, Q20), `tqqq_leveraged_comparison`(Q32 로 12개 뺌, 9개), `tqqq_simulation_outputs`(→ `test_leveraged_targets`, 파일 이름 Q33), `price_revision`(→ `test_revision` — 분할 기록이 맞아도 비정상 · 원인 줄 「분할로 보이는 변화: 날짜 · 비율 (야후 기록)」 · `split_changes` 필드, 원본가는 배당으로 설명하지 않는 `explain_dividends`, 원인 블록의 y / N → `--accept` / `--exclude` 와 분할 안내 줄), `stock_downloader`(→ `test_yahoo` · `test_prices` — 급등락 저장 거부 · `TestConfirmOverwrites` 4 · 받자마자 저장 없앰, `history(period="max", auto_adjust=False, raise_errors=True)` 고정), `rounding_policy`(→ 시세 6자리 `ROUND_INPUT_PRICE`), `data_loader` 의 읽기 7개. 옮기지 않은 quant 테스트: `data_loader` 의 합성-실물 끝날 2 · `extract_overlap_period` 2 · `load_signal_trade_pair` 3 · `ticker_from_stock_path` 2(백테스트 쪽 계약 — quant 에 남음). 새로 쓴 것: `test_catalog`(갱신 방식 · 짝 · 배율 · 하루 변동 한도 · 파일 경로), `test_new_days`, `test_domestic`, `test_update`, `test_export`. 테스트로 굳힌 설계 판단(다음 세션 구현 기준) — 받기 · 합성은 파일을 쓰지 않고 `run_update` 가 판정 · 가공이 모두 끝난 뒤 한꺼번에 씀 / `--exclude` 종목은 받지도 않음 / `--exclude` · `--accept` 에 표 밖 이름 · 고정 자료 · 두 옵션 같은 이름이면 받기 전에 `ValueError` / 고정 자료 파일이 없으면 받기 전에 `ValueError` / 짝 시세에 그날(또는 전날)이 없으면 짝 차이 실패로 보임 / 공식 등락률 경계는 `OFFICIAL_RATE_DECIMALS` 의 반 단위(값은 Phase 4 측정에서 확인) / C-2 ↔ KRX 수정주가 대조는 겹치는 날끼리 하루 수익률을 견주고 KRX 원 단위 반올림 구간으로 설명되는지 봄 / 패스 목록 `storage/records/pass_list.csv` · 국내 분할 기록 `storage/records/kr_actions.csv` 는 한글 머리 BOM CSV, 빈 사유 · 근거 · 중복 · 파일 없음은 멈춤 / 판 요약 `storage/edition.json` 은 파일(저장소 루트 기준 posix 경로)마다 종목 · 첫날 · 끝날 · 행 수 · 상태(새로 · 흔들림뿐 · 설명되는 변화 · 받아들임 · 제외 · 고정 · 가공) · 분배 기록 첫날 / 내보내기 목록 한 줄은 storage 기준 경로(`prices/QQQ_synthetic.csv`)이고 받는 폴더에는 이름만으로 복사, storage 밖 경로 · 같은 이름 두 줄은 멈춤. 다음 세션은 Phase 2(구현으로 그린)부터
- 2026-11-11 13:24: 사용자 「진행」 → **Phase 2 완료(그린)**. 소스 `src/quant_data/` — 그대로 옮김(import 만): `logger` · `cli` · `synthetic/{proxy_series, proxy_comparison, gold_proxy}` · `leveraged/simulation` / 고쳐 옮김: `revision`(분할 · 원본가 · 원인 블록) · `leveraged/{constants, monthly_data, synthetic, comparison}` · `sources/yahoo` / 새로: `constants` · `prices` · `record_files`(패스 목록 · 국내 분할 기록의 공통 읽기 — 두 모듈이 비공개 함수를 나눠 쓰지 않게) · `new_days` · `domestic` · `catalog` · `edition` · `update` · `products`(quant `generate_synthetic.py` 의 계산 — 콘솔 「직전 저장값과 나란히」 출력은 옮기지 않음: 검증 표를 이 저장소가 git 으로 추적해 diff 가 같은 일을 함) · `export`(표준 라이브러리만). 스크립트 `scripts/update.py`(`--exclude` · `--accept` · `--end` · `--no-fetch` — 받지 않고 지금 파일로 가공 · 판 요약만, 첫 판에 필요해 더함. 기준일은 판 요약의 것, 판 요약이 없으면 `--end`) · `scripts/export.py`(`runpy` 로 모듈 파일을 실행 — 패키지 설치 없이 아무 `python3`). `docs/COMMANDS.md` 에 갱신 · 내보내기 추가. 테스트: 파일마다 pytest 로 Phase 1 테스트 모두 통과(첫 실행). 변형 확인 5건 — Q17 멈추면 안 씀(7 실패) · Q23 분할 비정상(3) · Q20 상장일까지(2) · Q16 제외는 받지 않음(2)은 잡힘, **원본가 판정에 `explain_dividends` 를 넘기는 연결은 67개 모두 통과(빈자리)** → `TestRawFileJudgement` 를 더해 그 변형에서 1 실패로 막음. 함께 더한 테스트: `--no-fetch` 2 · 표 자체의 검사 2 · 멈춤 보고 1 · C-2 마지막 행 뒤 분배 1 · `test_products`(1배 대상 표 · ④ 대상 표) 2. 첫 판: quant 의 시세 15(실물 8 · 고정 6 → `*_adjusted.csv`, `^NDX_max` → `^NDX_raw.csv`) · `storage/etc` 4 → `storage/series/` · 굳힐 검증 표 3(`tracking` · `funds` · `fund_years`) → `storage/validation/` 을 복사(22개 `cmp` 다름 0), 기록 파일 둘은 머리만(BOM). `env -u VIRTUAL_ENV poetry run python scripts/update.py --no-fetch --end 2026-11-06` → 종료 코드 0 · 3초 · 12개 파일. **대조** — 합성 8종 바이트 같음, 행 수 QQQ 10,356 · SPY 11,809 · TLT 10,197 · GLD 11,612 · TQQQ 10,356 · QLD 10,356 · SSO 11,809 · UPRO 11,809, 날짜 · 가격 · 거래량 다른 값 모두 0 / `years.csv` · `assumptions.csv` 바이트 같음 / `summary.csv` 6행 수치 열 같음, 다른 칸은 「대용 파일」 4 · 「실물 파일」 5(예 `^NDX_max.csv` → `^NDX_raw.csv` · `QQQ_max.csv` → `QQQ_adjusted.csv` — Q33 이름 변경분). 판 요약 27개 파일(받지 않음 10 · 고정 9 · 가공 8), 기준일 2026-11-06. 품질 검증(Ruff · PyRight · 전체)은 마지막 Phase 에서
- 2026-11-11 13:34: 사용자 「이어서 진행」 → Phase 3 착수. quant 규칙 문서(`docs/MEMORY.md` · `docs/CLAUDE.md` · `docs/COMMANDS.md` · `src/qbt/backtest/CLAUDE.md`)를 엶. 기준: quant HEAD `0c74948` 깨끗한 상태의 `storage/results` 895개(209M)를 scratchpad `quant_results_baseline/` 로 복사. 남는 quant 코드가 쓰는 시세 경로 상수는 합성 8종뿐(실물 · 고정 · 금 원본 경로는 남는 코드 0건) → quant `storage/stock/quant_data_files.txt` 에 합성 8개만. quant 고침: `common_constants.py`(합성 경로 → `*_synthetic.csv`, 이관 경로 상수 · `ETC_DIR` · `PROXY_VALIDATION_RESULTS_DIR` · `FRED_DATE_COLUMN` 지움 — 남는 코드 0건) · `utils/data_loader.py`(합성 ↔ 실물 짝 `_synthetic.csv` ↔ `_adjusted.csv`, 안내 문구를 quant-data 갱신 · 내보내기로 — quant 가 합성만 받으므로 지금은 짝 실물이 없어 걸리지 않는 검사다) · 테스트 `test_data_loader`(이름 · 안내) · `test_portfolio_configs` 4 · `test_buffer_zone` 3 · `test_buy_and_hold` 3(이름 끝) · **`test_integration` 의 `TestTQQQSimulationWorkflow`(계획서 이관 목록 밖 — 지운 `qbt.tqqq` 를 import, 같은 연결은 quant-data `test_leveraged_synthetic` 이 지킴)를 빼고 백테스트 파이프라인 테스트만 둠** · `conftest.py` 의 `sample_ffr_df` · `sample_expense_df`(이번 삭제로 쓰는 곳 0). 지움 58개(모두 git 추적): `scripts/data/` 2 · `utils` 이관 모듈 5 · `src/qbt/tqqq/` 7 · 이관 테스트 11 · `storage/etc` 4 · `storage/results/proxy_validation` 6 · `storage/stock/*_max.csv` 23. 손대지 않음: 테스트가 임시 폴더에 아무 이름으로 쓰는 `QQQ_max.csv` 같은 글자(이름 규칙과 무관), quant `pyproject.toml` 의 `yfinance`(남는 코드 0건 — 잠금 파일을 바꾸는 일이라 따로 보고). quant 고친 테스트 5파일 86개 통과. 내보내기: `python3 scripts/export.py --to ../quant/storage/stock` → 종료 코드 0, 8개 복사, 판 요약에 커밋 없음 · 커밋 안 된 변경 9개(quant-data 커밋 전), 8종 모두 quant-data 원본 · quant 옛 합성(HEAD)과 바이트 같음. 다른 python3 로도 돌려 봄 — `/usr/bin/python3` 3.9.6 은 본문의 `str | None` 에서 `TypeError` 로 시작도 못 함 · brew 3.14.6 · pyenv 3.12.13 은 성공 → 진입점 `scripts/export.py` 가 3.10 미만이면 안내와 함께 종료 코드 1, COMMANDS 의 「어느 python3 로도」를 「파이썬 3.10 이상」으로 고침. quant 러너 넷(단일 · 워크포워드 · 고원 · 포트폴리오)을 백그라운드로 돌리는 중
- 2026-11-11 13:40: 사용자 「빼줘」(quant 의 `yfinance`) → 러너가 쓰는 가상환경은 그대로 두고 `env -u VIRTUAL_ENV poetry remove yfinance --lock`(Poetry 2.4.1) — `pyproject.toml` 한 줄, `poetry.lock` 68 → 59 패키지(빠짐: `yfinance` 와 그것만 쓰던 `beautifulsoup4` · `cffi` · `curl-cffi` · `frozendict` · `multitasking` · `peewee` · `pycparser` · `soupsieve`, 새로 생김 0, 버전이 바뀐 것 0 — 바꾸기 전 잠금 파일을 scratchpad 에 떠서 대조). 지금 상태를 적는 문서 둘(quant 루트 `CLAUDE.md` 주요 라이브러리 · `README.md` 기술 스택)에서 뺌, 연구 보고서 · 계획서의 언급은 그때의 기록이라 둠. 가상환경에서 지우는 `poetry sync` 는 러너가 끝난 뒤
- 2026-11-11 13:52: **Phase 3 완료.** 러너 넷 모두 종료 코드 0, ERROR · WARNING 줄 0 — 단일 13:33:44 ~ 13:33:52 · 워크포워드 ~ 13:47:41 · 고원 ~ 13:48:33 · 포트폴리오 ~ 13:48:48. **quant `poetry sync` 가 알린 9개보다 더 지움** — 잠금 파일 밖에 있던 가상환경 패키지(보인 출력 끝 14줄에 `pyasn1-modules` · `pyjwt` · `pyluach` · `python-dotenv` · `rich` · `smmap` · `toolz` · `tornado` · `watchdog` 등. 출력 앞부분을 남기지 않아 전체 목록은 다시 볼 수 없음)까지 지웠다. 잠금 파일 밖 패키지를 따지지 않고 `poetry install` 대신 `sync` 를 쓴 실수. 확인: `pip check` 깨진 의존성 없음, 가상환경 59개 = 잠금 파일 59개, quant 코드(`src` · `scripts` · `tests` · `validate_project.py`)가 import 하는 서드파티 6개(`lightweight_charts_v5` · `numpy` · `pandas` · `plotly` · `pytest` · `streamlit`) 모두 설치됨 — 지운 것은 잠금 파일에 없고 quant 코드도 쓰지 않던 것. **결과 대조**(scratchpad `compare_results.py`, 기준 895 ↔ 전환 뒤 889, 빠진 6개는 quant-data 로 옮긴 `proxy_validation`): 바이트 같음 858 · JSON 경로 필드만 다름 61개(19파일 — 모두 `*_synthetic_max.csv` → `*_synthetic.csv`) · 경로 밖 차이 12개 = 고원 CSV 12개(`param_plateau_*` — 예 QQQ ma=50 CAGR 10.46 → 10.33, 거래 52 → 53). 원인 가름: 고원 결과의 마지막 커밋 `58c1110`(2026-11-05)이 시세 갱신 커밋 `243cb1f`(2026-11-08)보다 앞 — quant HEAD 를 `git archive` 로 scratchpad 에 풀어 전환 전 코드 · 전환 전 데이터로 고원을 다시 돌리니 전환 뒤 결과와 16개 파일 모두 바이트 같음 → **옮기다 생긴 차이 0, 커밋된 고원 결과가 낡았던 것**(quant 커밋 diff 의 고원 변경은 11-08 시세 반영분). AppTest(scratchpad `apptest_dashboards.py`) 대시보드 4종 예외 0 · 오류 블록 0. quant 작업 트리: 삭제 58 · 수정 43(결과 31 포함) · 새 파일 10(합성 8 · 목록 · 판 요약). 다음은 Phase 4 — 착수 전 측정 둘(국내 공식 등락률 · Q31 짝 후보)과 Q31 결정 확인이 먼저
- 2026-11-11 14:24: 사용자 「다른 세션에서 이어서 할 수 있도록 인계서 작성」 → 둘 자리를 물음(전역 「인계 문서를 두지 않는다」 · 이 계획서 비목표와 어긋나서) → 사용자 「계획서 8장에 넣는다」. 8장에 「인계」 절(세션 ID · scratchpad · 진행 상황 · 작업 트리 · 결정 · 미결 · 다음 할 일)을 더함. 그사이 사용자가 quant-data 를 커밋함(`ae0e12c init`, 99개 파일), quant 는 커밋 전
- 2026-11-11 14:28: 사용자 「다음 세션에서 quant 쪽 수정분 커밋하기 전 검증과 테스트 · 커밋 메시지 추천도 진행할 수 있게」 → Phase 3 끝에 「quant 커밋 준비」 체크박스 6개와 「Commit Messages (Phase 3 — quant)」 절(`/impl-plan` 「사용자가 중간 커밋 분리를 명시적으로 요청한 경우」)을 더하고, 인계 절에 「먼저 할 일」로 둠 — 다음 세션의 첫 미완료 체크박스가 이것이 된다. 확인한 사실: quant 의 계획서 12개는 모두 ✅ Done 이라 `/commit` 10번(진행 중 계획서의 최종 후보 절 채우기)이 quant 쪽에서 채울 곳이 없다 · quant 커밋 이력은 `기능명 / 요약` 형식이고 quant `CLAUDE.md` 에 따로 정한 커밋 형식은 없다 · quant `plan-config` 의 검증은 `poetry run python validate_project.py`, 포맷은 `poetry run black .`
- 2026-11-11 14:40: 새 세션(작업 디렉터리 quant-data)에서 인계의 「먼저 할 일」부터. 상태 확인 — quant-data HEAD `ae0e12c` · 바뀐 것은 이 계획서뿐, quant 는 삭제 58 · 수정 43 · 새 파일 10(인계와 같음), quant 코드 diff(src · tests · scripts) 34파일 +57 / −10,752. quant 문서의 낡은 줄을 `.md` 만 다시 셈(인계의 수는 `.md` 밖 · 중복 포함 — 예 `_synthetic_max` 126 → `.md` 82): 지금 상태를 말하는 문서 9개(루트 `CLAUDE.md` 9 · `docs/COMMANDS.md` 16 · `src/qbt/utils/CLAUDE.md` 7 · `src/qbt/CLAUDE.md` 5 · `scripts/CLAUDE.md` 3 · `README.md` 2 · `src/qbt/backtest/CLAUDE.md` 1 · `tests/CLAUDE.md` 1 · `docs/DEFERRED_FINDINGS.md` 2건) / 그때의 기록(Done 계획서 12 · `전략_검증_보고서.md` 24줄 — 고치지 않음) / Q15 몫(`합성_시세_연장.md` 와 그것을 가리키는 49줄 — Phase 5). 결정 질문 셋에 사용자 「추천대로 진행」: **① 지금 상태를 말하는 문서 9개를 이번 quant 커밋에 고침**(Q15 는 Phase 5, quant-data 로 옮긴 코드의 규칙 — 추적 오차 4자리 · 월별 금리 6자리 등 — 은 quant-data `CLAUDE.md` 로 함께 옮김) · **② quant 미룬 지적 2건(`resolve_cutoff_date` — GC=F · 뮤추얼펀드 5종)은 quant-data `docs/DEFERRED_FINDINGS.md` 를 만들어 옮김**(대상 6종이 `catalog.py` 에서 고정이라 지금은 받지 않지만, 표의 상수 하나로 닿음 — `review.md` 「판정할 수 없으면 옮긴다」) · **③ 리뷰는 `review.md` 의 다른 저장소 방식**(quant diff 를 맥락 없는 `general-purpose` 서브에이전트에 — 이 세션은 quant-data 에서 시작해 `/code-review` 가 quant 를 보지 못함 `review.md` 실측 2026-10-04), 순서는 리뷰 → 포맷 → 품질 검증(`review.md` 「코드 리뷰는 품질 검증 «앞»에」 — 체크박스 문구는 그대로)
- 2026-11-11 14:47: 다시 내보내기 — `python3 scripts/export.py --to ../quant/storage/stock`(파이썬 3.12.13) 종료 코드 0, 8개 복사, quant `quant_data_edition.json` 의 커밋 `ae0e12cf80e0e3bbb10b051cf070ae4c3ec3cc17` · 커밋 안 된 변경 `[]` · 기준일 2026-11-06, 합성 8개 모두 quant-data 원본과 `cmp` 같음. quant 문서 고침(① — 각 파일을 `Read` 로 연 뒤): 루트 `CLAUDE.md`(디렉터리 구조 · 「스크립트 실행 규칙」의 `download_data.py` 두 항목 → 「시세는 quant-data 가 내보낸다 · 그 저장소 `CLAUDE.md` 를 먼저 연다」와 「결과 비교 중에 갱신 · 내보내기를 다시 돌리지 않는다」 · 확장성 경계 · 자릿수 표의 입력 행 → quant-data `ROUND_INPUT_PRICE`, 「전역 자릿수 표의 다른 예외」 절 지움) · `README.md`(관련 저장소에 quant-data, 데이터 수집 줄 → 내보낸 사본을 읽는다, 합성 · 레버리지 소개 두 줄 → quant-data README) · `docs/COMMANDS.md`(워크플로우 1 본문 → quant-data 갱신 · 내보내기를 가리킴(명령은 복제하지 않음), 「시세를 다시 받은 뒤 다시 돌리는 순서」 → ① 시세 받기 · ② 결과 러너, 「데이터 다운로드 옵션」 지움) · `scripts/CLAUDE.md`(데이터 스크립트 지도 → 한 줄) · `src/qbt/CLAUDE.md`(`tqqq/` · 월별 금리 줄, 「시세 파일 이름」 → 내보낸 사본 · `_synthetic` · `_adjusted`, 대용 구간 시가가 진짜 시가가 아니라는 줄을 utils 에서 옮겨 옴) · `src/qbt/utils/CLAUDE.md`(폴더 목적 · 지운 모듈 5줄 · 판정 · 이음매 · 대용 시가 규칙 3줄 — 이음매 · 시가 규칙은 quant-data `proxy_series` docstring 에 있음) · `src/qbt/backtest/CLAUDE.md`(이름 1) · `tests/CLAUDE.md`(TQQQ 시뮬레이션 항목 · softplus · 일일 비용 허용오차 2행(quant 테스트 사용 0) · FFR 날짜 형식 절(quant-data `monthly_data` 가 yyyy-mm 아니면 안내와 함께 `ValueError` — 조용히 틀리지 않아 옮기지 않음) · 「입력 시세」 · 패치 예시 → `qbt.backtest.parameter_stability._PLATEAU_DIR`(테스트에 실제 쓰임)) · `docs/DEFERRED_FINDINGS.md`(두 항목 지움, 머리말만) · `src/qbt/utils/data_loader.py` docstring 의 `tqqq/data_loader.py` 참고 줄(주석). 처음 잰 9개 밖에서 더 찾은 낡은 줄: 루트 `CLAUDE.md` 의 `tqqq` · `etc` 3줄 · `README.md` 수집 줄 · `tests/CLAUDE.md` 의 시뮬레이션 · FFR 항목. 옮기지 않고 지운 것: 추적 오차 표 4자리 규칙(사용자 결정 2026-11-05 — `tracking.csv` 를 Q32 로 굳혀 그 자릿수로 만드는 코드가 없음). quant-data 고침(②): `CLAUDE.md` 「자릿수 — 전역 4자리 규칙의 예외」(시세 6자리 · 월별 금리 6자리) · `README.md`(합성 · 레버리지 소개, 미룬 지적 링크) · `docs/DEFERRED_FINDINGS.md` 새로(quant 머리말 그대로, 두 항목의 자리 · 명령 · 파일 이름을 새 코드로 — `sources/yahoo.py:33` · `:45`, `catalog.py:94-99` 고정 표시, 그 사이 값을 쓰는 곳을 지금 코드로 다시 확인: GC=F 는 검증 표 ①(금 사슬 ↔ GLD)만 · 합성 GLD 는 상장 뒤 실물 행, 펀드는 대용 검증 표(VFINX ↔ SPY · VUSTX ↔ TLT)만 · 펀드 대조 표는 굳힘, `GC=F_adjusted.csv` 6,573행 중 일요일 0). 확인: 지금 상태를 말하는 quant 문서 11개에서 지운 이름 · 경로 검색 0줄, 남은 `합성_시세_연장` 3줄(`scripts` · `src/qbt` · `backtest` 의 `CLAUDE.md`)은 Q15 · Phase 5. 리뷰는 quant diff(수정 925줄 · 삭제 목록 58 · storage 이름 · 잠금 파일 크기)와 quant-data 문서 diff 를 scratchpad `review/` 에 떠서 `general-purpose` 서브에이전트에 줌(읽기 전용, `review.md` 의 무게 · 닿는가 정의를 그대로 줌)
- 2026-11-11 15:02: 리뷰 1회차 — 서브에이전트가 사용량 한도(429)로 한 번 멈춰 이어 보내 끝냄(그 사이 두 작업 트리는 계획서 말고 바뀌지 않음). **발견 6건 — 버그 0 [무거움 0 · 가벼움 0] · 그 외 6** → `review.md` 의 고칠 것 0, 1회차로 끝. 6건 모두 지금 코드에서 사실 확인: ① quant-data `DEFERRED_FINDINGS.md` GC=F 항목 — 금 선물 행은 미국 달력(VFINX)에 든 날만 사슬에 남아(`gold_proxy.py:423`) GC=F 하나만 고정을 풀면 닿지 않음, VFINX 도 풀어야 함 ② 같은 파일 펀드 항목 — `catalog.py:94-99` 에 GC=F(`:96`)가 끼어 있음 · VFINX 가 금 사슬의 달력이기도 함(`products.py:71`)이 빠짐 ③ quant `COMMANDS.md` 「시세를 다시 받은 뒤」 — 옛 문서의 「덮어쓰지 않은 종목은 옛 끝날에 머물러 결과 끝날도 묶인다」가 사라짐(새 흐름에서는 quant-data `--exclude` 로 같은 상태 — 예 `--exclude QQQ` 면 QQQ 합성은 옛 끝날 · TQQQ 합성은 새 끝날, 겹치는 기간으로 조용히 짧아짐) ④ quant `src/qbt/CLAUDE.md` 「시세 파일 이름」의 `{TICKER}_{가격 기준}.csv` · `^NDX_raw.csv` 예시 — `ticker_from_stock_path` 는 `_synthetic` · `_adjusted` 만 받음 ⑤ quant `data_loader.py:97` 판이 섞였을 때 안내가 「갱신 뒤 내보내기」 — 내보내기만 다시 하면 풀리고, 갱신은 새 데이터를 들임(루트 `CLAUDE.md` 「결과 비교 중 갱신 금지」와 어긋남) ⑥ quant `test_data_loader.py:11` 머리 설명의 「(합성 생성을 건너뜀)」. 서브에이전트가 읽기 전용 python 대조를 한 번 돌렸다고 밝힘(파일 쓰기 없음). quant `black .` 바뀐 파일 0(102개 그대로). quant `validate_project.py` — Ruff 통과 · PyRight 통과 · pytest passed=668 · failed=0 · skipped=0(31초). 「그 외」 처리는 사용자 결정 대기 — `review.md` 는 「그 외」를 고치지 않는데, ① ② ④ 는 이번 변경에서 쓴 글의 사실 오류다
- 2026-11-11 15:06: 사용자 「추천대로」 → 「그 외」 6건 모두 고침(`review.md` 「그 외는 고치지 않는다」의 사용자 결정 예외 — 버그 수정이 아니라 리뷰 회차는 늘지 않음). ① ② quant-data `DEFERRED_FINDINGS.md` — GC=F 항목의 도달 조건을 「GC=F · VFINX 둘 다 고정을 풀고, 그 시각 VFINX 에 그날 행이 있어야」로(`gold_proxy.py:423` · `products.py:71`, Perth 달러값은 2015-12-31 에 끝나 겹치지 않음), 펀드 항목의 자리를 `catalog.py:94-95` · `:97-99` 로 · VFINX 달력은 날짜만 쓰여 닿지 않음을 더함 ③ quant `COMMANDS.md` ① 에 `--exclude` 로 뺀 종목의 옛 끝날 경고를 되살림(예 QQQ — `buffer_zone.py:82-83` 의 QQQ 신호 · TQQQ 매매) ④ quant `src/qbt/CLAUDE.md` 「시세 파일 이름」 — 「이름은 아래 둘만 읽는다 — 그 밖은 `ticker_from_stock_path` 가 ValueError」, 예시에서 `^NDX_raw.csv` 뺌 ⑤ quant `data_loader.py` 안내 → 「내보내기를 다시 한 뒤 실행 — 갱신까지 하면 새 데이터가 함께 들어온다」(테스트의 `match` 는 `2023-01-04.*2023-01-05.*quant-data` 라 그대로 맞음) ⑥ quant `test_data_loader.py` 머리 설명 7번 · 그 테스트의 Then 줄. 다시 돌림: quant `black .` 바뀐 파일 0, `validate_project.py` Ruff 통과 · PyRight 통과 · pytest passed=668 · failed=0 · skipped=0
- 2026-11-11 15:07: quant 변경을 대상으로 `/commit`(staged 0 → unstaged + untracked 전체: 삭제 58 · 수정 50 · 새 파일 10). quant `CLAUDE.md` 에 커밋 형식 규정 없음 → `기능명 / 요약`. diff 를 파일별로 읽음 — src 2 · tests 6 · `pyproject.toml` · 문서 9 · 결과(경로 필드만 바뀐 `summary.json` 19 · 고원 CSV 12 · 지운 `proxy_validation` 6). 후보 5개를 「Commit Messages (Phase 3 — quant)」에 옮김(최종 후보 절이 아니라 — 이 절의 머리 설명대로). 무관한 덩어리로 고원 CSV 12개(11-08 시세 반영분, 진행 로그 13:52)를 사용자에게 알리고 분리 여부를 물음. **quant 커밋 준비 끝** — 커밋은 사용자(quant · quant-data 둘 다). 다음은 Phase 4(인계 「다음 할 일」)
- 2026-11-11 15:10: 사용자가 quant 를 커밋 — `9530ce9 데이터 / 시세 받기 · 합성을 quant-data 로 이관`(후보 1, 고원 CSV 를 나누지 않은 한 커밋 · 110개 파일), quant 작업 트리 깨끗함. quant 판 요약의 quant-data 커밋은 `ae0e12c`. quant-data 는 커밋 전 — `CLAUDE.md` · `README.md` · `docs/DEFERRED_FINDINGS.md`(새로) · 이 계획서
- 2026-11-11 15:11: 사용자 「커밋메시지 후보 만들어줘」(quant-data) → `/commit`(staged 0 → unstaged 3 + untracked 1 전체, quant-data `CLAUDE.md` 에 커밋 형식 규정 없음). 중간 커밋이라 최종 후보 절이 아니라 「Commit Messages (Phase 3 — quant-data)」를 더해 후보 5개를 옮김(`/impl-plan` 「사용자가 중간 커밋 분리를 명시적으로 요청한 경우」)
