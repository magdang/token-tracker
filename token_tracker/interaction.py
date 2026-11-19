"""Small, independently testable hover state machine."""


class HoverState:
    def __init__(self, schedule, cancel, show, hide, delay_ms=180):
        self.schedule = schedule
        self.cancel = cancel
        self.show = show
        self.hide = hide
        self.delay_ms = delay_ms
        self.inside = set()
        self.timeout = None

    def enter(self, surface):
        self.inside.add(surface)
        self.cancel_close()
        self.show()

    def leave(self, surface):
        self.inside.discard(surface)
        if not self.inside:
            self.cancel_close()
            self.timeout = self.schedule(self.delay_ms, self.close_if_outside)

    def cancel_close(self):
        if self.timeout is not None:
            self.cancel(self.timeout)
            self.timeout = None

    def close_if_outside(self):
        self.timeout = None
        if not self.inside:
            self.hide()
        return False

    def dismiss(self):
        self.cancel_close()
        self.inside.clear()
        self.hide()
