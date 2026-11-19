"""Project SF2 v14 public/18 coordinates into the frozen sh02v17 layout.

Each copy consumes a field from the SF2 vector and writes the overlapping
coordinates into the checkpoint vector. Gaps represent unavailable features.
The plan is constructed once, then applied with a single NumPy gather.
"""
import numpy as np


class Layout:
    def __init__(self):
        self.source = 0
        self.indices = []

    def field(self, width, trained_width=None):
        size = width if trained_width is None else trained_width
        count = min(width, size)
        self.indices.extend(range(self.source, self.source + count))
        self.indices.extend([-1] * (size - count))
        self.source += width

    def check(self, source, target):
        if (self.source, len(self.indices)) != (source, target):
            raise ValueError(f'layout mismatch: {(self.source, len(self.indices))}')


def public_projection():
    p = Layout()
    field = p.field
    # Regions with version-dependent denominators for normalized IDs.
    normalized = []

    def scaled(width, source_scale, trained_scale, is_id=False):
        start = len(p.indices)
        field(width)
        normalized.append((slice(start, start + width), source_scale, trained_scale, is_id))

    def inventory():
        field(300, 291)  # relic counts
        field(300, 291)  # relic counters
        field(66, 65)    # potion counts
        scaled(12, 66, 65, True)  # belt

    field(38 + 9 + 597 + 6 * 128 + 24)  # run, screen, deck, grid metadata
    for _ in range(8):
        field(631, 632)  # generated grid card, clone bit absent
    field(128)
    inventory()
    field(2 * 92 + 119 * 15 + 96)  # bosses, map, event ID
    for _ in range(8):
        field(6)
        field(300, 291)
    field(8 + 4)
    field(66, 65)
    for _ in range(8):
        field(2)
        field(300, 291)
    scaled(12, 66, 65, True)
    field(8 + 1 + 9 + 1 + 1 + 160 * 18)  # rewards and stolen cards
    for _ in range(4):
        field(631, 632)
    for _ in range(7):
        field(631, 632)
        field(2)
    for _ in range(3):
        field(300, 291)
        field(2)
    for _ in range(3):
        field(66, 65)
        field(2)
    field(4 + 3 * 4 + 4 + 1 + 11 + 92 + 1)
    for _ in range(5):
        field(23, 24)
    scaled(1, 32, 64)
    scaled(32, 300, 291, True)
    field(0, 32)  # further pending relic slots
    field(160 + 2 + 121 * 10 + 8)
    field(0, 28)  # reward display order
    field(3)  # Spoils map marker
    field(12, 0)  # Bones, grid kind and rest options
    field(1)  # grid service
    field(3, 0)
    field(0, 29198 - len(p.indices))  # floor/room history absent in v14
    p.check(26946, 29198)

    field(14 + 275 + 5 + 1 + 2 * 160 + 12 + 11)
    field(631, 632)  # active card
    field(1 + 160 * 2 + 2 + 160 * 4 + 1)
    thief_start = len(p.indices)
    field(160 * 18)
    normalized.append((slice(thief_start + 16, thief_start + 160 * 18, 18), 6, 4, False))
    for _ in range(10):
        field(631, 632)
        field(2)
    field(4 + 6 * 597)  # pile sizes and identity bags
    for _ in range(3 * 160):
        field(23, 24)
    field(1 + 16 * 598 + (160 - 16) * 2)
    for _ in range(160):
        field(23, 24)
    field(1 + 160 * 2)  # bombs
    inventory()
    field(6 * 572, 4 * 572)  # checkpoint has four monster slots
    field(1 + 3 * 597 + 4)
    field(24, 23)  # pending operation
    field(5 + 2 + 597)
    for _ in range(160):
        field(23, 24)
    field(1 + 160 + 3 + 111)
    field(39, 0)  # v14 turn/selection/potion queues
    field(0, 19)  # training-time combat history and bound cards
    p.check(77401, 79280)
    return np.array(p.indices), normalized


PUBLIC_INDEX, SCALED = public_projection()


def project_public(raw):
    if raw.shape != (77401,):
        raise ValueError(f'unexpected public observation shape {raw.shape}')
    # -1 references a padding zero, never a live feature.
    values = np.append(raw, np.float32(0))[PUBLIC_INDEX]
    for region, source, trained, is_id in SCALED:
        part = values[region]
        part *= source / trained
        if is_id:
            part[part >= 1] = 0
    return values


def project_combat_actions(raw, types):
    if raw.shape != (len(types), 732):
        raise ValueError(f'unexpected combat action shape {raw.shape}')
    out = np.zeros((len(types), 729), dtype=np.float32)
    out[np.arange(len(types)), types] = 1
    out[:, 6:603] = raw[:, 5:602]       # card one-hot
    out[:, 603:668] = raw[:, 602:667]   # potion one-hot
    out[:, 668:674] = raw[:, 668:674]   # cost through cost-this-turn
    # 674 is clone provenance
    out[:, 675:699] = raw[:, 674:698]
    out[:, 699:722] = raw[:, 698:721]   # shared choice operations
    out[:, 722:] = raw[:, 722:729]      # pile, stored cost, finished count
    return out

