"""Physical GPIO button monitor for triggering BLE setup mode on Raspberry Pi."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class GpioButtonHandler:
    """Monitors a physical button connected between a GPIO pin and GND.

    When the button is pressed (falling edge), debounces the signal and
    triggers the provided `on_press` callback (typically activating BLE setup mode).
    """

    def __init__(
        self,
        pin: int = 26,
        chip_path: str = "/dev/gpiochip0",
        debounce_ms: int = 150,
        on_press: Callable[[], None] | None = None,
    ) -> None:
        """Initialize GPIO button handler.

        Args:
            pin: Broadcom GPIO pin number (default: 26).
            chip_path: Path to GPIO character device.
            debounce_ms: Debounce threshold in milliseconds.
            on_press: Callback invoked when button is pressed.
        """
        self.pin = pin
        self.chip_path = chip_path
        self.debounce_ms = debounce_ms
        self.on_press = on_press
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_active = False

    @property
    def is_active(self) -> bool:
        """Return True if background monitoring is running."""
        return self._is_active

    def trigger_button_press(self) -> None:
        """Manually trigger button press event (for testing or software trigger)."""
        logger.info("GPIO button press triggered on pin %d", self.pin)
        if self.on_press:
            try:
                self.on_press()
            except Exception:
                logger.exception("Error in GPIO button on_press callback")

    def start(self) -> bool:
        """Start monitoring in a daemon background thread.

        Returns True if hardware monitoring started, False if falling back to software mode.
        """
        if self._thread and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._is_active = True

        # Check for gpiod availability
        try:
            import gpiod

            has_gpiod = True
        except ImportError:
            has_gpiod = False
            gpiod = None

        if not has_gpiod:
            logger.info(
                "gpiod not available in current environment. GPIO button monitoring on pin %d running in software/mock mode.",
                self.pin,
            )
            return False

        def _monitor_loop() -> None:
            try:
                # Attempt libgpiod v2 API
                if hasattr(gpiod, "request_lines"):
                    line_settings = gpiod.LineSettings(
                        direction=gpiod.line.Direction.INPUT,
                        bias=gpiod.line.Bias.PULL_UP,
                        edge_detection=gpiod.line.Edge.FALLING,
                        debounce_period=time.monotonic(),  # non-zero dummy
                    )
                    with gpiod.request_lines(
                        self.chip_path,
                        consumer="snippen-doorman-button",
                        config={self.pin: line_settings},
                    ) as request:
                        logger.info(
                            "GPIO button monitoring started on pin %d via gpiod v2", self.pin
                        )
                        last_press = 0.0
                        while not self._stop_event.is_set():
                            if request.wait_edge_events(timeout=0.5):
                                for _ in request.read_edge_events():
                                    now = time.monotonic()
                                    if (now - last_press) * 1000 >= self.debounce_ms:
                                        last_press = now
                                        self.trigger_button_press()
                else:
                    logger.info(
                        "gpiod v1 detected or unsupported layout. Running in fallback mode."
                    )
            except (OSError, RuntimeError) as exc:
                logger.warning(
                    "Could not initialize hardware GPIO monitoring on pin %d: %s. Software trigger remains available.",
                    self.pin,
                    exc,
                )

        self._thread = threading.Thread(
            target=_monitor_loop, name=f"gpio-button-{self.pin}", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop background GPIO monitoring thread."""
        self._stop_event.set()
        self._is_active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        logger.debug("GPIO button handler stopped")
