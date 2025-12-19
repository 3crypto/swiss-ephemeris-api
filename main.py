from typing import Optional, Tuple
from fastapi import FastAPI, HTTPException, Query
from functools import lru_cache
import time
import requests
import os
import swisseph as swe


app = FastAPI()

from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title="Swiss Ephemeris Chart API",
        version="1.0.0",
        description="Swiss Ephemeris (pyswisseph) Whole Sign chart API for GPT Actions.",
        routes=app.routes,
    )

    # Required for GPT Actions: tell it the base URL
    schema["servers"] = [
        {"url": "https://swiss-ephemeris-api-gpnc.onrender.com"}
    ]

    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi


# Swiss Ephemeris setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(BASE_DIR, "ephe")

# Make it extra explicit for Swiss Ephemeris
os.environ["SE_EPHE_PATH"] = EPHE_PATH
swe.set_ephe_path(EPHE_PATH + os.sep)  # trailing slash helps sometimes


# -----------------------------
# Constants
# -----------------------------
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

BODIES = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,

    # Extras
    "chiron": swe.CHIRON,

    # Nodes
    "north_node_true": swe.TRUE_NODE,
    "north_node_mean": swe.MEAN_NODE,
}

AYANAMSA_MAP = {
    "fagan_bradley": swe.SIDM_FAGAN_BRADLEY,
    "lahiri": swe.SIDM_LAHIRI,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
}

# -----------------------------
# Helpers
# -----------------------------
def norm360(x):
    return x % 360.0

def sign_index(lon):
    return int(norm360(lon) // 30)

def deg_in_sign(lon):
    return norm360(lon) % 30.0

def format_deg_sign(lon):
    sidx = sign_index(lon)
    deg = deg_in_sign(lon)
    deg_i = int(deg)
    minutes = int((deg - deg_i) * 60)
    return f"{deg_i}°{minutes:02d}' {SIGNS[sidx]}"

def whole_sign_house_for_lon(lon, asc_sign_idx):
    p_sign = sign_index(lon)
    return ((p_sign - asc_sign_idx) % 12) + 1

def planet_payload(lon, asc_sign_idx):
    lon = norm360(lon)
    sidx = sign_index(lon)
    house = whole_sign_house_for_lon(lon, asc_sign_idx)
    return {
        "longitude": float(lon),
        "sign": SIGNS[sidx],
        "deg_in_sign": float(deg_in_sign(lon)),
        "house_whole_sign": int(house),
        "display": f"{format_deg_sign(lon)} (House {house})",
    }

# -----------------------------
# Geocoding (Nominatim) helpers
# -----------------------------
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "swiss-ephemeris-api/1.0 (contact: admin@erosgpt.ai)"  # CHANGE THIS

_last_geocode_ts = 0.0

def _throttle_nominatim(min_interval_sec: float = 1.0) -> None:
    """Basic global throttle to reduce risk of violating Nominatim rate expectations."""
    global _last_geocode_ts
    now = time.time()
    wait = (_last_geocode_ts + min_interval_sec) - now
    if wait > 0:
        time.sleep(wait)
    _last_geocode_ts = time.time()

@lru_cache(maxsize=1024)
def geocode_place(place: str) -> Tuple[float, float]:
    """
    Geocode a place string -> (lat, lon) using Nominatim.
    Cached to reduce repeat lookups.
    """
    place = (place or "").strip()
    if not place:
        raise ValueError("Empty place string")

    _throttle_nominatim(1.0)

    params = {
        "q": place,
        "format": "json",
        "limit": 1,
    }
    headers = {
        "User-Agent": NOMINATIM_USER_AGENT,
    }

    r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    if not data:
        raise ValueError(f"Could not geocode place: '{place}'")

    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])
    return lat, lon


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def home():
    return {"status": "Swiss API is running", "version": "tzfix-2025-12-18-01"}

@app.get("/chart")
def chart(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: float = 0.0,
    tz_name: str = Query(..., description="IANA timezone, e.g. America/New_York"),
    place: Optional[str] = Query(None)
    lat: Optional[float] = Query(None)
    lon: Optional[float] = Query(None)
    zodiac: str = "tropical",          # "tropical" or "sidereal"
    ayanamsa: str = "fagan_bradley",   # used if zodiac="sidereal"
):
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        # -----------------------------
        # 1) Time: local -> UTC -> JD(UT)
        # -----------------------------
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise ValueError(
                f"Invalid tz_name '{tz_name}'. Use an IANA timezone like 'America/New_York'."
            )

        dt_local = datetime(year, month, day, hour, minute, int(second), tzinfo=tz)
        dt_utc = dt_local.astimezone(ZoneInfo("UTC"))

        ut_hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
        jd_ut = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, ut_hour)

        # -----------------------------
        # Location: lat/lon from inputs OR geocode place
        # -----------------------------
        if (lat is None or lon is None) and place:
            try:
                lat, lon = geocode_place(place)
            except Exception as ge:
                raise ValueError(str(ge))

        if lat is None or lon is None:
            raise ValueError("Location required: provide lat & lon, or provide place (e.g. 'New Haven, CT').")

        # -----------------------------
        # 2) Angles (tropical first)
        # -----------------------------
        _, ascmc = swe.houses_ex(jd_ut, lat, lon, b"P")
        asc_trop = norm360(ascmc[0])
        mc_trop = norm360(ascmc[1])

        zodiac = (zodiac or "tropical").lower().strip()
        ay_deg = None

        if zodiac == "sidereal":
            if ayanamsa not in AYANAMSA_MAP:
                raise ValueError(
                    f"Unknown ayanamsa '{ayanamsa}'. Use one of: {list(AYANAMSA_MAP.keys())}"
                )

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

        # -----------------------------
        # 3) Whole Sign houses
        # -----------------------------
        houses = []
        for h in range(1, 13):
            sidx = (asc_sign_idx + h - 1) % 12
            houses.append({
                "house": h,
                "sign": SIGNS[sidx],
                "cusp_longitude": float(sidx * 30.0),
            })

        # -----------------------------
        # 4) Bodies
        # -----------------------------
        bodies_out = {}
        south_nodes_to_add = {}

        for name, code in BODIES.items():
            lon_ecl = norm360(swe.calc_ut(jd_ut, code, flags)[0][0])
            bodies_out[name] = planet_payload(lon_ecl, asc_sign_idx)

            # Auto-create South Nodes
            if name == "north_node_true":
                south_lon = norm360(lon_ecl + 180.0)
                south_nodes_to_add["south_node_true"] = planet_payload(south_lon, asc_sign_idx)
            if name == "north_node_mean":
                south_lon = norm360(lon_ecl + 180.0)
                south_nodes_to_add["south_node_mean"] = planet_payload(south_lon, asc_sign_idx)

        bodies_out.update(south_nodes_to_add)

        # -----------------------------
        # 5) Response
        # -----------------------------
        return {
            "jd_utc": float(jd_ut),
            "timezone": tz_name,
            "dt_local": dt_local.isoformat(),
            "dt_utc": dt_utc.isoformat(),
            "location": {"lat": float(lat), "lon": float(lon)},
            "zodiac": zodiac,
            "ayanamsa": {
                "name": ayanamsa if zodiac == "sidereal" else None,
                "degrees": ay_deg,
            },
            "angles": {
                "asc": float(asc),
                "asc_sign": asc_sign_name,
                "dsc": float(dsc),
                "mc": float(mc),
                "mc_sign": mc_sign_name,
                "ic": float(ic),
            },
            "houses_whole_sign": houses,
            "bodies": bodies_out,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
