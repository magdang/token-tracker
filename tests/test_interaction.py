import unittest
from unittest.mock import Mock

from token_tracker.interaction import HoverState


class HoverTests(unittest.TestCase):
    def setUp(self):
        self.schedule = Mock(return_value=1)
        self.cancel = Mock()
        self.show = Mock()
        self.hide = Mock()
        self.hover = HoverState(self.schedule, self.cancel, self.show, self.hide)

    def test_hover_opens(self):
        self.hover.enter("button")
        self.show.assert_called_once()
        self.hide.assert_not_called()

    def test_crossing_gap_does_not_close(self):
        self.hover.enter("button")
        self.hover.leave("button")
        self.schedule.assert_called_once_with(180, self.hover.close_if_outside)
        self.hover.enter("panel")
        self.cancel.assert_called_once_with(1)
        self.hide.assert_not_called()

    def test_leaving_both_closes(self):
        self.hover.enter("button")
        self.hover.leave("button")
        self.hover.close_if_outside()
        self.hide.assert_called_once()

    def test_entering_child_does_not_close(self):
        self.hover.enter("panel")
        self.hover.enter("button")
        self.hover.leave("button")
        self.schedule.assert_not_called()

    def test_escape_clears_pending_close(self):
        self.hover.enter("button")
        self.hover.leave("button")
        self.hover.dismiss()
        self.cancel.assert_called_once_with(1)
        self.assertFalse(self.hover.inside)
        self.hide.assert_called_once()
