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
    engage_frames: int = 3
    release_frames: int = 5
    pinch_frames: int = 2
    paste_frames: int = 9
    close_frames: int = 30
    min_cutoff: float = 1.0
    beta: float = 10.0
    pinch_ratio: float = 0.35
    scroll_dead_zone: float = 0.03
    scroll_speed: float = 80.0
    zoom_dead_zone: float = 0.1
    zoom_speed: float = 10.0
    palms_cooldown_frames: int = 15
    swipe_distance: float = 0.25
    slider_step: float = 0.013
    swipe_frames: int = 10
    swipe_cooldown_frames: int = 15
    head_touch_frames: int = 15
    head_range: float = 0.12
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
        if not 0 < self.slider_step < 0.5:
            raise ValueError(f"need 0 < slider_step < 0.5, got {self.slider_step}")
        if not 0 < self.head_range <= 1:
            raise ValueError(f"need 0 < head_range <= 1, got {self.head_range}")
        if not (0 < self.swipe_distance < 1 and self.swipe_frames >= 2):
            raise ValueError(
                f"need 0 < swipe_distance < 1 and swipe_frames >= 2, got {self.swipe_distance} and {self.swipe_frames}"
            )
