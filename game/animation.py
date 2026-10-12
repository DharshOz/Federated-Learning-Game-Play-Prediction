import pygame
import os
import glob


def load_sequence(folder_path, prefix=None, ext=".png"):
    """Load a sorted sequence of PNG frames from a folder into a list of Surfaces."""
    files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(ext)])
    if prefix:
        files = [f for f in files if os.path.basename(f).startswith(prefix)]
    frames = []
    for f in files:
        img = pygame.image.load(os.path.join(folder_path, f)).convert_alpha()
        frames.append(img)
    return frames


def load_spritesheet_row(sheet_path, frame_w, frame_h, num_frames, scale=1):
    """Load frames from a horizontal spritesheet PNG."""
    sheet = pygame.image.load(sheet_path).convert_alpha()
    frames = []
    for i in range(num_frames):
        surf = pygame.Surface((frame_w, frame_h), pygame.SRCALPHA)
        surf.blit(sheet, (0, 0), (i * frame_w, 0, frame_w, frame_h))
        if scale != 1:
            surf = pygame.transform.scale(surf, (frame_w * scale, frame_h * scale))
        surf.set_colorkey((0, 0, 0))
        frames.append(surf)
    return frames


class AnimatedSprite:
    """Manages a set of named animation sequences for a character."""

    def __init__(self, animations: dict, default_anim="idle", frame_delay=80):
        """
        animations: dict of anim_name -> list of Surfaces
        frame_delay: ms per frame
        """
        self.animations = animations
        self.current = default_anim
        self.frame = 0
        self.last_update = 0
        self.frame_delay = frame_delay
        self.done = False         # True when a one-shot animation completes
        self.loop = True          # Whether current anim loops
        self._queued = None       # Next anim to play after current ends

    def play(self, name, loop=True, then=None):
        """Switch to animation 'name'. then=anim to queue after."""
        if name not in self.animations:
            return
        if self.current == name and self.loop == loop:
            return
        self.current = name
        self.frame = 0
        self.done = False
        self.loop = loop
        self._queued = then

    def update(self, now):
        """Advance animation frame. Returns True if a one-shot just finished."""
        if now - self.last_update < self.frame_delay:
            return False
        self.last_update = now
        frames = self.animations.get(self.current, [])
        if not frames:
            return False
        self.frame += 1
        if self.frame >= len(frames):
            if self.loop:
                self.frame = 0
            else:
                self.frame = len(frames) - 1
                self.done = True
                if self._queued:
                    self.play(self._queued, loop=True)
                    self._queued = None
                    return True
        return False

    def get_surface(self):
        frames = self.animations.get(self.current, [])
        if not frames:
            return None
        return frames[min(self.frame, len(frames) - 1)]

    def is_done(self):
        return self.done


class EffectAnimation:
    """A one-shot, self-disposing particle / spell effect."""

    def __init__(self, frames, pos, scale=1, frame_delay=60):
        self.frames = frames
        if scale != 1:
            w = int(frames[0].get_width() * scale)
            h = int(frames[0].get_height() * scale)
            self.frames = [pygame.transform.scale(f, (w, h)) for f in frames]
        self.pos = pos
        self.frame = 0
        self.last_update = 0
        self.frame_delay = frame_delay
        self.finished = False

    def update(self, now):
        if self.finished:
            return
        if now - self.last_update >= self.frame_delay:
            self.last_update = now
            self.frame += 1
            if self.frame >= len(self.frames):
                self.finished = True

    def draw(self, surface):
        if not self.finished and self.frame < len(self.frames):
            img = self.frames[self.frame]
            rect = img.get_rect(center=self.pos)
            surface.blit(img, rect)
