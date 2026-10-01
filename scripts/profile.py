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
* Стек не пишется руками, а собирается из кода публичных репозиториев:
  язык, зависимость в манифесте или служебный файл. Появился проект с
  PyTorch — PyTorch сам появится в профиле. Руками добавляется только то,
  чего в коде не видно (редакторы, Figma).

Запуск:
    GITHUB_TOKEN=<token> py scripts/profile.py [login]
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
ICONS = ASSETS / "icons" / "icons.json"
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
        defaultBranchRef { name }
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

def build_hero(login: str, user: dict, dark: bool, subtitle: str) -> str:
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
        f'<text class="sub" x="20" y="80">{subtitle}</text>',
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


# ──────────────────────────────────── стек ────────────────────────────────────
#
# Каждая технология в панели держится на доказательстве в коде, а число ×N —
# это сколько публичных репозиториев её реально используют. Что откуда взялось,
# скрипт пишет в assets/stack.json — его удобно открыть, если что-то удивило.

# (ключ, подпись в панели, короткое имя направления для шапки или "")
CATEGORIES = [
    ("lang", "ЯЗЫКИ", ""),
    ("mobile", "МОБАЙЛ", "мобайл"),
    ("web", "ВЕБ", "веб"),
    ("back", "БЭКЕНД", "бэкенд"),
    ("ml", "ML И ДАННЫЕ", "ML"),
    ("game", "ГЕЙМДЕВ", "геймдев"),
    ("bots", "БОТЫ", "боты"),
    ("test", "ТЕСТЫ", ""),
    ("infra", "ИНФРАСТРУКТУРА", ""),
    ("tools", "ИНСТРУМЕНТЫ", ""),
]

# Технология → (категория, иконка из assets/icons/icons.json или None). Порядок внутри
# категории — порядок этого словаря, если число репозиториев одинаковое.
TECH = {
    "Dart": ("lang", "dart"), "Kotlin": ("lang", "kotlin"), "Java": ("lang", "openjdk"),
    "Python": ("lang", "python"), "TypeScript": ("lang", "typescript"),
    "JavaScript": ("lang", "javascript"), "C#": ("lang", "csharp"),
    "Flutter": ("mobile", "flutter"), "BLoC": ("mobile", None), "Android": ("mobile", "android"),
    "React": ("web", "react"), "Vite": ("web", "vite"), "Tailwind CSS": ("web", "tailwindcss"),
    "Three.js": ("web", "threedotjs"), "HTML": ("web", "html5"), "CSS": ("web", None),
    "Spring Boot": ("back", "springboot"), "Node.js": ("back", "nodedotjs"),
    "Fastify": ("back", "fastify"), "Dart Frog": ("back", None),
    "PostgreSQL": ("back", "postgresql"), "SQLite": ("back", "sqlite"),
    "MS SQL Server": ("back", "mssql"), "Liquibase": ("back", "liquibase"),
    "PyTorch": ("ml", "pytorch"), "scikit-learn": ("ml", "scikitlearn"),
    "CatBoost": ("ml", None), "LightGBM": ("ml", None), "pandas": ("ml", "pandas"),
    "Polars": ("ml", "polars"), "NumPy": ("ml", "numpy"), "Jupyter": ("ml", "jupyter"),
    "Streamlit": ("ml", "streamlit"), "Plotly": ("ml", "plotly"),
    "Unity": ("game", "unity"), "HLSL": ("game", None), "libGDX": ("game", None),
    "Telegram Bot API": ("bots", "telegram"), "MAX Bot API": ("bots", None),
    "JUnit 5": ("test", "junit5"), "Testcontainers": ("test", None),
    "pytest": ("test", "pytest"), "Vitest": ("test", "vitest"),
    "Docker": ("infra", "docker"), "GitHub Actions": ("infra", "githubactions"),
    "Gradle": ("infra", "gradle"), "Maven": ("infra", "apachemaven"), "Caddy": ("infra", "caddy"),
    "Git": ("tools", "git"), "Figma": ("tools", "figma"),
    "IntelliJ IDEA": ("tools", "intellijidea"), "VS Code": ("tools", "vscode"),
}

# В коде этого не видно, поэтому указано руками. Число ×N у них не рисуется.
MANUAL = ["Android", "Git", "Figma", "IntelliJ IDEA", "VS Code"]

