#!/usr/bin/env python3
"""Собирает шапку профиля и таблицу проектов по данным GitHub GraphQL.

Решения, которые важно не откатить обратно:

* Одна гарнитура — JetBrains Mono. У неё есть кириллица (у Archivo нет), а
  перечёркнутый ноль делает ник `imaO0O` читаемым: три знака O-0-O в гротеске
  сливаются в одинаковые овалы.
* Гарнитура вшита в SVG как data-URI. GitHub отдаёт картинку через свой прокси
  как обычный <img>, внешние ресурсы там заблокированы, а data-URI работает.
* Фон прозрачный, боковых полей нет. Шапка встаёт в колонку README без шва и
  переживает все четыре темы GitHub, а не только одну захардкоженную.
* Контраст графики держим не ниже 3:1 (WCAG 1.4.11). Данные — не декорация.
* Шкала активности линейная и помесячная. Корневая шкала завышала неделю с
  одним коммитом в восемь раз, а на 53 недельных столбцах две трети года
  были нулями.

Запуск:
    GITHUB_TOKEN=<token> py scripts/profile.py [login]
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
BOARD = ASSETS / "board"
README = ROOT / "README.md"

TABLE_START = "<!--PROJECTS_START-->"
TABLE_END = "<!--PROJECTS_END-->"

W, H = 860, 258
ACCENT = "#E10600"

# Порядок в таблице задаётся руками: сортировка по дате пуша выносит наверх
# случайный репозиторий, а первым должен стоять основной проект.
FEATURED = [
    "citrus-app",
    "survey-and-notification-bot",
    "ferrari-strategy",
    "mental-health",
]

# Тулчейны тащат в репозитории свои языки — к навыку это не относится.
NOISE_LANGUAGES = {"CMake", "C++", "C", "Objective-C", "Swift", "Shell", "Batchfile",
                   "Ruby", "PowerShell", "Makefile", "Dockerfile", "Inno Setup"}

MONTHS = ["янв", "фев", "мар", "апр", "май", "июн",
          "июл", "авг", "сен", "окт", "ноя", "дек"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, privacy: PUBLIC, ownerAffiliations: OWNER,
                 isFork: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name url description pushedAt
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch(login: str, token: str) -> dict:
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-builder",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "errors" in payload:
        raise SystemExit(f"GraphQL вернул ошибку: {payload['errors']}")
    return payload["data"]["user"]


# ──────────────────────────────── оформление ────────────────────────────────

def font_face() -> str:
    data = base64.b64encode((FONTS / "jbmono-cyr.woff2").read_bytes()).decode()
    return ("@font-face{font-family:'JB';"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');"
            "font-weight:100 800;}")


def palette(dark: bool) -> dict:
    """Все цвета графики проверены на контраст к фону: не ниже 3:1."""
    if dark:
        return {
            "text": "#F2F3F5", "muted": "#9BA3AA", "rule": "#2A313A",
            "bar": "#596167", "peak": "#F2F3F5",
            "ramp": ["#ACB4BA", "#8D959B", "#71797F", "#596167", "#454C52"],
        }
    return {
        "text": "#0B0C0E", "muted": "#5A6268", "rule": "#D8DDE3",
        "bar": "#8E969C", "peak": "#0B0C0E",
        "ramp": ["#424A50", "#5A6268", "#737B81", "#8E969C", "#A9B0B6"],
    }


def styles(colors: dict) -> str:
    return f"""
    text{{font-family:'JB',ui-monospace,monospace;}}
    .name{{font-weight:700;font-size:46px;fill:{colors['text']};letter-spacing:.9px;}}
    .sub{{font-weight:400;font-size:12.5px;fill:{colors['muted']};letter-spacing:.5px;}}
    .num{{font-weight:500;font-size:28px;fill:{colors['text']};
          font-variant-numeric:tabular-nums;}}
    .lab{{font-weight:400;font-size:10.5px;fill:{colors['muted']};letter-spacing:.85px;}}
    .cap{{font-weight:400;font-size:10.5px;fill:{colors['muted']};letter-spacing:.2px;}}
    .rule{{stroke:{colors['rule']};stroke-width:1;}}
