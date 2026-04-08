#!/usr/bin/env python3
"""Tests for issue #218: Temporal decay for learning prominence scoring.

Covers:
 - HALF_LIFE_DAYS is 90 (generous half-life per issue spec)
 - Decay floor: recency_decay never falls below DECAY_FLOOR
 - Retired entries are exempt from floor (still return 0.0)
 - Very old entries still have nonzero prominence (floor effect)
 - Reinforcement resets the decay clock (already works, verified here)
"""
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.learning.episodic.indexer import (
    compute_prominence,
    HALF_LIFE_DAYS,
)
# DECAY_FLOOR may not exist yet — that's one of the things we're testing
try:
    from teaparty.learning.episodic.indexer import DECAY_FLOOR
except ImportError:
    DECAY_FLOOR = None


class TestHalfLifeConstant(unittest.TestCase):
    """Issue #218 specifies a generous half-life of 90 days."""

    def test_half_life_is_90_days(self):
        """HALF_LIFE_DAYS must be 90, not the original 30."""
        self.assertEqual(HALF_LIFE_DAYS, 90,
                         f"HALF_LIFE_DAYS should be 90 per issue #218, got {HALF_LIFE_DAYS}")


class TestDecayFloor(unittest.TestCase):
    """Entries must not decay below DECAY_FLOOR (0.1)."""

    def test_decay_floor_constant_exists_and_is_point_one(self):
        """DECAY_FLOOR must be defined and equal to 0.1."""
        self.assertIsNotNone(DECAY_FLOOR, "DECAY_FLOOR must be exported from memory_indexer")
        self.assertAlmostEqual(DECAY_FLOOR, 0.1, places=5,
                               msg=f"DECAY_FLOOR should be 0.1, got {DECAY_FLOOR}")

    def test_very_old_entry_does_not_decay_below_floor(self):
        """An entry 365 days old must have recency_decay >= DECAY_FLOOR.

        With HALF_LIFE=90 and no floor: decay = exp(-ln(2)/90 * 365) ≈ 0.057
        With floor=0.1: decay is clamped to 0.1
        So prominence = importance × max(floor, decay) × (1 + rc)
                      = 0.5 × 0.1 × 1 = 0.05
        """
        today = date.today()
        old_date = (today - timedelta(days=365)).isoformat()
        metadata = {
            'importance': '0.5',
            'last_reinforced': old_date,
            'reinforcement_count': '0',
            'status': 'active',
        }
        p = compute_prominence(metadata, today=today)
        # Without floor, this would be 0.5 × exp(-ln2/90 × 365) ≈ 0.029
        # With floor on recency_decay: 0.5 × 0.1 × 1 = 0.05
        self.assertIsNotNone(DECAY_FLOOR, "DECAY_FLOOR must exist for this test")
        expected_floor_prominence = 0.5 * DECAY_FLOOR * 1
        self.assertAlmostEqual(p, expected_floor_prominence, places=4,
                               msg=f"Very old entry should hit decay floor, got {p}")

    def test_ancient_entry_has_same_prominence_as_365_day_entry(self):
        """Entries at 365 days and 1000 days should have the same prominence
        because both hit the decay floor."""
        today = date.today()
        meta_365 = {
            'importance': '0.7',
            'last_reinforced': (today - timedelta(days=365)).isoformat(),
            'reinforcement_count': '0',
            'status': 'active',
        }
        meta_1000 = {
            'importance': '0.7',
            'last_reinforced': (today - timedelta(days=1000)).isoformat(),
            'reinforcement_count': '0',
            'status': 'active',
        }
        p_365 = compute_prominence(meta_365, today=today)
        p_1000 = compute_prominence(meta_1000, today=today)
        self.assertAlmostEqual(p_365, p_1000, places=4,
                               msg="Both should be at the decay floor")

    def test_retired_entries_exempt_from_floor(self):
        """Retired entries must still return 0.0 — the floor does not save them."""
        metadata = {
            'importance': '0.9',
            'status': 'retired',
            'reinforcement_count': '5',
            'last_reinforced': date.today().isoformat(),
        }
        p = compute_prominence(metadata)
        self.assertEqual(p, 0.0,
                         "Retired entries must have prominence 0.0 regardless of floor")

    def test_recent_entry_unaffected_by_floor(self):
        """An entry reinforced today should have natural decay (1.0), not be clipped."""
        today = date.today()
        metadata = {
            'importance': '0.8',
            'last_reinforced': today.isoformat(),
            'reinforcement_count': '0',
            'status': 'active',
        }
        p = compute_prominence(metadata, today=today)
        # decay should be 1.0 (age=0), prominence = 0.8 × 1.0 × 1 = 0.8
        self.assertAlmostEqual(p, 0.8, places=4,
                               msg="Recent entry should not be affected by the floor")

    def test_entry_at_half_life_decays_to_half(self):
        """At exactly HALF_LIFE_DAYS (90), decay should be 0.5."""
        today = date.today()
        hl_date = (today - timedelta(days=90)).isoformat()
        metadata = {
            'importance': '1.0',
            'last_reinforced': hl_date,
            'reinforcement_count': '0',
            'status': 'active',
        }
        p = compute_prominence(metadata, today=today)
        # decay = exp(-ln2/90 × 90) = 0.5, prominence = 1.0 × 0.5 × 1 = 0.5
        self.assertAlmostEqual(p, 0.5, places=4,
                               msg="At half-life, prominence should be half of importance")


class TestReinforcementResetsDecayClock(unittest.TestCase):
    """Reinforcement updates last_reinforced, which resets the decay clock."""

    def test_reinforced_entry_is_fresher_than_unreinforced(self):
        """An entry created 180 days ago but reinforced today should score
        much higher than one created 180 days ago and never reinforced."""
        today = date.today()
        old_date = (today - timedelta(days=180)).isoformat()

        meta_reinforced = {
            'importance': '0.5',
            'last_reinforced': today.isoformat(),  # reinforced today
            'reinforcement_count': '1',
            'status': 'active',
        }
        meta_stale = {
            'importance': '0.5',
            'last_reinforced': old_date,  # never reinforced since creation
            'reinforcement_count': '0',
            'status': 'active',
        }
        p_reinforced = compute_prominence(meta_reinforced, today=today)
        p_stale = compute_prominence(meta_stale, today=today)

        self.assertGreater(p_reinforced, p_stale,
                           "Reinforced entry should have higher prominence than stale entry")
        # reinforced: 0.5 × 1.0 × 2 = 1.0
        # stale: 0.5 × max(0.1, exp(-ln2/90 × 180)) × 1 = 0.5 × 0.25 = 0.125
        self.assertGreater(p_reinforced / p_stale, 4,
                           "Reinforced entry should be significantly higher")


if __name__ == '__main__':
    unittest.main()
