"""Unit tests for GpioButtonHandler."""

from __future__ import annotations

from snippen_doorman.gpio_button import GpioButtonHandler


def test_gpio_button_trigger_callback() -> None:
    press_count = 0

    def on_press() -> None:
        nonlocal press_count
        press_count += 1

    handler = GpioButtonHandler(pin=26, on_press=on_press)
    assert handler.is_active is False

    handler.trigger_button_press()
    assert press_count == 1

    handler.trigger_button_press()
    assert press_count == 2


def test_gpio_button_start_stop() -> None:
    handler = GpioButtonHandler(pin=26)
    handler.start()
    assert handler.is_active is True

    handler.stop()
    assert handler.is_active is False
