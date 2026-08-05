#!/usr/bin/env python3
"""Крестики-нолики, в которые играют прямо со страницы профиля.

Посетитель кликает по пустой клетке -> открывается issue с заголовком
`ttt|move|<0-8>` -> GitHub Action запускает этот скрипт -> он делает ход,
отвечает за бота и перерисовывает доску в README.md.

Команды:
    py game/tictactoe.py render                 — просто перерисовать доску
    py game/tictactoe.py move <0-8> [игрок]     — ход человека + ответ бота
    py game/tictactoe.py new                    — новая партия
"""

from __future__ import annotations

import json
import os
import random
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "game" / "state.json"
README_PATH = ROOT / "README.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "imaO0O/imaO0O")

HUMAN, BOT, EMPTY = "X", "O", " "
MARK = {HUMAN: "❌", BOT: "⭕", EMPTY: "⬜"}
START_MARKER = "<!--TTT_START-->"
END_MARKER = "<!--TTT_END-->"

LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]

# Насколько часто бот "зевает". 0.0 — непобедим и скучен, 1.0 — играет наугад.
BLUNDER_CHANCE = 0.25

DEFAULT_STATE = {
    "board": EMPTY * 9,
    "turn": 1,
    "score": {"players": 0, "bot": 0, "draws": 0},
    "last_player": None,
    "log": [],
}


# ─────────────────────────────── состояние ───────────────────────────────

def load_state() -> dict:
    if not STATE_PATH.exists():
        return json.loads(json.dumps(DEFAULT_STATE))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, value)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ──────────────────────────────── правила ────────────────────────────────

def winner(board: str) -> str | None:
    for a, b, c in LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    return None


def free_cells(board: str) -> list[int]:
    return [i for i, c in enumerate(board) if c == EMPTY]


def place(board: str, index: int, mark: str) -> str:
    return board[:index] + mark + board[index + 1:]


def minimax(board: str, player: str) -> tuple[int, int | None]:
    """Возвращает (оценка позиции для бота, лучший ход)."""
    won = winner(board)
    if won == BOT:
        return 1, None
    if won == HUMAN:
        return -1, None
    options = free_cells(board)
    if not options:
        return 0, None

    scored = []
    for index in options:
        score, _ = minimax(place(board, index, player), HUMAN if player == BOT else BOT)
        scored.append((score, index))

    return max(scored) if player == BOT else min(scored)


def bot_move(board: str) -> int | None:
    options = free_cells(board)
    if not options:
        return None
    if random.random() < BLUNDER_CHANCE:
        return random.choice(options)
    return minimax(board, BOT)[1]


def game_over(board: str) -> bool:
    return winner(board) is not None or not free_cells(board)


# ─────────────────────────────── отрисовка ───────────────────────────────

def issue_url(title: str, body: str) -> str:
    query = urllib.parse.urlencode({"title": title, "body": body})
    return f"https://github.com/{REPO}/issues/new?{query}"


def move_url(index: int) -> str:
    return issue_url(
        f"ttt|move|{index}",
        "Не меняй заголовок — по нему бот поймёт твой ход.\n"
        "Просто нажми «Create new issue». Issue закроется сама.",
    )


def new_game_url() -> str:
    return issue_url(
        "ttt|new",
        "Не меняй заголовок. Нажми «Create new issue», чтобы начать новую партию.",
    )


