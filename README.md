# quant-data

시세를 받고 · 판정하고 · 가공해(합성 · 국내 수정주가) 사용처 저장소(quant · verify-lab)로 내보내는 데이터 저장소입니다.

- **상장 전 구간을 채운 1배 합성 시세** — 실물 ETF 상장 전을 지수 · 인덱스 펀드로 채운다(QQQ ← 나스닥 100 지수, 1985년부터 · SPY ← S&P 500 인덱스 펀드 VFINX, 1980년부터 · TLT ← 장기국채 펀드 VUSTX, 1986년부터 · GLD ← Perth Mint 금값과 금 선물을 이은 금 사슬에서 GLD 운용보수를 뺀 것, 1980년부터). 대용이 실물을 얼마나 따르는지 검증 표로 남긴다
- **레버리지 ETF 합성 (TQQQ · QLD · SSO · UPRO)** — softplus 동적 스프레드 비용 모델로 상장 전 구간(나스닥 100 쪽 1985년부터 · S&P 500 쪽 1980년부터, 월별 금리는 FRED 에서 받는다)의 시가 · 고가 · 저가 · 종가를 시뮬레이션해 실물 시세에 이어 붙인다. 실물 ETF 추적 오차 · ETF 상장 전 레버리지 펀드 대조는 2026-11-06 시점 기록으로 굳혔고, 비용 가정을 바꾼 판은 만들 때마다 다시 만든다

- 실행 명령: [docs/COMMANDS.md](docs/COMMANDS.md)
- 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 미룬 코드 리뷰 지적: [docs/DEFERRED_FINDINGS.md](docs/DEFERRED_FINDINGS.md)
