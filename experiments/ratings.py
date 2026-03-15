"""Human quality ratings — collect, store, and load post-run quality assessments.

After each experiment run, the human rates the output quality on multiple
dimensions. Ratings are stored as ratings.json alongside metrics.json
in the run's results directory.

Rating dimensions:
  - overall:       1-5 overall quality score
  - correctness:   1-5 functional correctness
  - completeness:  1-5 coverage of requirements
  - code_quality:  1-5 readability, style, organization
  - notes:         free-text observations

The interactive prompt collects ratings via stdin. Programmatic ratings
can be written directly via write_ratings().
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class QualityRating:
    """A single human quality assessment of an experiment run."""
    overall: int = 0           # 1-5 overall quality
    correctness: int = 0       # 1-5 functional correctness
    completeness: int = 0      # 1-5 requirement coverage
    code_quality: int = 0      # 1-5 readability, style, organization
    notes: str = ''            # free-text observations
    rater: str = ''            # who rated (for multi-rater experiments)

    def is_valid(self) -> bool:
        """Check that all numeric ratings are in the 1-5 range."""
        for dim in ('overall', 'correctness', 'completeness', 'code_quality'):
            val = getattr(self, dim)
            if not isinstance(val, int) or val < 1 or val > 5:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return asdict(self)


def write_ratings(results_dir: str, rating: QualityRating) -> str:
    """Write a quality rating to ratings.json in the results directory.

    Args:
        results_dir: path to the run's results directory
        rating: the quality rating to write

    Returns:
        path to the written ratings.json file
    """
    path = os.path.join(results_dir, 'ratings.json')
    with open(path, 'w') as f:
        json.dump(rating.to_dict(), f, indent=2)
    return path


def load_ratings(results_dir: str) -> QualityRating | None:
    """Load a quality rating from ratings.json in the results directory.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(results_dir, 'ratings.json')
    if not os.path.isfile(path):
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        return QualityRating(**{
            k: v for k, v in data.items()
            if k in QualityRating.__dataclass_fields__
        })
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _prompt_int(prompt: str, low: int, high: int, stream=None) -> int:
    """Prompt for an integer in [low, high] range.

    Args:
        prompt: the prompt text
        low: minimum valid value
        high: maximum valid value
        stream: input stream (defaults to sys.stdin)

    Returns:
        the validated integer
    """
    stream = stream or sys.stdin
    while True:
        try:
            print(prompt, end='', flush=True, file=sys.stderr)
            raw = stream.readline().strip()
            val = int(raw)
            if low <= val <= high:
                return val
            print(f'  Please enter a number between {low} and {high}.',
                  file=sys.stderr)
        except (ValueError, EOFError):
            print(f'  Please enter a number between {low} and {high}.',
                  file=sys.stderr)


def collect_rating_interactive(
    *,
    task_description: str = '',
    stream=None,
) -> QualityRating:
    """Interactively collect a quality rating via stdin.

    Displays the rating scale and prompts for each dimension.

    Args:
        task_description: displayed to remind the rater what they're rating
        stream: input stream (defaults to sys.stdin)

    Returns:
        the collected QualityRating
    """
    stream = stream or sys.stdin

    print('\n' + '=' * 60, file=sys.stderr)
    print('  Human Quality Rating', file=sys.stderr)
    print('=' * 60, file=sys.stderr)

    if task_description:
        print(f'\nTask: {task_description}', file=sys.stderr)

    print('\nRate each dimension from 1 (poor) to 5 (excellent):', file=sys.stderr)
    print('  1 = Poor  2 = Below avg  3 = Acceptable  4 = Good  5 = Excellent',
          file=sys.stderr)
    print(file=sys.stderr)

    dimensions = [
        ('overall', 'Overall quality'),
        ('correctness', 'Functional correctness'),
        ('completeness', 'Requirement coverage'),
        ('code_quality', 'Code readability/style'),
    ]

    values = {}
    for key, label in dimensions:
        values[key] = _prompt_int(f'  {label} [1-5]: ', 1, 5, stream=stream)

    print('\nOptional notes (press Enter to skip):', file=sys.stderr)
    print('  Notes: ', end='', flush=True, file=sys.stderr)
    notes = stream.readline().strip()

    rating = QualityRating(
        overall=values['overall'],
        correctness=values['correctness'],
        completeness=values['completeness'],
        code_quality=values['code_quality'],
        notes=notes,
    )

    print(f'\nRating recorded: overall={rating.overall}, '
          f'correctness={rating.correctness}, '
          f'completeness={rating.completeness}, '
          f'code_quality={rating.code_quality}',
          file=sys.stderr)

    return rating
