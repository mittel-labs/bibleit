from __future__ import annotations

from bibleit.ui.status import StatusBar


class OverlayStatusMixin:
    def _refresh_status(self) -> None:
        from bibleit.ui.bible_view import BibleView

        try:
            bible_view = self.app.query_exactly_one(BibleView)
            status = self.query_exactly_one(StatusBar)
        except Exception:
            return

        status.translations = [view.translation.slug for view in bible_view.views]
        active_view = bible_view._active_view()
        status.active_translation = active_view.translation.slug if active_view is not None else ""
        status.maximized_translation = (
            bible_view.maximized_view.translation.slug
            if bible_view.maximized_view is not None
            else ""
        )
        status.strongs = any(view.show_strongs for view in bible_view.views)
        status.live = bible_view.state.live
