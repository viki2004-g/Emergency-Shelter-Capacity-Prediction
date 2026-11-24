"""
services/distance.py — Geographic distance calculation using the Haversine formula.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IS THE HAVERSINE FORMULA? (Beginner-friendly explanation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The Earth is a sphere. If you want to measure the shortest distance between
two cities (following the curve of the Earth's surface, not digging through
the ground), you need the "great-circle distance."

The Haversine formula gives you exactly that — the shortest path along the
surface of a sphere between any two points identified by latitude/longitude.

Step-by-step intuition
───────────────────────

  1.  Start with two GPS coordinates:
        Point A — latitude1, longitude1  (e.g., your shelter location)
        Point B — latitude2, longitude2  (e.g., the emergency group's location)

  2.  Convert degrees → radians
      GPS coordinates are given in degrees (0°–360°). Trigonometry functions
      in Python (sin, cos) expect radians. The conversion is simple:
          radians = degrees × (π / 180)

  3.  Calculate the differences
        Δφ (delta phi)        = latitude2  - latitude1   (north–south change)
        Δλ (delta lambda)     = longitude2 - longitude1  (east–west change)

  4.  The core "haversine" calculation
      The word "haversine" comes from "half versine":
          hav(θ) = sin²(θ/2)

      We combine the north–south and east–west haversines:

          a = hav(Δφ) + cos(φ1) × cos(φ2) × hav(Δλ)
            = sin²(Δφ/2) + cos(lat1) × cos(lat2) × sin²(Δλ/2)

      Think of 'a' as a raw "angle squared" proxy: a number between 0 and 1
      where 0 means the two points are at the same spot and 1 means they are
      on exactly opposite sides of the Earth.

  5.  Convert 'a' into an angular distance
          c = 2 × atan2(√a, √(1-a))

      'c' is the central angle between the two points, measured in radians.
      atan2 is used (instead of plain arcsin) because it handles edge cases
      near 0° and 180° more robustly.

  6.  Multiply by Earth's radius to get real-world kilometers
          distance = R × c
      where R = 6371 km (mean radius of the Earth).

Why use Haversine and not simple Pythagoras?
─────────────────────────────────────────────
  A flat-map (Pythagorean) calculation would treat the Earth like a flat
  piece of paper. That works acceptably for very short distances (<1 km)
  but becomes increasingly wrong over larger distances because the Earth
  curves. The Haversine formula accounts for that curvature correctly.

Error margin
─────────────
  The Earth is not a perfect sphere — it is slightly flattened at the poles
  (an oblate spheroid). Haversine ignores this and treats Earth as a perfect
  sphere, introducing an error of up to ±0.3% (~3 km over 1000 km). For
  emergency shelter routing this is acceptable and no external API is needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import math


# Mean radius of the Earth in kilometers (WGS-84 spherical approximation)
EARTH_RADIUS_KM = 6371.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth's surface
    using the Haversine formula.

    The result is the shortest over-the-surface (geodesic) distance between
    the two coordinates — the path a crow would fly, following the Earth's
    curvature.  No external routing API is used.

    Args:
        lat1 (float): Latitude  of point A in decimal degrees  (e.g. 18.5204)
        lon1 (float): Longitude of point A in decimal degrees  (e.g. 73.8567)
        lat2 (float): Latitude  of point B in decimal degrees  (e.g. 19.0760)
        lon2 (float): Longitude of point B in decimal degrees  (e.g. 72.8777)

    Returns:
        float: Great-circle distance in kilometers, rounded to 2 decimal places.
               Returns 9999.0 on invalid / non-numeric input.

    Formula (step by step):
        φ1, φ2  = lat1, lat2 converted to radians
        Δφ      = (lat2 - lat1) in radians          ← north-south difference
        Δλ      = (lon2 - lon1) in radians          ← east-west  difference

        a  = sin²(Δφ/2) + cos(φ1)·cos(φ2)·sin²(Δλ/2)
        c  = 2·atan2(√a, √(1−a))                   ← central angle in radians
        d  = R·c                                    ← arc length on Earth's surface

    Example:
        >>> haversine_distance(18.5204, 73.8567, 19.0760, 72.8777)
        116.28   # approx. distance Pune → Mumbai in km
    """
    try:
        # ── Step 1: Convert all degree inputs to radians ───────────────────
        phi1         = math.radians(float(lat1))
        phi2         = math.radians(float(lat2))
        delta_phi    = math.radians(float(lat2) - float(lat1))   # Δφ
        delta_lambda = math.radians(float(lon2) - float(lon1))   # Δλ

        # ── Step 2: Haversine intermediate value 'a' ──────────────────────
        # a = sin²(Δφ/2) + cos(φ1)·cos(φ2)·sin²(Δλ/2)
        a = (
            math.sin(delta_phi    / 2.0) ** 2 +
            math.cos(phi1) * math.cos(phi2) *
            math.sin(delta_lambda / 2.0) ** 2
        )

        # ── Step 3: Central angle 'c' ──────────────────────────────────────
        # Clamp 'a' to [0, 1] to guard against floating-point rounding beyond
        # the valid range (e.g. a = 1.0000000002 for identical coordinates).
        a = max(0.0, min(1.0, a))
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

        # ── Step 4: Arc length on Earth's surface ─────────────────────────
        distance = EARTH_RADIUS_KM * c

        return round(distance, 2)

    except (TypeError, ValueError):
        # Non-numeric input — return a sentinel "unreachably far" value so
        # the recommendation engine safely scores such a shelter at 0 for distance.
        return 9999.0


def distance_band(distance_km: float) -> str:
    """
    Classify a distance into a human-readable proximity band.

    Used by the recommendation engine reason generator to pick the right
    narrative label without hard-coding thresholds in the template.

    Bands:
        'immediate'  —  0 – 2 km
        'close'      —  2 – 10 km
        'moderate'   — 10 – 25 km
        'far'        — 25 – 50 km
        'very_far'   — > 50 km

    Returns:
        str: One of 'immediate', 'close', 'moderate', 'far', 'very_far'.
    """
    d = float(distance_km)
    if d < 2.0:
        return 'immediate'
    if d < 10.0:
        return 'close'
    if d < 25.0:
        return 'moderate'
    if d < 50.0:
        return 'far'
    return 'very_far'


BAND_LABELS = {
    'immediate': 'Extremely close proximity',
    'close':     'Close proximity',
    'moderate':  'Relatively close',
    'far':       'Accessible distance',
    'very_far':  'Remote — outside typical operational perimeter',
}