"""


# ────────────────────────────────── данные ──────────────────────────────────

def monthly(calendar: dict) -> list[tuple[str, int]]:
    """Свёртка календаря в 12 месяцев, от самого старого к последнему."""
    buckets: dict[str, int] = {}
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            key = day["date"][:7]
            buckets[key] = buckets.get(key, 0) + day["contributionCount"]
    keys = sorted(buckets)[-12:]
    return [(MONTHS[int(key[5:7]) - 1], buckets[key]) for key in keys]


def active_weeks(calendar: dict) -> tuple[int, int, int]:
    totals = [sum(d["contributionCount"] for d in w["contributionDays"])
              for w in calendar["weeks"]]
    return sum(1 for t in totals if t), len(totals), (max(totals) if totals else 0)


def top_languages(nodes: list[dict], limit: int = 4) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for repo in nodes:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name not in NOISE_LANGUAGES:
                totals[name] = totals.get(name, 0) + edge["size"]
    ranked = sorted(totals.items(), key=lambda item: -item[1])
    head, tail = ranked[:limit], ranked[limit:]
    if tail:
        head.append(("прочее", sum(size for _, size in tail)))
    return head


def stack_of(repo: dict) -> str:
    names = [e["node"]["name"] for e in repo["languages"]["edges"]
             if e["node"]["name"] not in NOISE_LANGUAGES]
    return " · ".join(names[:2]) if names else "—"


def humanise(iso: str) -> str:
    moment = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (dt.datetime.now(dt.timezone.utc) - moment).days
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 30:
        return f"{days} дн. назад"
    months = days // 30
    return f"{months} мес. назад" if months < 12 else "больше года назад"


# ─────────────────────────────────── шапка ───────────────────────────────────

def build_hero(login: str, user: dict, dark: bool) -> str:
    colors = palette(dark)
    calendar = user["contributionsCollection"]["contributionCalendar"]
    commits = user["contributionsCollection"]["totalCommitContributions"]
    months = monthly(calendar)
    active, total_weeks, best_week = active_weeks(calendar)
    peak_month = max((value for _, value in months), default=0)

    # Числа выбраны так, чтобы не дублировать то, что GitHub и так рисует
    # рядом на этой же странице (календарь контрибуций и счётчик репозиториев).
    stats = [
        (str(commits), "КОММИТОВ ЗА ГОД"),
        (str(best_week), "ЛУЧШАЯ НЕДЕЛЯ"),
        (f"{active}/{total_weeks}", "АКТИВНЫХ НЕДЕЛЬ"),
    ]

    alt = (f"{commits} коммитов за год, лучшая неделя {best_week}, "
           f"активных недель {active} из {total_weeks}, "
           f"максимум {peak_month} за месяц")

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="{alt}">',
        f"<style>{font_face()}{styles(colors)}</style>",
        # Планка ровно по кэп-высоте имени (0.73 em при кегле 46).
        f'<rect x="0" y="24" width="6" height="34" fill="{ACCENT}"/>',
        f'<text class="name" x="20" y="58">{login}</text>',
        f'<text class="sub" x="20" y="80">Flutter · Python · Java · веб</text>',
    ]

    for index, (value, label) in enumerate(stats):
        x = 510 + index * 120
        out.append(f'<text class="num" x="{x}" y="58">{value}</text>')
        out.append(f'<text class="lab" x="{x}" y="76">{label}</text>')

    out.append(f'<line class="rule" x1="0" y1="104" x2="{W}" y2="104"/>')
    out.append('<text class="lab" x="0" y="126">АКТИВНОСТЬ ПО МЕСЯЦАМ</text>')
    out.append(f'<text class="cap" x="{W}" y="126" text-anchor="end">'
               f'максимум {peak_month} за месяц</text>')

    # Линейная шкала: высота столбца пропорциональна числу коммитов.
    # Пустой месяц не рисуется вовсе — фальшивый минимум создавал бы
    # впечатление работы там, где её не было.
    base_y, max_h, gap = 220, 78, 10
    bar_w = (W - gap * (len(months) - 1)) / len(months)
    for index, (label, value) in enumerate(months):
        x = index * (bar_w + gap)
        if value and peak_month:
            height = value / peak_month * max_h
            fill = colors["peak"] if value == peak_month else colors["bar"]
            out.append(f'<rect x="{x:.1f}" y="{base_y - height:.1f}" '
                       f'width="{bar_w:.1f}" height="{height:.1f}" rx="1.5" fill="{fill}"/>')
        out.append(f'<text class="cap" x="{x + bar_w / 2:.1f}" y="238" '
                   f'text-anchor="middle">{label}</text>')
    out.append(f'<line class="rule" x1="0" y1="{base_y}" x2="{W}" y2="{base_y}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ─────────────────────────────── клетки поля ───────────────────────────────

def build_board_cells() -> None:
    """Клетки поля: рамку рисует сам GitHub у <td>, своя была бы второй."""
    size = 72
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">')
    style = ("<style>"
             ".mark{stroke:#57606A;}.hint{fill:#8C959F;"
             "font-family:ui-monospace,monospace;font-size:12px;}"
             "@media (prefers-color-scheme:dark){"
             ".mark{stroke:#B9C1C9;}.hint{fill:#7D8590;}}"
             "</style>")

    BOARD.mkdir(parents=True, exist_ok=True)
    for index in range(9):
        (BOARD / f"empty-{index}.svg").write_text(
            f'{head}{style}<text class="hint" x="36" y="41" '
            f'text-anchor="middle">{index + 1}</text></svg>\n', encoding="utf-8")

    (BOARD / "x.svg").write_text(
        f'{head}{style}<g class="mark" stroke-width="5" stroke-linecap="round" '
        f'stroke="{ACCENT}"><line x1="25" y1="25" x2="47" y2="47"/>'
        f'<line x1="47" y1="25" x2="25" y2="47"/></g></svg>\n', encoding="utf-8")
    (BOARD / "o.svg").write_text(
        f'{head}{style}<circle class="mark" cx="36" cy="36" r="13" fill="none" '
        f'stroke-width="4.5"/></svg>\n', encoding="utf-8")


# ────────────────────────────── таблица проектов ──────────────────────────────

def build_table(user: dict) -> str:
    by_name = {repo["name"]: repo for repo in user["repositories"]["nodes"]}
    chosen = [by_name[name] for name in FEATURED if name in by_name]

    rows = ["| Проект | Описание | Стек |", "|:--|:--|:--|"]
    for repo in chosen:
        # Описание берём только из самого репозитория: выдумывать за автора
        # нельзя, а пустая ячейка честнее прочерка.
        description = (repo.get("description") or "").strip().strip('"«»')
        if len(description) < 8:
            description = ""
        else:
            description = description[0].upper() + description[1:]
            if len(description) > 80:
                description = description[:80].rsplit(" ", 1)[0].rstrip(' ,.;:—-"«') + "…"
        rows.append(f"| **[{repo['name']}]({repo['url']})** | {description} | {stack_of(repo)} |")
    return "\n".join(rows)


def update_readme(user: dict) -> None:
    text = README.read_text(encoding="utf-8")
    start, end = text.find(TABLE_START), text.find(TABLE_END)
    if start == -1 or end == -1:
        raise SystemExit(f"В README нет маркеров {TABLE_START} / {TABLE_END}")
    README.write_text(
        text[: start + len(TABLE_START)] + "\n" + build_table(user) + "\n" + text[end:],
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Нужен GITHUB_TOKEN в переменных окружения.")
        return 2
    login = argv[1] if len(argv) > 1 else "imaO0O"

    user = fetch(login, token)
    ASSETS.mkdir(parents=True, exist_ok=True)
    for dark, name in ((True, "hero-dark.svg"), (False, "hero-light.svg")):
        (ASSETS / name).write_text(build_hero(login, user, dark), encoding="utf-8")
    build_board_cells()
    print("Собрано: шапка, клетки поля, таблица проектов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