# Язык считается, если занимает в репозитории не меньше этой доли.
LANGUAGE_SHARE = 0.05
LANGUAGES = {
    "Dart": "Dart", "Kotlin": "Kotlin", "Java": "Java", "Python": "Python",
    "TypeScript": "TypeScript", "JavaScript": "JavaScript", "C#": "C#",
    "HTML": "HTML", "CSS": "CSS", "HLSL": "HLSL",
    "Jupyter Notebook": "Jupyter",
}
NPM = {
    "react": ["React"], "vite": ["Vite"], "tailwindcss": ["Tailwind CSS"],
    "@tailwindcss/vite": ["Tailwind CSS"], "three": ["Three.js"],
    "typescript": ["TypeScript"], "vitest": ["Vitest"],
    "fastify": ["Fastify", "Node.js"], "express": ["Node.js"], "koa": ["Node.js"],
    "@nestjs/core": ["Node.js"], "@maxhub/max-bot-api": ["MAX Bot API"],
}
PYPI = {
    "torch": "PyTorch", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "catboost": "CatBoost", "lightgbm": "LightGBM", "pandas": "pandas",
    "polars": "Polars", "numpy": "NumPy", "streamlit": "Streamlit", "plotly": "Plotly",
    "pytest": "pytest", "jupyter": "Jupyter", "notebook": "Jupyter",
    "python-telegram-bot": "Telegram Bot API", "telethon": "Telegram Bot API",
    "aiogram": "Telegram Bot API", "pytelegrambotapi": "Telegram Bot API",
}
PUB = {
    "flutter": "Flutter", "flutter_bloc": "BLoC", "bloc": "BLoC",
    "dart_frog": "Dart Frog", "postgres": "PostgreSQL", "sqflite": "SQLite",
}
JVM = {
    "org.springframework.boot": "Spring Boot", "liquibase": "Liquibase",
    "testcontainers": "Testcontainers", "org.postgresql": "PostgreSQL", "mssql-jdbc": "MS SQL Server",
    "telegrambots": "Telegram Bot API", "com.badlogicgames.gdx": "libGDX",
    "gdxversion": "libGDX",
}
# (шаблон пути, технология, сколько файлов нужно как минимум)
FILES = [
    (r"(^|/)ProjectSettings/ProjectVersion\.txt$", "Unity", 1),
    (r"(^|/)(Dockerfile|compose\.ya?ml|docker-compose\.ya?ml)$", "Docker", 1),
    (r"^\.github/workflows/[^/]+\.ya?ml$", "GitHub Actions", 1),
    (r"(^|/)build\.gradle(\.kts)?$", "Gradle", 1),
    (r"(^|/)pom\.xml$", "Maven", 1),
    (r"\.ipynb$", "Jupyter", 1),
    # GitHub иногда не считает языки у репозитория — TypeScript видно по исходникам
    (r"(^|/)src/.+(?<!\.d)\.tsx?$", "TypeScript", 3),
    # Spring Initializr сам кладёт пустой ApplicationTests — его не считаем
    (r"(^|/)src/test/.+(?<!Application)Tests?\.(java|kt)$", "JUnit 5", 1),
]
IMAGES = {"postgres": "PostgreSQL", "caddy": "Caddy"}

MANIFEST = re.compile(r"(^|/)(package\.json|requirements[^/]*\.txt|pyproject\.toml|pubspec\.yaml"
                      r"|build\.gradle(\.kts)?|pom\.xml|gradle\.properties"
                      r"|compose\.ya?ml|docker-compose\.ya?ml)$")
# Зависимости, вендоринг и временные копии чужого кода — не доказательство.
SKIP = re.compile(r"(^|/)(node_modules|\.venv|venv|vendor|Library|build|dist|\.dart_tool"
                  r"|temp[^/]*|third_party|android|ios|macos|linux|windows)/")
MAX_MANIFESTS = 30


def http_get(url: str, token: str | None = None) -> bytes | None:
    headers = {"User-Agent": "profile-builder"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=30) as response:
            return response.read()
    except Exception as error:  # сетевой сбой по одному файлу не должен ронять сборку
        print(f"  пропущено {url}: {error}")
        return None


def pypi_names(text: str, filename: str) -> set[str]:
    names: list[str] = []
    if filename.endswith(".toml"):
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return set()
        project = data.get("project", {})
        names += project.get("dependencies", [])
        for group in project.get("optional-dependencies", {}).values():
            names += group
        names += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    else:
        names = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    result = set()
    for name in names:
        match = re.match(r"[A-Za-z0-9_.\-]+", name.strip())
        if match and not name.strip().startswith("-"):
            result.add(match.group(0).lower().replace("_", "-"))
    return result


