from typing import Dict
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from .daily_transits import calc_angles_from_longitudes

import swisseph as swe

from .constants import BODIES, AYANAMSA_MAP, SIGNS
from .math_utils import norm360, sign_index, planet_payload, format_lon_ddmmss_sign

# -------------------------------------------------
# Swiss Ephemeris initialization (RUNS ON IMPORT)
# -------------------------------------------------
EPHE_PATH = Path(__file__).resolve().parents[2] / "ephe"
swe.set_ephe_path(str(EPHE_PATH))
# -------------------------------------------------

def sect_from_sun_altitude(jd_ut: float, lat: float, lon: float) -> str:
    """
    True sect:
      - diurnal if Sun altitude > 0°
      - nocturnal if Sun altitude <= 0°
    Uses Swiss Ephemeris equatorial coordinates + azalt.
    """
    # Sun equatorial coordinates (RA/Dec)
    xx, _ = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_EQUATORIAL)
    ra = float(xx[0])
    dec = float(xx[1])
    dist = float(xx[2])

    geopos = [float(lon), float(lat), 0.0]  # lon, lat, altitude(m)
    # returns: azimuth, true altitude, apparent altitude
    az, true_alt, app_alt = swe.azalt(jd_ut, swe.EQU2HOR, geopos, 0.0, 0.0, [ra, dec, dist])

    return "diurnal" if true_alt > 0.0 else "nocturnal"

def compute_chart(
    *,
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: float = 0.0,
    tz_name: str,
    lat: float,
    lon: float,
    zodiac: str = "tropical",
    ayanamsa: str = "fagan_bradley",
    sect: str = "auto",
) -> Dict:
    # 1) Local time -> UTC -> JD(UT)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Invalid tz_name '{tz_name}'. Use IANA like 'America/New_York'.")

    dt_local = datetime(year, month, day, hour, minute, int(second), tzinfo=tz)
    dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

    ut_hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    jd_ut = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, ut_hour)

    # 2) Angles (tropical first)
    _, ascmc = swe.houses_ex(jd_ut, lat, lon, b"W")
    asc_trop = norm360(ascmc[0])
    mc_trop = norm360(ascmc[1])

    zodiac = (zodiac or "tropical").lower().strip()
    ay_deg = None

    if zodiac == "sidereal":
        if ayanamsa not in AYANAMSA_MAP:
            raise ValueError(f"Unknown ayanamsa '{ayanamsa}'. Use one of: {list(AYANAMSA_MAP.keys())}")

        swe.set_sid_mode(AYANAMSA_MAP[ayanamsa], 0, 0)
        ay_deg = float(swe.get_ayanamsa_ut(jd_ut))

        asc = norm360(asc_trop - ay_deg)
        mc = norm360(mc_trop - ay_deg)
        flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    else:
        asc = asc_trop
        mc = mc_trop
        flags = swe.FLG_SWIEPH

    dsc = norm360(asc + 180.0)
    ic = norm360(mc + 180.0)

    asc_sign_idx = sign_index(asc)
    asc_sign_name = SIGNS[asc_sign_idx]
    mc_sign_name = SIGNS[sign_index(mc)]

    # 3) Bodies
    bodies_out: Dict[str, Dict] = {}
    south_nodes_to_add: Dict[str, Dict] = {}

    for name, code in BODIES.items():
        xx, _ = swe.calc_ut(jd_ut, code, flags | swe.FLG_SPEED)
        lon_ecl = norm360(xx[0])
        speed = float(xx[3])  # deg/day

        payload = planet_payload(lon_ecl, asc_sign_idx)
        payload["speed"] = speed
        bodies_out[name] = payload

        if name == "north_node_true":
            south_nodes_to_add["south_node_true"] = planet_payload(norm360(lon_ecl + 180.0), asc_sign_idx)
        if name == "north_node_mean":
            south_nodes_to_add["south_node_mean"] = planet_payload(norm360(lon_ecl + 180.0), asc_sign_idx)

    bodies_out.update(south_nodes_to_add)

    # -------------------------
    # Part of Fortune (PoF)
    # -------------------------
    # Sect (TRUE: Sun altitude)
    sect_norm = (sect or "auto").lower().strip()

    if sect_norm == "auto":
        sect_used = sect_from_sun_altitude(jd_ut, lat, lon)
    else:
        if sect_norm not in {"diurnal", "nocturnal"}:
            raise ValueError("sect must be 'auto', 'diurnal', or 'nocturnal'")
        sect_used = sect_norm

    sun_lon = bodies_out.get("sun", {}).get("longitude")
    moon_lon = bodies_out.get("moon", {}).get("longitude")

    if sun_lon is not None and moon_lon is not None:
        if sect_used == "diurnal":
            pof_lon = norm360(asc + moon_lon - sun_lon)
        else:
            pof_lon = norm360(asc + sun_lon - moon_lon)

        pof_payload = planet_payload(pof_lon, asc_sign_idx)
        pof_payload["speed"] = 0.0  # PoF is a calculated point

        bodies_out["part_of_fortune"] = pof_payload

    angles_out = calc_angles_from_longitudes(asc_deg=asc, mc_deg=mc)

    return {
        "jd_utc": float(jd_ut),
        "timezone": tz_name,
        "dt_local": dt_local.isoformat(),
        "dt_utc": dt_utc.isoformat(),
        "location": {"lat": float(lat), "lon": float(lon)},
        "zodiac": zodiac,
        "sect": sect_used,
        "ayanamsa": {
            "name": ayanamsa if zodiac == "sidereal" else None,
            "degrees": ay_deg,
        },
        "angles": angles_out,
        "bodies": bodies_out,
    }

