"""
wordstat_api.py — клиент Yandex Cloud Wordstat API (Search API v2) для Шагов 1 и 3.

Старый «Yandex Cloud Wordstat API» по ссылке support2/wordstat теперь живёт внутри
**Yandex Search API** (Yandex Cloud AI Studio). Метод topRequests отдаёт похожие
запросы с частотностью + ассоциации. Это то, на чём держатся:
  - Шаг 1 (mask-builder): проверка существования маски и её частотности (≥150).
  - Шаг 3: сбор полной семантики (results[] → keyword,frequency,mask_parent).

Эндпоинт:  POST https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests
Авторизация: заголовок  Authorization: Api-Key <key>
  - key — API-ключ из Yandex Cloud AI Studio, привязанный к сервисному аккаунту
    (тот же ключ, что для YandexGPT). Переменная WORDSTAT_API_KEY.
  - folderId — ОБЯЗАТЕЛЕН в теле каждого запроса. Переменная WORDSTAT_FOLDER_ID.

Креды берутся из окружения ИЛИ из файла .env в корне проекта (load_dotenv ниже):
    WORDSTAT_API_KEY=...
    WORDSTAT_FOLDER_ID=...
Реальное окружение имеет приоритет над .env.

Подводные камни (учтены в коде):
  - Поля count / totalCount приходят СТРОКАМИ (int64→JSON) — кастуем в int.
  - Без folderId — ошибка INVALID_ARGUMENT.
  - associations может быть пустым массивом (узкая ниша), не null.
  - Лимит ~5-10 rps — между фразами спим 0.2 c.
  - Операторы Wordstat (!, +, [], "") НЕ поддерживаются — фразы шлём «как есть».

Использование:
  # проверка подключения (один запрос по тестовой фразе)
  python -m scripts.wordstat_api --check --regions 213

  # частотности масок (Шаг 1) → JSON
  python -m scripts.wordstat_api --mode masks --phrases-file masks.txt \
      --regions 213,2 --output 01_masks_freq.json

  # сбор семантики (Шаг 3) → CSV keyword,frequency,mask_parent
  python -m scripts.wordstat_api --mode semantics --phrases-file masks.txt \
      --regions 213 --num-phrases 300 --output 03_semantics_raw.csv

Документация: https://yandex.cloud/ru/docs/search-api/concepts/wordstat
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib import request as urlreq, error as urlerror

BASE_URL = "https://searchapi.api.cloud.yandex.net/v2/wordstat"
THROTTLE_SEC = 0.2  # пауза между фразами, чтобы не упереться в rps-лимит


class WordstatError(RuntimeError):
    pass


def load_dotenv() -> None:
    """Подхватывает KEY=VALUE из .env (CWD или корень репозитория) в os.environ.

    Без внешних зависимостей. Уже заданные переменные окружения НЕ перетирает —
    приоритет у реального окружения. Кавычки вокруг значения снимаются.
    """
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    seen: set = set()
    for env_path in candidates:
        try:
            rp = env_path.resolve()
        except OSError:
            continue
        if rp in seen or not env_path.is_file():
            continue
        seen.add(rp)
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _to_int(value) -> int:
    """count/totalCount приходят строками ('21500'); безопасно кастуем."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def call(path: str, body: dict, key: str, folder_id: str) -> dict:
    body = dict(body)
    body.setdefault("folderId", folder_id)
    url = f"{BASE_URL}/{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urlreq.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Api-Key {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body_text)
            msg = parsed.get("message") or parsed.get("error") or body_text
        except json.JSONDecodeError:
            msg = body_text
        raise WordstatError(f"HTTP {e.code}: {msg}") from e
    except urlerror.URLError as e:
        raise WordstatError(f"Сеть/SSL: {e.reason}") from e


def _extract_results(response: dict) -> list[dict]:
    """Массив похожих запросов. Имя поля у источников расходится — берём, что есть."""
    for key in ("results", "topRequests", "requests"):
        if isinstance(response.get(key), list):
            return response[key]
    return []


