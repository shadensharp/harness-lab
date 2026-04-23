"""Minimal Tetris stub used by the Repo Harness Lab live portal demo."""

from __future__ import annotations


class TetrisGame:
    def __init__(self, width: int = 6, height: int = 8, locked_rows: tuple[str, ...] | list[str] | None = None) -> None:
        self.width = width
        self.height = height
        self.locked_rows = tuple(locked_rows or ("." * width for _ in range(height)))
        self.score = 0
        self.lines_cleared = 0
        self.active_name: str | None = None

    def spawn_piece(self, name: str) -> None:
        raise NotImplementedError("Implement piece spawning.")

    def move_left(self) -> None:
        raise NotImplementedError("Implement left movement.")

    def move_right(self) -> None:
        raise NotImplementedError("Implement right movement.")

    def rotate_clockwise(self) -> None:
        raise NotImplementedError("Implement clockwise rotation.")

    def hard_drop(self) -> None:
        raise NotImplementedError("Implement hard drop and locking.")

    def clear_full_lines(self) -> int:
        raise NotImplementedError("Implement line clear scoring.")

    def render(self) -> str:
        raise NotImplementedError("Implement text rendering.")


def main() -> None:
    game = TetrisGame()
    game.spawn_piece("O")
    print(game.render())


if __name__ == "__main__":
    main()