def techs_in_manifest(path: str, text: str) -> set[str]:
    filename = path.rsplit("/", 1)[-1]
    found: set[str] = set()
    if filename == "package.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return found
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name in data.get(section) or {}:
                found.update(NPM.get(name, []))
    elif filename.startswith("requirements") or filename == "pyproject.toml":
        found.update(PYPI[name] for name in pypi_names(text, filename) if name in PYPI)
    elif filename == "pubspec.yaml":
        for name in re.findall(r"^ {2}([a-z0-9_]+):", text, flags=re.M):
            if name in PUB:
                found.add(PUB[name])
    elif filename in ("build.gradle", "build.gradle.kts", "pom.xml", "gradle.properties"):
        lowered = text.lower()
        found.update(tech for needle, tech in JVM.items() if needle in lowered)
    else:  # compose-файлы: смотрим, какие образы поднимаются
        for image in re.findall(r"image:\s*['\"]?([a-z0-9./-]+)", text):
            base = image.rsplit("/", 1)[-1]
            found.update(tech for needle, tech in IMAGES.items() if base.startswith(needle))
    return found


def detect_stack(login: str, user: dict, token: str) -> dict[str, set[str]]:
    """Технология → множество публичных репозиториев, где она подключена."""
    stack: dict[str, set[str]] = {}

    def add(tech: str, repo: str) -> None:
        if tech in TECH:
            stack.setdefault(tech, set()).add(repo)

    for repo in user["repositories"]["nodes"]:
        name, branch = repo["name"], (repo.get("defaultBranchRef") or {}).get("name")
        if name.lower() == login.lower() or not branch:
            continue  # репозиторий профиля сам себя не доказывает; пустые пропускаем

        sizes = {e["node"]["name"]: e["size"] for e in repo["languages"]["edges"]}
        total = sum(sizes.values()) or 1
        for language, size in sizes.items():
            if language in LANGUAGES and size / total >= LANGUAGE_SHARE:
                add(LANGUAGES[language], name)

        raw_tree = http_get(f"https://api.github.com/repos/{login}/{name}/git/trees/"
                            f"{urllib.parse.quote(branch)}?recursive=1", token)
        if not raw_tree:
            continue
        paths = [item["path"] for item in json.loads(raw_tree).get("tree", [])
                 if item.get("type") == "blob" and not SKIP.search(item["path"])]

        for pattern, tech, minimum in FILES:
            if sum(1 for path in paths if re.search(pattern, path)) >= minimum:
                add(tech, name)

        manifests = [path for path in paths if MANIFEST.search(path)
                     and "lock" not in path.rsplit("/", 1)[-1]][:MAX_MANIFESTS]
        for path in manifests:
            body = http_get(f"https://raw.githubusercontent.com/{login}/{name}/"
                            f"{urllib.parse.quote(branch)}/{urllib.parse.quote(path)}")
            if body:
                for tech in techs_in_manifest(path, body.decode("utf-8", "replace")):
                    add(tech, name)

    for tech in MANUAL:
        stack.setdefault(tech, set())
    return stack


def directions(stack: dict[str, set[str]]) -> str:
    """Подзаголовок шапки: направления, в которых есть хоть одна технология."""
    present = {TECH[tech][0] for tech, repos in stack.items() if repos}
    return " · ".join(short for key, _, short in CATEGORIES if short and key in present)


def wrap_balanced(widths: list[float], limit: float, gap: float) -> list[list[int]]:
    """Перенос по строкам так, чтобы строки были близки по длине.

    Жадный перенос оставляет на последней строке один сиротливый пункт;
    здесь сначала считается, сколько строк нужно, а потом ширина строки
    подбирается минимальной, при которой пункты в это число строк влезают.
    """
    def greedy(width_limit: float) -> list[list[int]]:
        lines, current, used = [], [], 0.0
        for index, width in enumerate(widths):
            extra = width if not current else gap + width
            if current and used + extra > width_limit:
                lines.append(current)
                current, used = [index], width
            else:
                current.append(index)
                used += extra
        return lines + [current] if current else lines

    target = len(greedy(limit))
    total = sum(widths) + gap * (len(widths) - 1)
    width_limit = max(max(widths), total / target)
    while width_limit < limit:
        lines = greedy(width_limit)
        if len(lines) <= target:
            return lines
        width_limit += 4
    return greedy(limit)


