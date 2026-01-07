"""
Daily Transit Rules — Rule-first implementation (hybrid)

- Personal/Jupiter group (Sun, Mercury, Venus, Mars, Jupiter):
  - applying vs separating is computed (if speed is provided)
  - orb depends on applying vs separating (per RULES.ORB_RULES)

- Minute-exact group (Saturn, Uranus, Neptune, Pluto, Chiron, North Node):
  - must be "exact to degree+minute" (within RULES.MINUTE_TOL_ARCMIN)
  - applying/separating is not required and is not used to gate inclusion
  - orbs are optional here; this implementation gates only by minute-exactness

Other:
- Moon excluded as transiting body; South Node excluded
- Natal points include angles + Part of Fortune
- Aspects: major + quincunx only
- Degree-accurate geometry
- Mars dominance (diurnal): if Mars hits a natal point, suppress other hits to that natal point
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
import math


# =============================================================================
# RULES (single source of truth)
# =============================================================================

class RULES:
    HOUSE_SYSTEM = "Whole Sign"

    # Transiting bodies considered
    TRANSIT_INCLUDED = {
        "Sun", "Mercury", "Venus", "Mars", "Jupiter",
        "Saturn", "Uranus", "Neptune", "Pluto",
        "Chiron", "North Node"   # Mean Node expected
    }
    TRANSIT_EXCLUDED = {"Moon", "South Node"}

    # Natal points eligible to receive aspects
    NATAL_ELIGIBLE = {
        "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
        "Saturn", "Uranus", "Neptune", "Pluto",
        "Chiron", "North Node",
        "Ascendant", "Midheaven", "Part of Fortune"
    }

    # Aspect types used (major + quincunx)
    ASPECTS_DEG = {
        "conjunction": 0.0,
        "sextile": 60.0,
        "square": 90.0,
        "trine": 120.0,
        "opposition": 180.0,
        "quincunx": 150.0,
    }

    # Applying vs separating orb rules (only used for non-minute-exact bodies)
    # (applying_orb_deg, separating_orb_deg)
    ORB_RULES = {
        "Sun": (2.0, 1.0),
        "Venus": (2.0, 1.0),
        "Mars": (2.0, 1.0),
        "Jupiter": (2.0, 1.0),
        "Mercury": (2.5, 1.0),
    }

    # Minute-exact-only transiting bodies
    MINUTE_EXACT_TRANSITS = {"Saturn", "Uranus", "Neptune", "Pluto", "Chiron", "North Node"}

    # "Exact to degree AND minute" tolerance, arcminutes
    MINUTE_TOL_ARCMIN = 1.59

    # Natal outer planets receiving rule (optional constraint you previously had)
    OUTER_NATAL = {"Saturn", "Uranus", "Neptune", "Pluto"}
    OUTER_NATAL_ALLOWED_TRANSITS = {"Sun", "Mercury", "Venus", "Mars", "Jupiter"}

    # Mars dominance rule (diurnal only)
    MARS_DOMINANCE_DIURNAL_ONLY = True


# =============================================================================
# Formatting + angles + Part of Fortune (utilities)
# =============================================================================

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

def norm360(x: float) -> float:
    x = x % 360.0
    return x + 360.0 if x < 0 else x

def angular_distance(a: float, b: float) -> float:
    d = abs(norm360(a) - norm360(b)) % 360.0
    return d if d <= 180.0 else 360.0 - d

def aspect_error(transit_lon: float, natal_lon: float, aspect_deg: float) -> float:
    sep = angular_distance(transit_lon, natal_lon)
    return sep - aspect_deg

def is_minute_exact(error_deg: float, minute_tolerance_arcmin: float) -> bool:
    return abs(error_deg) <= (minute_tolerance_arcmin / 60.0)

def format_sign_degree(deg: float) -> str:
    deg = norm360(deg)
    sign_index = int(deg // 30)
    deg_in_sign = deg - sign_index * 30

    whole_deg = int(math.floor(deg_in_sign))
    minutes = int((deg_in_sign - whole_deg) * 60.0)  # truncate, don't round

    return f"{SIGNS[sign_index]} {whole_deg}°{minutes:02d}′"


def calc_angles_from_longitudes(asc_deg: float, mc_deg: float) -> Dict[str, Any]:
    asc = norm360(asc_deg)
    mc = norm360(mc_deg)
    dsc = norm360(asc + 180.0)
    ic = norm360(mc + 180.0)
    return {
        "asc": asc, "mc": mc, "dsc": dsc, "ic": ic,
        "asc_fmt": format_sign_degree(asc),
        "mc_fmt": format_sign_degree(mc),
        "dsc_fmt": format_sign_degree(dsc),
        "ic_fmt": format_sign_degree(ic),
    }

def calc_part_of_fortune(asc_lon: float, sun_lon: float, moon_lon: float, sect: str) -> float:
    sect = sect.lower().strip()
    if sect not in {"diurnal", "nocturnal"}:
        raise ValueError("sect must be 'diurnal' or 'nocturnal'")
    asc = norm360(asc_lon)
    sun = norm360(sun_lon)
    moon = norm360(moon_lon)
    pof = asc + (moon - sun) if sect == "diurnal" else asc + (sun - moon)
    return norm360(pof)

def calc_part_of_fortune_formatted(asc_lon: float, sun_lon: float, moon_lon: float, sect: str) -> str:
    return format_sign_degree(calc_part_of_fortune(asc_lon, sun_lon, moon_lon, sect))

def whole_sign_house(asc_lon: float, point_lon: float) -> int:
    asc_sign_idx = int(norm360(asc_lon) // 30)
    pt_sign_idx = int(norm360(point_lon) // 30)
    return ((pt_sign_idx - asc_sign_idx) % 12) + 1


# =============================================================================
# Data models
# =============================================================================

@dataclass(frozen=True)
class BodyPosition:
    longitude: float
    speed: Optional[float] = None  # deg/day (recommended for applying/separating)

@dataclass(frozen=True)
class TransitAspectHit:
    transit_body: str
    natal_point: str
    aspect_name: str
    aspect_angle: float
    error_deg: float

    # applying/separating is only relevant for non-minute-exact bodies
    applying: Optional[bool] = None

    # For non-minute-exact bodies, orb_used is the allowed orb (applying or separating)
    orb_used: Optional[float] = None

    minute_exact_required: bool = False
    minute_exact_passed: bool = True
    notes: str = ""
    
    qualifies: bool = True
    within_orb: Optional[bool] = None

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        d["error_abs_deg"] = abs(self.error_deg)
        d["error_fmt"] = _format_error_minutes(self.error_deg)
        d["applying_label"] = (
            "applying" if self.applying is True else
            "separating" if self.applying is False else
            "n/a"
        )
        return d

def _format_error_minutes(error_deg: float) -> str:
    sign = "+" if error_deg >= 0 else "-"
    d_abs = abs(error_deg)
    whole = int(math.floor(d_abs))
    minutes = int((d_abs - whole) * 60.0)  # truncate, don't round
    return f"{sign}{whole}°{minutes:02d}′"

# =============================================================================
# Rule engine
# =============================================================================

class DailyTransitRuleEngine:
    def __init__(self, sect: str, minute_tolerance_arcmin: float = RULES.MINUTE_TOL_ARCMIN):
        sect = sect.lower().strip()
        if sect not in {"diurnal", "nocturnal"}:
            raise ValueError("sect must be 'diurnal' or 'nocturnal'")
        self.sect = sect
        self.minute_tol = float(minute_tolerance_arcmin)

    def run_qualifying(self, transits: Dict[str, BodyPosition], natal: Dict[str, BodyPosition]) -> List[TransitAspectHit]:
        hits = self.find_aspects(transits=transits, natal=natal, qualify=True)
        hits = self.apply_mars_dominance(hits)
        return self.rank_hits(hits)

    def run_all(self, transits: Dict[str, BodyPosition], natal: Dict[str, BodyPosition]) -> List[TransitAspectHit]:
        # do NOT apply Mars dominance here (you want "all aspects" unaltered)
        hits = self.find_aspects(transits=transits, natal=natal, qualify=False)
        return self.rank_hits(hits)

    # -------------------------
    # eligibility / constraints
    # -------------------------

    def _eligible_transit_body(self, body: str) -> bool:
        if body in RULES.TRANSIT_EXCLUDED:
            return False
        return body in RULES.TRANSIT_INCLUDED

    def _eligible_natal_point(self, point: str) -> bool:
        return point in RULES.NATAL_ELIGIBLE

    def _outer_natal_receiving_allowed(self, transit_body: str, natal_point: str) -> bool:
        if natal_point in RULES.OUTER_NATAL:
            return transit_body in RULES.OUTER_NATAL_ALLOWED_TRANSITS
        return True

    def _minute_exact_required(self, transit_body: str) -> bool:
        return transit_body in RULES.MINUTE_EXACT_TRANSITS

    # -------------------------
    # applying/separating logic
    # -------------------------

    def _applying_or_separating(
        self,
        transit_lon: float,
        transit_speed: Optional[float],
        natal_lon: float,
        aspect_angle: float
    ) -> Optional[bool]:
        """
        Determine applying vs separating using speed, if available.
        If no speed is provided, returns None.
        """
        if transit_speed is None:
            return None

        err_now = abs(aspect_error(transit_lon, natal_lon, aspect_angle))

        # small forward projection
        step = 0.1  # day
        future_lon = norm360(transit_lon + transit_speed * step)
        err_future = abs(aspect_error(future_lon, natal_lon, aspect_angle))

        if err_future < err_now:
            return True
        if err_future > err_now:
            return False
        return True

    def _orb_for_non_exact(self, transit_body: str, applying: Optional[bool]) -> Optional[float]:
        """
        For non-minute-exact bodies only.
        Uses applying/separating orb rules. If applying is unknown, uses the tighter orb.
        """
        if transit_body not in RULES.ORB_RULES:
            return None
        app_orb, sep_orb = RULES.ORB_RULES[transit_body]
        if applying is None:
            return min(app_orb, sep_orb)
        return app_orb if applying else sep_orb

    # -------------------------
    # core aspect finding
    # -------------------------

    def find_aspects(
        self,
        transits: Dict[str, BodyPosition],
        natal: Dict[str, BodyPosition],
        *,
        qualify: bool = True
    ) -> List[TransitAspectHit]:
        hits: List[TransitAspectHit] = []

        transit_items = [(b, p) for b, p in transits.items() if self._eligible_transit_body(b)]
        natal_items = [(n, p) for n, p in natal.items() if self._eligible_natal_point(n)]

        for t_body, t_pos in transit_items:
            minute_required = self._minute_exact_required(t_body)

            for n_point, n_pos in natal_items:
                if not self._outer_natal_receiving_allowed(t_body, n_point):
                    continue

                for aspect_name, aspect_angle in RULES.ASPECTS_DEG.items():
                    err = aspect_error(t_pos.longitude, n_pos.longitude, aspect_angle)
                    abs_err = abs(err)

                    # A) Minute-exact group
                    if minute_required:
                        passed = is_minute_exact(abs_err, minute_tolerance_arcmin=self.minute_tol)

                        if qualify and not passed:
                            continue

                        hits.append(
                            TransitAspectHit(
                                transit_body=t_body,
                                natal_point=n_point,
                                aspect_name=aspect_name,
                                aspect_angle=aspect_angle,
                                error_deg=err,
                                applying=None,
                                orb_used=None,
                                minute_exact_required=True,
                                minute_exact_passed=passed,
                                qualifies=passed,
                                within_orb=None,
                                notes="minute-exact transit" if passed else "minute-exact required (did not pass)",
                            )
                        )
                        continue

                    # B) Non-minute-exact group
                    applying = self._applying_or_separating(
                        transit_lon=t_pos.longitude,
                        transit_speed=t_pos.speed,
                        natal_lon=n_pos.longitude,
                        aspect_angle=aspect_angle,
                    )

                    orb = self._orb_for_non_exact(t_body, applying)
                    if orb is None:
                        continue

                    within_orb = abs_err <= orb
                    qualifies_hit = within_orb

                    if qualify and not qualifies_hit:
                        continue

                    hits.append(
                        TransitAspectHit(
                            transit_body=t_body,
                            natal_point=n_point,
                            aspect_name=aspect_name,
                            aspect_angle=aspect_angle,
                            error_deg=err,
                            applying=applying,
                            orb_used=orb,
                            minute_exact_required=False,
                            minute_exact_passed=True,
                            qualifies=qualifies_hit,
                            within_orb=within_orb,
                            notes="within orb" if within_orb else "outside orb",
                        )
                    )

        return hits

        
    # -------------------------
    # Mars dominance (diurnal)
    # -------------------------

    def apply_mars_dominance(self, hits: List[TransitAspectHit]) -> List[TransitAspectHit]:
        """
        In diurnal charts:
        - if Mars has any qualifying hit to a natal point,
          suppress other planets' hits to that same natal point.
        """
        if not RULES.MARS_DOMINANCE_DIURNAL_ONLY or self.sect != "diurnal":
            return hits

        dominated_points = {h.natal_point for h in hits if h.transit_body == "Mars"}
        if not dominated_points:
            return hits

        return [
            h for h in hits
            if (h.transit_body == "Mars") or (h.natal_point not in dominated_points)
        ]

    # -------------------------
    # ranking
    # -------------------------

    def rank_hits(self, hits: List[TransitAspectHit]) -> List[TransitAspectHit]:
        """
        Prioritize:
        1) non-minute-exact applying (True)
        2) non-minute-exact unknown applying (None)
        3) non-minute-exact separating (False)
        4) minute-exact (treated as its own stable category)
        Then by tightness (abs error).
        """
        def key(h: TransitAspectHit):
            if h.minute_exact_required:
                bucket = 3
                app_rank = 0
            else:
                bucket = 0
                app_rank = 0 if h.applying is True else (1 if h.applying is None else 2)
            return (bucket, app_rank, abs(h.error_deg), h.transit_body, h.natal_point, h.aspect_angle)

        return sorted(hits, key=key)
        
def build_positions_from_chart_response(chart: dict, *, sect: str, include_pof: bool = True) -> Dict[str, BodyPosition]:

    """
    Convert your /chart JSON into the {Name: BodyPosition} dict
    expected by DailyTransitRuleEngine.

    Assumptions:
      - chart["bodies"][key]["longitude"] exists
      - angles live in chart["angles"]
      - Part of Fortune is NOT in /chart today; you will add it OR omit it.
    """
    bodies = chart.get("bodies", {})
    angles = chart.get("angles", {})

    out: Dict[str, BodyPosition] = {}

    # Map swiss_api keys -> rule engine names
    key_map = {
        "sun": "Sun",
        "moon": "Moon",
        "mercury": "Mercury",
        "venus": "Venus",
        "mars": "Mars",
        "jupiter": "Jupiter",
        "saturn": "Saturn",
        "uranus": "Uranus",
        "neptune": "Neptune",
        "pluto": "Pluto",
        "chiron": "Chiron",

        # choose ONE node convention; your RULES expects Mean Node:
        "north_node_mean": "North Node",

        # If you prefer true node instead, swap the line above for:
        # "north_node_true": "North Node",
    }

    for k, name in key_map.items():
        if k in bodies:
            lon = float(bodies[k]["longitude"])
            # speed is optional; include it later if you add speed to /chart output
            out[name] = BodyPosition(longitude=lon, speed=bodies[k].get("speed"))

    # Angles
    if "asc" in angles:
        out["Ascendant"] = BodyPosition(longitude=float(angles["asc"]))
    if "mc" in angles:
        out["Midheaven"] = BodyPosition(longitude=float(angles["mc"]))

    # Part of Fortune (natal point) — include by default
    if include_pof:
        if sect is None:
            raise ValueError("sect is required to compute Part of Fortune ('diurnal' or 'nocturnal')")

        sect_norm = sect.lower().strip()
        if sect_norm not in {"diurnal", "nocturnal"}:
            raise ValueError("sect must be 'diurnal' or 'nocturnal'")

        asc_lon = out.get("Ascendant").longitude if "Ascendant" in out else None
        sun_lon = out.get("Sun").longitude if "Sun" in out else None
        moon_lon = out.get("Moon").longitude if "Moon" in out else None

        if asc_lon is None or sun_lon is None or moon_lon is None:
            raise ValueError("Cannot compute Part of Fortune: need Ascendant, Sun, and Moon longitudes")

        pof_lon = calc_part_of_fortune(
            asc_lon=asc_lon,
            sun_lon=sun_lon,
            moon_lon=moon_lon,
            sect=sect_norm,
        )
        out["Part of Fortune"] = BodyPosition(longitude=float(pof_lon))

    return out