def top_requests(phrase: str, regions: list[str], key: str, folder_id: str,
                 num_phrases: int = 20, devices: list[str] | None = None) -> dict:
    body = {"phrase": phrase, "numPhrases": num_phrases, "regions": regions}
    if devices:
        body["devices"] = devices
    raw = call("topRequests", body, key, folder_id)
    return {
        "phrase": phrase,
        "total_count": _to_int(raw.get("totalCount")),
        "results": [
            {"keyword": r.get("phrase", ""), "frequency": _to_int(r.get("count"))}
            for r in _extract_results(raw)
        ],
        "associations": [
            {"keyword": a.get("phrase", ""), "frequency": _to_int(a.get("count"))}
            for a in (raw.get("associations") or [])
        ],
    }


def normalize(phrase: str) -> str:
    """Канонизация фразы для дедупликации: lower-case + один пробел между словами."""
    return " ".join(phrase.lower().split())


def passes_anchor(keyword: str, anchors: list[str]) -> bool:
    """True, если запрос содержит хотя бы одну основу-якорь. Пустой список — не фильтруем."""
    if not anchors:
        return True
    kw = keyword.lower()
    return any(a.lower() in kw for a in anchors)


def is_dry(new_unique: int, total_before: int, dry_threshold: float) -> bool:
    """Волна 'сухая', если принесла новых меньше доли dry_threshold от уже собранного."""
    if total_before <= 0:
        return False
    return new_unique < dry_threshold * total_before


def select_next_seeds(found_this_wave: list[dict], used_seeds: set[str],
                      anchors: list[str], seed_floor: int,
                      seeds_per_wave: int) -> list[dict]:
    """Кандидаты в семена следующей волны: порог частоты + якорь + не были семенами,
    топ по убыванию частоты, не больше seeds_per_wave."""
    candidates = [
        r for r in found_this_wave
        if r["frequency"] >= seed_floor
        and passes_anchor(r["keyword"], anchors)
        and normalize(r["keyword"]) not in used_seeds
    ]
    candidates.sort(key=lambda r: r["frequency"], reverse=True)
    return candidates[:seeds_per_wave]


