#!/usr/bin/env python3
"""Собирает визуальные ассеты профиля и таблицу проектов.

Что делает:
  1. рисует assets/hero-dark.svg и assets/hero-light.svg по данным GitHub GraphQL;
  2. перезаписывает таблицу проектов в README между маркерами.

Гарнитуры (Archivo и JetBrains Mono, обе под OFL) подрезаны до латиницы и
вшиваются в SVG как data-URI. Это принципиально: GitHub отдаёт картинку через
свой прокси как обычный <img>, где внешние ресурсы заблокированы, — а data-URI
работает. Поэтому заголовок набран настоящей гарнитурой, а не системной.

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
README = ROOT / "README.md"

TABLE_START = "<!--PROJECTS_START-->"
TABLE_END = "<!--PROJECTS_END-->"

W, H = 1200, 410
MARGIN = 64
ACCENT = "#E10600"

# Flutter и прочие тулчейны тащат в репозиторий свои языки — к навыку они не относятся.
NOISE_LANGUAGES = {"CMake", "C++", "C", "Objective-C", "Swift", "Shell", "Batchfile",
                   "Ruby", "PowerShell", "Makefile", "Dockerfile", "Inno Setup"}

QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, privacy: PUBLIC, ownerAffiliations: OWNER,
                 isFork: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name url description pushedAt isArchived
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount } }
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


# ──────────────────────────────── типографика ────────────────────────────────

def font_face() -> str:
    def embed(filename: str, family: str, upper: int) -> str:
        data = base64.b64encode((FONTS / filename).read_bytes()).decode()
        return (f"@font-face{{font-family:'{family}';"
                f"src:url(data:font/woff2;base64,{data}) format('woff2');"
                f"font-weight:100 {upper};}}")

    return embed("archivo.woff2", "AR", 900) + embed("jbmono.woff2", "JB", 800)


def theme_css(dark: bool) -> str:
    if dark:
        ink, hair, text, muted, tick = "#08090B", "#1E222A", "#F2F3F5", "#767D89", "#2A2F39"
        ramp = ["#8A929E", "#6A727E", "#4E555F", "#3A4048", "#2C3138"]
    else:
        ink, hair, text, muted, tick = "#FFFFFF", "#E3E6EB", "#0B0C0E", "#6B717C", "#D8DCE3"
        ramp = ["#6B717C", "#8B919B", "#A7ACB5", "#C0C4CB", "#D6D9DE"]
    css = f"""
    .bg{{fill:{ink};}}
    .rule,.base{{stroke:{hair};stroke-width:1;}}
    .accent{{fill:{ACCENT};}}
    .name{{font-family:'AR';font-variation-settings:'wdth' 112,'wght' 700;
           fill:{text};font-size:68px;letter-spacing:1px;}}
    .sub{{font-family:'AR';font-variation-settings:'wdth' 88,'wght' 500;
          fill:{muted};font-size:12.5px;letter-spacing:4.6px;}}
    .num{{font-family:'JB';font-weight:500;fill:{text};font-size:33px;
          font-variant-numeric:tabular-nums;}}
    .lab{{font-family:'AR';font-variation-settings:'wdth' 88,'wght' 600;
          fill:{muted};font-size:9.5px;letter-spacing:2.4px;}}
    .cap{{font-family:'JB';font-weight:400;fill:{muted};font-size:9.5px;letter-spacing:1.4px;}}
    .tick{{fill:{tick};}}
    .peak{{fill:{ACCENT};}}