def render_board(state: dict) -> str:
    board = state["board"]
    won = winner(board)
    finished = game_over(board)

    rows = []
    for row in range(3):
        cells = []
        for col in range(3):
            index = row * 3 + col
            mark = MARK[board[index]]
            if board[index] == EMPTY and not finished:
                cells.append(
                    f'<td align="center" width="80" height="60">'
                    f'<a href="{move_url(index)}" title="сходить сюда">{mark}</a></td>'
                )
            else:
                cells.append(
                    f'<td align="center" width="80" height="60">{mark}</td>'
                )
        rows.append("  <tr>" + "".join(cells) + "</tr>")

    table = '<table align="center">\n' + "\n".join(rows) + "\n</table>"

    # Внутри HTML-блоков GitHub не разбирает markdown, поэтому здесь только теги.
    if won == HUMAN:
        headline = "🎉 <b>Человечество побеждает.</b> Бот ушёл переобучаться."
    elif won == BOT:
        headline = "🤖 <b>Бот выиграл.</b> Он извиняется. Наверное."
    elif finished:
        headline = "🤝 <b>Ничья.</b> Как обычно, когда обе стороны читали одну и ту же книжку."
    else:
        headline = "Твой ход — ты за ❌. Кликни по пустой клетке."

    score = state["score"]
    footer_bits = [
        f"игроки <b>{score['players']}</b> : <b>{score['bot']}</b> бот",
        f"ничьи <b>{score['draws']}</b>",
        f"ход <b>№{state['turn']}</b>",
    ]
    if state.get("last_player"):
        login = state["last_player"]
        footer_bits.append(
            f'последний ход — <a href="https://github.com/{login}">@{login}</a>'
        )

    parts = [
        "<p align=\"center\">" + headline + "</p>",
        "",
        table,
        "",
        "<p align=\"center\">" + " · ".join(footer_bits) + "</p>",
    ]
    if finished:
        parts += [
            "",
            f'<p align="center"><a href="{new_game_url()}">'
            "<b>▶ Начать новую партию</b></a></p>",
        ]
    return "\n".join(parts)


def update_readme(state: dict) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1:
        raise SystemExit(f"В README.md нет маркеров {START_MARKER} / {END_MARKER}")
    new_text = (
        text[: start + len(START_MARKER)]
        + "\n"
        + render_board(state)
        + "\n"
        + text[end:]
    )
    README_PATH.write_text(new_text, encoding="utf-8")


# ──────────────────────────────── команды ────────────────────────────────

def register_result(state: dict) -> None:
    won = winner(state["board"])
    if won == HUMAN:
        state["score"]["players"] += 1
    elif won == BOT:
        state["score"]["bot"] += 1
    else:
        state["score"]["draws"] += 1


def cmd_new(state: dict) -> str:
    state["board"] = EMPTY * 9
    state["turn"] = 1
    state["last_player"] = None
    state["log"] = []
    return "Новая партия. Доска чистая, ты ходишь первым."


def cmd_move(state: dict, raw_index: str, player: str | None) -> str:
    if game_over(state["board"]):
        return "Партия уже закончена — открой issue с заголовком `ttt|new`, чтобы начать заново."

    try:
        index = int(raw_index)
    except ValueError:
        return f"Не понял клетку «{raw_index}». Нужно число от 0 до 8."

    if not 0 <= index <= 8:
        return f"Клетка {index} вне доски. Нужно число от 0 до 8."
    if state["board"][index] != EMPTY:
        return f"Клетка {index} уже занята. Выбери другую."

    state["board"] = place(state["board"], index, HUMAN)
    state["turn"] += 1
    if player:
        state["last_player"] = player
    state["log"].append({"player": player, "cell": index})

    if game_over(state["board"]):
        register_result(state)
        return "Ход принят — и партия закончена!"

    answer = bot_move(state["board"])
    state["board"] = place(state["board"], answer, BOT)
    state["turn"] += 1

    if game_over(state["board"]):
        register_result(state)
        return f"Ход принят. Бот ответил в клетку {answer} — и партия закончена!"

    return f"Ход принят. Бот ответил в клетку {answer}. Твой ход."


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "render"
    state = load_state()

    if command == "render":
        message = "Доска перерисована."
    elif command == "new":
        message = cmd_new(state)
    elif command == "move":
        if len(argv) < 3:
            print("Использование: tictactoe.py move <0-8> [игрок]")
            return 2
        message = cmd_move(state, argv[2], argv[3] if len(argv) > 3 else None)
    else:
        print(f"Неизвестная команда: {command}")
        return 2

    save_state(state)
    update_readme(state)
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
