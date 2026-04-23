# Game Spec

Implement a tiny text-mode Tetris engine in `game/tetris.py`.

Required API:
- `TetrisGame(width=6, height=8, locked_rows=None)`
- `spawn_piece(name)`
- `move_left()`
- `move_right()`
- `rotate_clockwise()`
- `hard_drop()`
- `clear_full_lines()`
- `render()`

Rules:
- Empty cells render as `.`
- The active falling piece renders as `@`
- Locked cells render as `#`
- The first line of `render()` must be `score=<score> lines=<lines_cleared>`
- The remaining lines of `render()` must be the board from top to bottom
- Supported piece names are `O` and `I`
- `O` is a 2x2 square and does not change on rotation
- `I` is a 4-cell line; it should spawn vertically and rotate to horizontal
- New pieces should spawn centered as much as possible near the top row
- `move_left()` and `move_right()` must stop at the board edge or at locked cells
- `hard_drop()` must move the active piece to the lowest valid row, lock it, add `2` score, and then clear full lines
- `clear_full_lines()` must remove any full rows, insert empty rows at the top, add `100` score per cleared row, and update `lines_cleared`

Reference scenarios used by the tests:
- On a 6x6 board, an `O` piece spawns in the middle and should render as a 2x2 block of `@`
- Rotating an `I` piece before dropping it should produce a horizontal row of four locked cells
- If the bottom row starts as `####..`, dropping an `O` piece on the far right should clear one line and leave `....##` on the new bottom row