"""
    return css, ramp


# ────────────────────────────────── данные ──────────────────────────────────

def top_languages(nodes: list[dict], limit: int = 6) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for repo in nodes:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name not in NOISE_LANGUAGES:
                totals[name] = totals.get(name, 0) + edge["size"]
    return sorted(totals.items(), key=lambda item: -item[1])[:limit]


def stack_of(repo: dict) -> str:
    names = [e["node"]["name"] for e in repo["languages"]["edges"]
             if e["node"]["name"] not in NOISE_LANGUAGES]
    return " · ".join(names[:2]) if names else "—"


def days_ago(iso: str) -> int:
    moment = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - moment).days


def humanise(days: int) -> str:
    if days <= 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 30:
        return f"{days} дн. назад"
    months = days // 30
    if months < 12:
        return f"{months} мес. назад"
    years = days // 365
    return "год назад" if years == 1 else f"{years} г. назад"


# ─────────────────────────────────── hero ───────────────────────────────────

def build_hero(login: str, user: dict, dark: bool) -> str:
    contributions = user["contributionsCollection"]
    calendar = contributions["contributionCalendar"]
    weeks = [sum(d["contributionCount"] for d in w["contributionDays"])
             for w in calendar["weeks"]]
    peak = max(weeks) if weeks else 0
    peak_index = weeks.index(peak) if peak else -1
    css, ramp = theme_css(dark)

    stats = [
        (str(contributions["totalCommitContributions"]), "COMMITS"),
        (str(calendar["totalContributions"]), "CONTRIBUTIONS"),
        (str(user["repositories"]["totalCount"]), "REPOSITORIES"),
    ]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="{login} — заголовок профиля">',
        f"<style>{font_face()}{css}</style>",
        f'<rect class="bg" width="{W}" height="{H}"/>',
        f'<rect class="accent" x="{MARGIN}" y="56" width="5" height="62"/>',
        f'<text class="name" x="{MARGIN + 24}" y="112">{login.upper()}</text>',
        f'<text class="sub" x="{MARGIN + 27}" y="140">STUDENT SOFTWARE DEVELOPER</text>',
        f'<text class="sub" x="{MARGIN + 27}" y="160">MOBILE · BOTS · WEB</text>',
    ]

    x = W - MARGIN
    for value, label in reversed(stats):
        out.append(f'<text class="num" x="{x}" y="102" text-anchor="end">{value}</text>')
        out.append(f'<text class="lab" x="{x}" y="122" text-anchor="end">{label}</text>')
        x -= 200

    out.append(f'<line class="rule" x1="{MARGIN}" y1="190" x2="{W - MARGIN}" y2="190"/>')

    # Активность за 52 недели. Шкала корневая: при линейной редкие пики
    # вдавливают все остальные недели в ноль и график читается как сломанный.
    base_y, max_h = 250, 46
    span = W - MARGIN * 2
    step = span / max(len(weeks), 1)
    bar_w = max(2.0, step - 3.4)
    for index, value in enumerate(weeks):
        share = (value / peak) ** 0.5 if peak else 0
        height = max(2.0, share * max_h)
        css_class = "peak" if index == peak_index else "tick"
        out.append(f'<rect class="{css_class}" x="{MARGIN + index * step:.1f}" '
                   f'y="{base_y - height:.1f}" width="{bar_w:.1f}" '
                   f'height="{height:.1f}" rx="1"/>')
    out += [
        f'<line class="base" x1="{MARGIN}" y1="{base_y + 0.5}" x2="{W - MARGIN}" y2="{base_y + 0.5}"/>',
        f'<text class="cap" x="{MARGIN}" y="270">52 WEEKS</text>',
        f'<text class="cap" x="{W - MARGIN}" y="270" text-anchor="end">PEAK {peak} / WEEK</text>',
        f'<line class="rule" x1="{MARGIN}" y1="306" x2="{W - MARGIN}" y2="306"/>',
        f'<text class="lab" x="{MARGIN}" y="334">LANGUAGE DISTRIBUTION</text>',
    ]

    # Одна полоса на все языки. Цвета GitHub намеренно не используются:
    # четыре чужих насыщенных оттенка разваливают палитру.
    languages = top_languages(user["repositories"]["nodes"])
    total = sum(size for _, size in languages) or 1
    palette = [ACCENT] + ramp

    x = float(MARGIN)
    for index, (_name, size) in enumerate(languages):
        segment = span * size / total
        out.append(f'<rect x="{x:.1f}" y="348" width="{max(segment - 2.5, 1):.1f}" '
                   f'height="10" rx="1.5" fill="{palette[index % len(palette)]}"/>')
        x += segment

    x = float(MARGIN)
    for index, (name, size) in enumerate(languages):
        share = round(100 * size / total)
        if share < 4:
            continue
        out.append(f'<rect x="{x:.1f}" y="378" width="8" height="8" rx="1.5" '
                   f'fill="{palette[index % len(palette)]}"/>')
        out.append(f'<text class="cap" x="{x + 16:.1f}" y="386">{name.upper()} {share}%</text>')
        x += len(name) * 7.0 + 66

    out.append("</svg>")
    return "\n".join(out) + "\n"


# ────────────────────────────── таблица проектов ──────────────────────────────

def tidy_description(raw: str | None, limit: int = 84) -> str:
    """Готовит описание репозитория к вставке в таблицу."""
    if not raw:
        return ""
    text = raw.strip().strip('"«»').replace("|", "\\|")
    if len(text) < 8:          # ":)" и подобное — не описание
        return ""
    if len(text) > limit:      # режем по границе слова, а не посреди него
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
        text = cut + "…"
    return text[0].upper() + text[1:]


def build_table(login: str, user: dict) -> str:
    repos = [r for r in user["repositories"]["nodes"]
             if r["name"].lower() != login.lower()]

    rows = [
        "| № | Проект | Стек | Обновлён |",
        "|:-:|:--|:--|--:|",
    ]
    for index, repo in enumerate(repos[:8], start=1):
        title = f"**[{repo['name']}]({repo['url']})**"
        description = tidy_description(repo.get("description"))
        if description:
            title += f"<br><sub>{description}</sub>"
        rows.append(
            f"| `{index:02d}` | {title} | {stack_of(repo)} | {humanise(days_ago(repo['pushedAt']))} |"
        )
    return "\n".join(rows)


def update_readme(login: str, user: dict) -> None:
    text = README.read_text(encoding="utf-8")
    start, end = text.find(TABLE_START), text.find(TABLE_END)
    if start == -1 or end == -1:
        raise SystemExit(f"В README нет маркеров {TABLE_START} / {TABLE_END}")
    README.write_text(
        text[: start + len(TABLE_START)] + "\n" + build_table(login, user) + "\n" + text[end:],
        encoding="utf-8",
    )


BOARD_DIR = ASSETS / "board"

# Нейтральный серый: одна и та же клетка читается и в светлой, и в тёмной теме,
# поэтому парные ассеты под каждую тему не нужны.
STROKE = "#8B93A1"


def build_board_cells() -> None:
    """Клетки игрового поля как SVG: зона клика во всю клетку, а не в один символ."""
    size, radius = 76, 7
    frame = (f'<rect x="1.5" y="1.5" width="{size - 3}" height="{size - 3}" rx="{radius}" '
             f'fill="none" stroke="{STROKE}" stroke-opacity=".38" stroke-width="1.5"/>')
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">')

    cells = {
        "empty": f'{head}{frame}<circle cx="38" cy="38" r="2.5" fill="{STROKE}" '
                 f'fill-opacity=".28"/></svg>',
        "x": f'{head}{frame}<g stroke="{ACCENT}" stroke-width="4.5" stroke-linecap="round">'
             f'<line x1="27" y1="27" x2="49" y2="49"/>'
             f'<line x1="49" y1="27" x2="27" y2="49"/></g></svg>',
        "o": f'{head}{frame}<circle cx="38" cy="38" r="12.5" fill="none" '
             f'stroke="{STROKE}" stroke-width="4.5"/></svg>',
    }
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    for name, markup in cells.items():
        (BOARD_DIR / f"{name}.svg").write_text(markup + "\n", encoding="utf-8")


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
    update_readme(login, user)
    print("Собрано: assets/hero-dark.svg, assets/hero-light.svg, таблица проектов в README")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
