from __future__ import annotations

import base64
import unittest

from app.agentic_browser import (
    PlaywrightComputerHarness,
    _anthropic_display_dimensions,
    _normalize_anthropic_tool_use,
    _normalize_key,
    _normalize_key_combo,
    extract_anthropic_tool_uses,
    extract_computer_call,
    extract_output_text,
    extract_reasoning_summary,
)


class FakeMouse:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def click(self, x, y, button="left", click_count=1) -> None:
        self.calls.append(("click", x, y, button, click_count))

    def dblclick(self, x, y, button="left") -> None:
        self.calls.append(("double_click", x, y, button))

    def move(self, x, y) -> None:
        self.calls.append(("move", x, y))

    def wheel(self, dx, dy) -> None:
        self.calls.append(("wheel", dx, dy))

    def down(self, button="left") -> None:
        self.calls.append(("down", button))

    def up(self, button="left") -> None:
        self.calls.append(("up", button))


class FakeKeyboard:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def press(self, key) -> None:
        self.calls.append(("press", key))

    def type(self, text) -> None:
        self.calls.append(("type", text))

    def down(self, key) -> None:
        self.calls.append(("down", key))

    def up(self, key) -> None:
        self.calls.append(("up", key))


class FakePage:
    def __init__(self) -> None:
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()

    def screenshot(self, full_page=False) -> bytes:
        return b"fake-image"


class AgenticBrowserTests(unittest.TestCase):
    def test_extract_helpers(self) -> None:
        openai_response = {
            "output_text": "",
            "output": [
                {"type": "reasoning", "summary": [{"text": "Inspecting the board."}]},
                {"type": "computer_call", "call_id": "call_123", "actions": [{"type": "screenshot"}]},
                {"type": "message", "content": [{"text": "Solved in 4 guesses."}]},
            ],
        }
        anthropic_response = {
            "content": [
                {"type": "thinking", "thinking": "Inspecting the board."},
                {"type": "tool_use", "id": "toolu_123", "name": "computer", "input": {"action": "screenshot"}},
                {"type": "text", "text": "Solved in 4 guesses."},
            ]
        }
        self.assertEqual(extract_reasoning_summary(openai_response), "Inspecting the board.")
        self.assertEqual(extract_computer_call(openai_response)["call_id"], "call_123")
        self.assertEqual(extract_output_text(openai_response), "Solved in 4 guesses.")
        self.assertEqual(extract_reasoning_summary(anthropic_response), "Inspecting the board.")
        self.assertEqual(extract_anthropic_tool_uses(anthropic_response)[0]["id"], "toolu_123")
        self.assertEqual(extract_output_text(anthropic_response), "Solved in 4 guesses.")

    def test_apply_action_dispatches_supported_actions(self) -> None:
        page = FakePage()
        PlaywrightComputerHarness.apply_action(page, {"type": "click", "x": 10, "y": 20, "button": "left"})
        PlaywrightComputerHarness.apply_action(page, {"type": "double_click", "x": 30, "y": 40, "button": "right"})
        PlaywrightComputerHarness.apply_action(page, {"type": "triple_click", "x": 31, "y": 41, "button": "left"})
        PlaywrightComputerHarness.apply_action(page, {"type": "scroll", "x": 50, "y": 60, "scroll_x": 0, "scroll_y": 400})
        PlaywrightComputerHarness.apply_action(page, {"type": "keypress", "keys": ["A", "SPACE", "Enter"]})
        PlaywrightComputerHarness.apply_action(page, {"type": "keypress_combo", "combo": "CTRL+s"})
        PlaywrightComputerHarness.apply_action(page, {"type": "type", "text": "crane"})
        PlaywrightComputerHarness.apply_action(page, {"type": "move", "x": 70, "y": 80})
        PlaywrightComputerHarness.apply_action(
            page,
            {"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}]},
        )
        PlaywrightComputerHarness.apply_action(page, {"type": "mouse_down", "button": "left"})
        PlaywrightComputerHarness.apply_action(page, {"type": "mouse_up", "button": "left"})
        PlaywrightComputerHarness.apply_action(page, {"type": "hold_key", "key": "SHIFT", "duration_seconds": 0})
        PlaywrightComputerHarness.apply_action(page, {"type": "screenshot"})

        self.assertIn(("click", 10, 20, "left", 1), page.mouse.calls)
        self.assertIn(("double_click", 30, 40, "right"), page.mouse.calls)
        self.assertIn(("click", 31, 41, "left", 3), page.mouse.calls)
        self.assertIn(("move", 50, 60), page.mouse.calls)
        self.assertIn(("wheel", 0, 400), page.mouse.calls)
        self.assertIn(("press", "A"), page.keyboard.calls)
        self.assertIn(("press", " "), page.keyboard.calls)
        self.assertIn(("press", "Enter"), page.keyboard.calls)
        self.assertIn(("press", "Control+s"), page.keyboard.calls)
        self.assertIn(("type", "crane"), page.keyboard.calls)
        self.assertIn(("down", "left"), page.mouse.calls)
        self.assertIn(("up", "left"), page.mouse.calls)
        self.assertIn(("down", "Shift"), page.keyboard.calls)
        self.assertIn(("up", "Shift"), page.keyboard.calls)

        screenshot_result = PlaywrightComputerHarness.apply_action(page, {"type": "screenshot"})
        self.assertEqual(screenshot_result["type"], "image")
        self.assertEqual(base64.b64decode(screenshot_result["data"]), b"fake-image")

    def test_normalize_key_maps_computer_use_names(self) -> None:
        self.assertEqual(_normalize_key("ENTER"), "Enter")
        self.assertEqual(_normalize_key("SPACE"), " ")
        self.assertEqual(_normalize_key("LEFT"), "ArrowLeft")
        self.assertEqual(_normalize_key("CTRL"), "Control")
        self.assertEqual(_normalize_key("a"), "a")
        self.assertEqual(_normalize_key_combo("ctrl+s"), "Control+s")

    def test_normalize_anthropic_actions(self) -> None:
        self.assertEqual(
            _normalize_anthropic_tool_use({"action": "left_click", "coordinate": [10, 20]}),
            {"type": "click", "x": 10, "y": 20, "button": "left"},
        )
        self.assertEqual(
            _normalize_anthropic_tool_use({"action": "key", "text": "ctrl+s"}),
            {"type": "keypress_combo", "combo": "ctrl+s"},
        )
        self.assertEqual(
            _normalize_anthropic_tool_use({"action": "scroll", "coordinate": [1, 2], "scroll_amount": 300, "scroll_direction": "down"}),
            {"type": "scroll", "x": 1, "y": 2, "scroll_x": 0, "scroll_y": 300},
        )
        self.assertEqual(
            _normalize_anthropic_tool_use({"action": "left_click_drag", "start_coordinate": [1, 2], "end_coordinate": [3, 4]}),
            {"type": "drag", "button": "left", "path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]},
        )

    def test_anthropic_display_dimensions_fit_limits(self) -> None:
        width, height = _anthropic_display_dimensions(1440, 1200)
        self.assertLessEqual(max(width, height), 1568)
        self.assertLessEqual(width * height, 1_150_000)


if __name__ == "__main__":
    unittest.main()