def build_stack(stack: dict[str, set[str]], dark: bool) -> str:
    colors = palette(dark)
    icons = json.loads(ICONS.read_text(encoding="utf-8"))["icons"]
    order = list(TECH)

    item_size, count_size, icon = 12.5, 10.5, 14
    char, count_char = item_size * 0.6, count_size * 0.6  # моноширинная: 600/1000 em
    items_x, line_h, gap = 150, 28, 22

    def width_of(tech: str) -> float:
        count = len(stack[tech])
        suffix = 4 + len(f"×{count}") * count_char if count >= 2 else 0
        return icon + 7 + len(tech) * char + suffix

    rows: list[str] = []
    y = 44
    for key, title, _ in CATEGORIES:
        techs = sorted((t for t in stack if TECH[t][0] == key),
                       key=lambda t: (-len(stack[t]), order.index(t)))
        if not techs:
            continue
        rows.append(f'<text class="lab" x="0" y="{y + 17}">{title}</text>')
        lines = wrap_balanced([width_of(t) for t in techs], W - items_x, gap)
        for line_no, line in enumerate(lines):
            top, x = y + line_no * line_h, items_x
            for index in line:
                tech = techs[index]
                slug = TECH[tech][1]
                if slug and slug in icons:
                    box, path = icons[slug]
                    rows.append(f'<path transform="translate({x:.1f} {top + 5}) '
                                f'scale({icon / box:.5f})" d="{path}" fill="{colors["muted"]}"/>')
                else:
                    # Логотипа нет ни в одном открытом наборе — ставим точку-маркер.
                    # Пустой квадрат пробовали: читается как неотмеченный чекбокс.
                    rows.append(f'<circle cx="{x + icon / 2:.1f}" cy="{top + 12}" r="2.4" '
                                f'fill="{colors["muted"]}"/>')
                text_x = x + icon + 7
                rows.append(f'<text class="item" x="{text_x:.1f}" y="{top + 17}">{tech}</text>')
                if len(stack[tech]) >= 2:
                    rows.append(f'<text class="cnt" x="{text_x + len(tech) * char + 4:.1f}" '
                                f'y="{top + 17}">×{len(stack[tech])}</text>')
                x += width_of(tech) + gap
        y += len(lines) * line_h + 8

    height = y + 4
    repos = len({repo for repos in stack.values() for repo in repos})
    alt = "Стек: " + "; ".join(
        f"{title.capitalize()} — " + ", ".join(t for t in stack if TECH[t][0] == key)
        for key, title, _ in CATEGORIES if any(TECH[t][0] == key for t in stack))
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="{alt}">',
        f"<style>{font_face()}{styles(colors)}"
        f".item{{font-weight:400;font-size:{item_size}px;fill:{colors['text']};}}"
        f".cnt{{font-weight:400;font-size:{count_size}px;fill:{colors['muted']};}}</style>",
        f'<line class="rule" x1="0" y1="0.5" x2="{W}" y2="0.5"/>',
        '<text class="lab" x="0" y="24">СТЕК</text>',
        f'<text class="cap" x="{W}" y="24" text-anchor="end">'
        f'собран из кода {repos} репозиториев · ×N — в скольких используется</text>',
    ]
    return "\n".join(head + rows + ["</svg>"]) + "\n"


# Подписи разделов повторяют строку-заголовок внутри шапки: линейка, слева
# название капителью, справа пояснение. Так виджеты разных сервисов читаются
# как продолжение одного листа, а не как набор чужих картинок.
SECTIONS = {
    "stats": ("СТАТИСТИКА", "github-readme-stats · streak-stats"),
    "farm": ("ФЕРМА", "gitanimals · новый питомец за каждые 30 коммитов"),
    "quote": ("ЦИТАТА", "каждый показ — новая"),
}


def build_section(title: str, caption: str, dark: bool) -> str:
    colors = palette(dark)
    height = 34
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" role="img" aria-label="{title.capitalize()}">',
        f"<style>{font_face()}{styles(colors)}</style>",
        f'<line class="rule" x1="0" y1="0.5" x2="{W}" y2="0.5"/>',
        f'<text class="lab" x="0" y="24">{title}</text>',
        f'<text class="cap" x="{W}" y="24" text-anchor="end">{caption}</text>',
        "</svg>",
    ]) + "\n"


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
    stack = detect_stack(login, user, token)
    detected = sum(1 for repos in stack.values() if repos)
    # Если API не ответил, лучше оставить вчерашнюю панель, чем нарисовать пустую.
    stack_ok = detected >= 5

    ASSETS.mkdir(parents=True, exist_ok=True)
    subtitle = directions(stack) if stack_ok else "мобайл · веб · бэкенд"
    for dark, suffix in ((True, "dark"), (False, "light")):
        (ASSETS / f"hero-{suffix}.svg").write_text(
            build_hero(login, user, dark, subtitle), encoding="utf-8")
        if stack_ok:
            (ASSETS / f"stack-{suffix}.svg").write_text(build_stack(stack, dark), encoding="utf-8")
        for key, (title, caption) in SECTIONS.items():
            (ASSETS / f"section-{key}-{suffix}.svg").write_text(
                build_section(title, caption, dark), encoding="utf-8")

    if stack_ok:
        report = {tech: sorted(repos) for tech, repos in
                  sorted(stack.items(), key=lambda item: (TECH[item[0]][0], -len(item[1])))}
        (ASSETS / "stack.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    build_board_cells()
    print(f"Собрано: шапка, стек ({detected} технологий из кода"
          f"{'' if stack_ok else ' — мало, панель не обновлена'}), подписи разделов")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
