from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    """Box of the camera frame (normalized 0..1) that maps onto the whole screen.

    Smaller than the frame so the screen edges are reachable without the hand
    leaving the camera's view.
    """

    left: float = 0.25
    top: float = 0.2
    right: float = 0.75
    bottom: float = 0.7

    def __post_init__(self) -> None:
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1):
            raise ValueError(f"invalid region {self}: need 0 <= left < right <= 1 and 0 <= top < bottom <= 1")

    def normalize(self, x: float, y: float) -> tuple[float, float]:
        """Camera coordinates -> screen coordinates, both 0..1, clamped to the edges."""
        u = (x - self.left) / (self.right - self.left)
        v = (y - self.top) / (self.bottom - self.top)
        return min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)


@dataclass(frozen=True)
class Settings:
    camera: int = 0
    width: int = 640
    height: int = 480
    region: Region = field(default_factory=Region)
    min_gesture_score: float = 0.5
    # Frames a pose must hold before the cursor engages / disengages.
    engage_frames: int = 3
    release_frames: int = 5
    # Frames a pinch must hold / stay open to press / release: shorter than the above so double clicks fit.
    pinch_frames: int = 2
    # Frames a 👎 must hold before it pastes: longer than engage_frames, a stray paste does more harm than a copy.
    paste_frames: int = 9
    # Frames a 🤟 must hold before it closes the window (~1 s): closing can lose work.
    close_frames: int = 30
    # One Euro filter, in screen units (0..1): lower min_cutoff = less jitter, higher beta = less lag.
    min_cutoff: float = 1.0
    beta: float = 10.0
    # Pinch = thumb-index tip distance below this fraction of the hand size; holds the left button (click or drag).
    pinch_ratio: float = 0.35
    # Two open palms scroll: the driver hand moving past the dead zone (fraction of the frame height) from where
    # the palms opened scrolls at scroll_speed wheel clicks per second per frame height beyond it.
    scroll_dead_zone: float = 0.03
    scroll_speed: float = 80.0
    # Two open palms zoom (Ctrl+wheel): their horizontal gap changing past the dead zone (log of the ratio to the
    # gap where they opened, ~fraction) zooms at zoom_speed wheel clicks per second per unit beyond it.
    zoom_dead_zone: float = 0.1
    zoom_speed: float = 10.0
    # One open palm moved sideways by swipe_distance (fraction of the frame width) within swipe_frames switches
    # workspace; then swipes are ignored for swipe_cooldown_frames, so the hand swinging back does not undo it.
    swipe_distance: float = 0.25
    swipe_frames: int = 10
    swipe_cooldown_frames: int = 15
    preview: bool = False

    def __post_init__(self) -> None:
        if not (self.min_cutoff > 0 and self.beta >= 0):
            raise ValueError(f"need min_cutoff > 0 and beta >= 0, got {self.min_cutoff} and {self.beta}")
        if not 0 < self.pinch_ratio < 1:
            raise ValueError(f"need 0 < pinch_ratio < 1, got {self.pinch_ratio}")
        if not (0 <= self.scroll_dead_zone < 0.5 and self.scroll_speed > 0):
            raise ValueError(
                f"need 0 <= scroll_dead_zone < 0.5 and scroll_speed > 0, "
                f"got {self.scroll_dead_zone} and {self.scroll_speed}"
            )
        if not (0 <= self.zoom_dead_zone < 1 and self.zoom_speed > 0):
            raise ValueError(
                f"need 0 <= zoom_dead_zone < 1 and zoom_speed > 0, got {self.zoom_dead_zone} and {self.zoom_speed}"
            )
        if not (0 < self.swipe_distance < 1 and self.swipe_frames >= 2):
            raise ValueError(
                f"need 0 < swipe_distance < 1 and swipe_frames >= 2, got {self.swipe_distance} and {self.swipe_frames}"
            )