def collect_semantics(initial_seeds: list[str], anchors: list[str], fetch_fn,
                      *, num_phrases: int = 1000, max_depth: int = 2,
                      seed_floor: int = 10, seeds_per_wave: int = 150,
                      dry_threshold: float = 0.05, max_api_calls: int = 1000,
                      max_minutes: float = 15.0, throttle_sec: float = 0.2,
                      clock=time.monotonic, sleep_fn=time.sleep, log_fn=print):
    """Рекурсивный сбор семантики волнами. fetch_fn(phrase)->{'results','associations'}.
    Возвращает (rows, report). Конечен по построению + 4 предохранителя:
    dry / max_api_calls / max_minutes / серия сбоев. Частичный результат сохраняется."""
    start = clock()
    seen: set[str] = set()
    rows: list[dict] = []
    used_seeds: set[str] = set()
    total_calls = 0
    consecutive_failures = 0
    stop_reason = "depth"
    waves_report: list[dict] = []
    budget_hit = False

    current: list[tuple[str, str]] = []  # (фраза-семя, корневой mask_parent)
    for s in initial_seeds:
        n = normalize(s)
        if n and n not in used_seeds:
            used_seeds.add(n)
            current.append((s, s))

    depth = 0
    while current and depth <= max_depth:
        total_before = len(seen)
        wave_rows: list[dict] = []
        for phrase, root in current:
            if total_calls >= max_api_calls:
                stop_reason = "max_api_calls"
                budget_hit = True
                break
            if (clock() - start) >= max_minutes * 60:
                stop_reason = "max_minutes"
                budget_hit = True
                break
            try:
                resp = fetch_fn(phrase)
                total_calls += 1
                consecutive_failures = 0
            except WordstatError as e:
                total_calls += 1
                consecutive_failures += 1
                log_fn(f"  ! сбой по семени «{phrase}»: {e}")
                if consecutive_failures >= 5:
                    stop_reason = "failures"
                    budget_hit = True
                    break
                continue
            for source_name, items in (("result", resp.get("results", [])),
                                       ("association", resp.get("associations", []))):
                for it in items:
                    kw = it.get("keyword", "")
                    n = normalize(kw)
                    if not n or n in seen:
                        continue
                    seen.add(n)
                    row = {"keyword": kw, "frequency": it.get("frequency", 0),
                           "mask_parent": root, "source": source_name, "depth": depth}
                    rows.append(row)
                    wave_rows.append(row)
            sleep_fn(throttle_sec)

        new_unique = len(seen) - total_before
        waves_report.append({"depth": depth, "seeds": len(current),
                             "new_keywords": new_unique, "total": len(seen),
                             "calls": total_calls})
        log_fn(f"Волна {depth}: семян {len(current)}, новых {new_unique}, "
               f"всего {len(seen)}, вызовов {total_calls}")

        if budget_hit:
            break
        if depth >= max_depth:
            stop_reason = "depth"
            break
        if is_dry(new_unique, total_before, dry_threshold):
            stop_reason = "dry"
            break

        next_rows = select_next_seeds(wave_rows, used_seeds, anchors,
                                      seed_floor, seeds_per_wave)
        for r in next_rows:
            used_seeds.add(normalize(r["keyword"]))
        current = [(r["keyword"], r["mask_parent"]) for r in next_rows]
        if not current:
            stop_reason = "exhausted"
            break
        depth += 1

    report = {"total_keywords": len(rows), "total_calls": total_calls,
              "elapsed_sec": round(clock() - start, 1), "stop_reason": stop_reason,
              "waves": waves_report}
    return rows, report


