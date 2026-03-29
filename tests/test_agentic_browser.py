from __future__ import annotations

import unittest

from app.agentic_browser import (
    PlaywrightComputerHarness,
    _normalize_key,
    extract_computer_call,
    extract_output_text,
    extract_reasoning_summary,
)


class FakeMouse:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def click(self, x, y, button="left") -> None:
        self.calls.append(("click", x, y, button))

    def dblclick(self, x, y, button="left") -> None:
        self.calls.append(("double_click", x, y, button))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))

    def wheel(self, dx, dy) -> None:
        self.calls.append(("wheel", dx, dy))

    def down(self) -> None:
        self.calls.append(("down",))

    def up(self) -> None:
        self.calls.append(("up",))


class FakeKeyboard:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def press(self, key) -> None:
        self.calls.append(("press", key))

    def type(self, text) -> None:
        self.calls.append(("type", text))


class FakePage:
    def __init__(self) -> None:
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()


class AgenticBrowserTests(unittest.TestCase):
    def test_extract_helpers(self) -> None:
        response = {
            "output_text": "",
            "output": [
                {"type": "reasoning", "summary": [{"text": "Inspecting the board."}]},
                {"type": "computer_call", "call_id": "call_123", "actions": [{"type": "screenshot"}]},
                {"type": "message", "content": [{"text": "Solved in 4 guesses."}]},
            ],
        }
        self.assertEqual(extract_reasoning_summary(response), "Inspecting the board.")
        self.assertEqual(extract_computer_call(response)["call_id"], "call_123")
        self.assertEqual(extract_output_text(response), "Solved in 4 guesses.")

    def test_apply_action_dispatches_supported_actions(self) -> None:
        page = FakePage()
        PlaywrightComputerHarness.apply_action(page, {"type": "click", "x": 10, "y": 20, "button": "left"})
        PlaywrightComputerHarness.apply_action(page, {"type": "double_click", "x": 30, "y": 40, "button": "right"})
        PlaywrightComputerHarness.apply_action(page, {"type": "scroll", "x": 50, "y": 60, "scroll_x": 0, "scroll_y": 400})
        PlaywrightComputerHarness.apply_action(page, {"type": "keypress", "keys": ["A", "SPACE", "Enter"]})
        PlaywrightComputerHarness.apply_action(page, {"type": "type", "text": "crane"})
        PlaywrightComputerHarness.apply_action(page, {"type": "move", "x": 70, "y": 80})
        PlaywrightComputerHarness.apply_action(
            page,
            {"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}]},
        )
        PlaywrightComputerHarness.apply_action(page, {"type": "screenshot"})

        self.assertIn(("click", 10, 20, "left"), page.mouse.calls)
        self.assertIn(("double_click", 30, 40, "right"), page.mouse.calls)
        self.assertIn(("move", 50, 60), page.mouse.calls)
        self.assertIn(("wheel", 0, 400), page.mouse.calls)
        self.assertIn(("press", "A"), page.keyboard.calls)
        self.assertIn(("press", " "), page.keyboard.calls)
        self.assertIn(("press", "Enter"), page.keyboard.calls)
        self.assertIn(("type", "crane"), page.keyboard.calls)
        self.assertIn(("down",), page.mouse.calls)
        self.assertIn(("up",), page.mouse.calls)

    def test_normalize_key_maps_computer_use_names(self) -> None:
        self.assertEqual(_normalize_key("ENTER"), "Enter")
        self.assertEqual(_normalize_key("SPACE"), " ")
        self.assertEqual(_normalize_key("LEFT"), "ArrowLeft")
        self.assertEqual(_normalize_key("a"), "a")


if __name__ == "__main__":
    unittest.main()
