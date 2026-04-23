# Terminal Tetris Demo Repo

This repository is the default live-portal example for Repo Harness Lab.

Goal:
- implement the missing Tetris logic in `game/tetris.py`
- keep `tests/test_tetris_game.py` unchanged
- make `python -m unittest tests.test_tetris_game -q` pass

What the finished demo should support:
- spawning an `O` piece and an `I` piece
- moving the active piece left and right inside the board
- rotating the `I` piece clockwise
- hard-dropping the active piece so it becomes locked
- clearing full lines and updating the score
- rendering a text frame with the score line followed by the board

Quick run:

```powershell
python -m unittest tests.test_tetris_game -q
python -m game.tetris
```