def write_semantics_csv(rows: list[dict], path: str) -> None:
    """CSV строго: keyword,frequency,mask_parent (совместимость с Шагом 4) + source,depth."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["keyword", "frequency", "mask_parent", "source", "depth"])
        for r in rows:
            w.writerow([r["keyword"], r["frequency"], r["mask_parent"],
                        r["source"], r["depth"]])


def _read_phrases(args) -> list[str]:
    if args.phrase:
        return [args.phrase]
    if args.phrases_file:
        lines = Path(args.phrases_file).read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return []


def _creds() -> tuple[str, str]:
    key = os.environ.get("WORDSTAT_API_KEY") or os.environ.get("YANDEX_AI_API_KEY")
    folder = os.environ.get("WORDSTAT_FOLDER_ID") or os.environ.get("YANDEX_FOLDER_ID")
    if not key:
        sys.exit("ERROR: нет WORDSTAT_API_KEY — впиши его в .env в корне проекта "
                 "(Api-Key из Yandex Cloud AI Studio)")
    if not folder:
        sys.exit("ERROR: нет WORDSTAT_FOLDER_ID — впиши folder_id Yandex Cloud в .env")
    return key, folder


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    load_dotenv()  # подхватить WORDSTAT_API_KEY / WORDSTAT_FOLDER_ID из .env

    parser = argparse.ArgumentParser(description="Yandex Cloud Wordstat API (Search API v2) — topRequests")
    parser.add_argument("--mode", choices=["masks", "semantics"], default="masks",
                        help="masks — частотности фраз (Шаг 1); semantics — сбор ключей (Шаг 3)")
    parser.add_argument("--check", action="store_true",
                        help="Проверка подключения: один запрос по тестовой фразе, печать OK/ошибки")
    parser.add_argument("--phrase", help="Одна фраза")
    parser.add_argument("--phrases-file", help="Файл с фразами (по одной в строке, # — комментарий)")
    parser.add_argument("--regions", default="225",
                        help="ID регионов через запятую (225=РФ, 213=Москва, 2=СПб)")
    parser.add_argument("--num-phrases", type=int, default=1000,
                        help="Сколько похожих запросов на фразу (1-2000)")
    parser.add_argument("--anchors-file", default=None,
                        help="Файл с якорями-основами (по одной в строке) для фильтра релевантности рекурсии")
    parser.add_argument("--max-depth", type=int, default=2,
                        help="Глубина рекурсии: волна 0 + столько рекурсивных волн (0 = один проход)")
    parser.add_argument("--seed-floor", type=int, default=10,
                        help="Мин. частота запроса, чтобы стать семенем следующей волны")
    parser.add_argument("--seeds-per-wave", type=int, default=150,
                        help="Топ-N по частоте в семена каждой волны")
    parser.add_argument("--dry-threshold", type=float, default=0.05,
                        help="Стоп, если волна дала новых меньше этой доли от собранного")
    parser.add_argument("--max-api-calls", type=int, default=1000,
                        help="Предохранитель: максимум вызовов API")
    parser.add_argument("--max-minutes", type=float, default=15.0,
                        help="Предохранитель: максимум минут на сбор")
    parser.add_argument("--devices", default=None,
                        help="DEVICE_ALL|DEVICE_DESKTOP|DEVICE_PHONE|DEVICE_TABLET, через запятую")
    parser.add_argument("--output", default=None, help="Файл результата (по умолчанию stdout)")
    args = parser.parse_args()

    key, folder = _creds()
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    devices = [d.strip() for d in args.devices.split(",")] if args.devices else None

    if args.check:
        try:
            res = top_requests("кофеварка", regions, key, folder, num_phrases=5)
            print(f"OK — подключение работает. totalCount по тестовой фразе 'кофеварка' "
                  f"в регионах {regions}: {res['total_count']}, похожих запросов: {len(res['results'])}")
        except WordstatError as e:
            sys.exit(f"FAIL — {e}")
        return

    phrases = _read_phrases(args)
    if not phrases:
        sys.exit("ERROR: не заданы фразы (--phrase или --phrases-file)")

    if args.mode == "masks":
        out_rows = []
        for i, ph in enumerate(phrases):
            res = top_requests(ph, regions, key, folder, num_phrases=args.num_phrases, devices=devices)
            out_rows.append({
                "mask": ph,
                "frequency": res["total_count"],
                "exists": res["total_count"] > 0,
                "variants_found": len(res["results"]),
            })
            if i < len(phrases) - 1:
                time.sleep(THROTTLE_SEC)
        payload = json.dumps(out_rows, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
            print(f"Записано {len(out_rows)} масок: {args.output}")
        else:
            print(payload)

    else:  # semantics
        anchors: list[str] = []
        if args.anchors_file:
            anchors = [ln.strip().lower()
                       for ln in Path(args.anchors_file).read_text(encoding="utf-8").splitlines()
                       if ln.strip() and not ln.startswith("#")]

        def fetch_fn(phrase: str) -> dict:
            return top_requests(phrase, regions, key, folder,
                                num_phrases=args.num_phrases, devices=devices)

        rows, report = collect_semantics(
            phrases, anchors, fetch_fn,
            num_phrases=args.num_phrases, max_depth=args.max_depth,
            seed_floor=args.seed_floor, seeds_per_wave=args.seeds_per_wave,
            dry_threshold=args.dry_threshold, max_api_calls=args.max_api_calls,
            max_minutes=args.max_minutes,
        )

        if args.output:
            write_semantics_csv(rows, args.output)
            print(f"Записано {report['total_keywords']} ключей в {args.output}", file=sys.stderr)
        else:
            w = csv.writer(sys.stdout)
            w.writerow(["keyword", "frequency", "mask_parent", "source", "depth"])
            for r in rows:
                w.writerow([r["keyword"], r["frequency"], r["mask_parent"],
                            r["source"], r["depth"]])

        print(f"Сбор завершён: причина остановки = {report['stop_reason']}, "
              f"вызовов API = {report['total_calls']}, "
              f"время = {report['elapsed_sec']} c, "
              f"волн = {len(report['waves'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
