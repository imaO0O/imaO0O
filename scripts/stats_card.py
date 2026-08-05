#!/usr/bin/env python3
"""Генератор карточки статистики в стиле игрового окна статуса.

Тянет данные через GitHub GraphQL и кладёт готовый SVG в assets/stats.svg.
Никаких сторонних сервисов: картинка лежит в репозитории, поэтому не отвалится,
когда у очередного публичного инстанса закончится лимит.

Запуск:
    GITHUB_TOKEN=<token> py scripts/stats_card.py [login]
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "assets" / "stats.svg"

ACCENT = "#a29bfe"
ACCENT_DEEP = "#6c5ce7"
DIM = "#8b8ba7"

# Языки, которые Flutter и прочие генераторы добавляют сами — они не про навык.
NOISE_LANGUAGES = {"CMake", "C++", "C", "Objective-C", "Swift", "Ruby", "Shell", "Batchfile"}

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
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
            "User-Agent": "profile-stats-card",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if "errors" in payload:
        raise SystemExit(f"GraphQL вернул ошибку: {payload['errors']}")
    return payload["data"]["user"]


def streaks(weeks: list[dict]) -> tuple[int, int]:
    days = [d for week in weeks for d in week["contributionDays"]]
    days.sort(key=lambda d: d["date"])

    longest = run = 0
    for day in days:
        run = run + 1 if day["contributionCount"] > 0 else 0
        longest = max(longest, run)

    # Текущую серию считаем с конца, разрешая «сегодня ещё не коммитил».
    today = dt.date.today().isoformat()
    current = 0
    for day in reversed(days):
        if day["contributionCount"] > 0:
            current += 1
        elif day["date"] != today:
            break
    return current, longest


def top_languages(nodes: list[dict], limit: int = 5) -> list[tuple[str, str, float]]:
    totals: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in nodes:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in NOISE_LANGUAGES:
                continue
            totals[name] = totals.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or ACCENT
    if not totals:
        return []
    ranked = sorted(totals.items(), key=lambda item: -item[1])[:limit]
    biggest = ranked[0][1]
    return [(name, colors[name], size / biggest) for name, size in ranked]


def build_svg(login: str, user: dict) -> str:
    repos = user["repositories"]
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"]
    current, longest = streaks(calendar["weeks"])
    languages = top_languages(repos["nodes"])
    stars = sum(repo["stargazerCount"] for repo in repos["nodes"])

    rows = [
        ("COMMITS", f"{contributions['totalCommitContributions']}", "за год"),
        ("PULL REQUESTS", f"{contributions['totalPullRequestContributions']}", "принято в бой"),
        ("REPOSITORIES", f"{repos['totalCount']}", "проектов"),
        ("CONTRIBUTIONS", f"{calendar['totalContributions']}", "клеток закрашено"),
        ("STREAK", f"{current}", f"дней подряд · рекорд {longest}"),
        ("STARS", f"{stars}", "звёзд собрано"),
    ]

    width, height = 820, 320
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="статистика {escape(login)}">',
        """
  <style>
    .bg      { fill: none; stroke: #a29bfe; stroke-width: 2; }
    .glow    { fill: #6c5ce7; opacity: .06; }
    text     { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .title   { font-size: 15px; font-weight: 700; fill: #a29bfe; letter-spacing: 3px; }
    .label   { font-size: 12px; fill: #8b8ba7; letter-spacing: 1px; }
    .value   { font-size: 22px; font-weight: 700; fill: #6c5ce7; }
    .note    { font-size: 10px; fill: #8b8ba7; }
    .lang    { font-size: 12px; fill: #8b8ba7; }
    .track   { fill: #8b8ba7; opacity: .22; }
    @media (prefers-color-scheme: dark) {
      .value { fill: #a29bfe; }
      .label, .lang, .note { fill: #9d9dbd; }
      .track { opacity: .16; }
    }
  </style>
""",
        f'  <rect class="glow" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="14"/>',
        f'  <rect class="bg" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="14"/>',
        f'  <text class="title" x="28" y="38">PLAYER STATS · {escape(login).upper()}</text>',
        f'  <line x1="28" y1="52" x2="{width - 28}" y2="52" stroke="{ACCENT}" stroke-width="1" opacity=".35"/>',
    ]

    # Левая колонка — числа.
    y = 88
    for index, (label, value, note) in enumerate(rows):
        column_x = 28 if index < 3 else 250
        row_y = y + (index % 3) * 74
        parts += [
            f'  <text class="label" x="{column_x}" y="{row_y}">{label}</text>',
            f'  <text class="value" x="{column_x}" y="{row_y + 26}">{value}</text>',
            f'  <text class="note" x="{column_x}" y="{row_y + 42}">{escape(note)}</text>',
        ]

    # Правая колонка — языки: подпись, под ней шкала.
    bar_x, bar_w = 460, 332
    parts.append(f'  <text class="label" x="{bar_x}" y="88">SKILL TREE</text>')
    for index, (name, color, fraction) in enumerate(languages):
        row_y = 116 + index * 38
        percent = round(fraction * 100)
        parts += [
            f'  <text class="lang" x="{bar_x}" y="{row_y}">{escape(name)}</text>',
            f'  <text class="lang" x="{bar_x + bar_w}" y="{row_y}" text-anchor="end">{percent}%</text>',
            f'  <rect class="track" x="{bar_x}" y="{row_y + 7}" width="{bar_w}" height="9" rx="4.5"/>',
            f'  <rect x="{bar_x}" y="{row_y + 7}" width="{round(bar_w * fraction, 1)}" '
            f'height="9" rx="4.5" fill="{color}"/>',
        ]

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%d.%m.%Y")
    parts += [
        f'  <text class="note" x="28" y="{height - 18}">save file updated: {stamp} · автообновление раз в сутки</text>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Нужен GITHUB_TOKEN в переменных окружения.")
        return 2
    login = argv[1] if len(argv) > 1 else os.environ.get("USERNAME_OVERRIDE", "imaO0O")

    user = fetch(login, token)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build_svg(login, user), encoding="utf-8")
    print(f"Готово: {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
