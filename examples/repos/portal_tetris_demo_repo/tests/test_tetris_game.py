from __future__ import annotations

import unittest

from game.tetris import TetrisGame


class TetrisGameTests(unittest.TestCase):
    def test_spawn_move_and_render_square_piece(self) -> None:
        game = TetrisGame(width=6, height=6)

        game.spawn_piece("O")
        game.move_left()

        lines = game.render().splitlines()
        self.assertEqual(lines[0], "score=0 lines=0")
        self.assertEqual(lines[1], ".@@...")
        self.assertEqual(lines[2], ".@@...")

    def test_rotate_i_piece_and_drop_locks_cells(self) -> None:
        game = TetrisGame(width=6, height=6)

        game.spawn_piece("I")
        game.rotate_clockwise()
        game.hard_drop()

        lines = game.render().splitlines()
        self.assertEqual(lines[0], "score=2 lines=0")
        self.assertEqual(lines[-1], ".####.")
        self.assertEqual(lines[-2], "......")

    def test_clearing_a_line_updates_score_and_line_count(self) -> None:
        game = TetrisGame(
            width=6,
            height=6,
            locked_rows=(
                "......",
                "......",
                "......",
                "......",
                "......",
                "####..",
            ),
        )

        game.spawn_piece("O")
        game.move_right()
        game.move_right()
        game.hard_drop()

        lines = game.render().splitlines()
        self.assertEqual(lines[0], "score=102 lines=1")
        self.assertEqual(lines[-1], "....##")


if __name__ == "__main__":
    unittest.main()