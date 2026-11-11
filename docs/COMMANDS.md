# quant-data 실행 명령어 레퍼런스

> 이 파일은 실행 명령어의 **단일 SoT(Source of Truth)** 입니다.
> README.md 등 다른 문서에는 실행 명령어를 기재하지 않으며, 필요 시 이 문서를 참조합니다.
> 관련 규칙: 전역 `~/.claude/CLAUDE.md` 「개인 프로젝트 공통」

---

## 갱신

받기 → 판정 → 가공(합성 · 검증 표) → 쓰기 → 판 요약(`storage/edition.json`). 비정상이나 새로 붙는 날 실패가 하나라도
있으면 원인을 내고 **아무 파일도 쓰지 않은 채** 종료 코드 1 로 끝난다.

```bash
# 받을 마지막 날은 기본 그저께 (뉴욕에서 그날 봉이 끝나기 전인 날은 빠진다)
poetry run python scripts/update.py
poetry run python scripts/update.py --end 2026-11-06

# 멈춘 뒤 사람이 정한 자료에만 — 옛 값 · 옛 끝날 그대로 / 이번 응답으로 덮어씀 (여러 번 줄 수 있다)
poetry run python scripts/update.py --exclude QQQ
poetry run python scripts/update.py --accept QQQ

# 받지 않고 지금 파일로 가공 · 판 요약만 — 가공 코드를 고친 뒤. 판 요약이 없는 첫 판은 --end 로 기준일을 준다
poetry run python scripts/update.py --no-fetch
```

새로 붙는 날 검사에 걸린 날은 `storage/records/pass_list.csv` 에 `종목,날짜,검사,사유,근거` 한 줄을 적고 다시 실행한다.

## 내보내기

사용처 저장소의 받는 폴더(그 안에 `quant_data_files.txt` 목록)로 복사한다. 표준 라이브러리만 써서 파이썬 3.10 이상의 `python3`
면 가상환경 없이 돈다 — macOS 기본 `/usr/bin/python3`(3.9)는 안내와 함께 멈춘다.

```bash
python3 scripts/export.py --to ../quant/storage/stock
```

---

## 품질 검증

```bash
# 전체 검증 (Ruff + PyRight + Pytest)
poetry run python validate_project.py

# 테스트 + 커버리지만
poetry run python validate_project.py --cov
```

## 코드 포맷

```bash
poetry run black .
```
