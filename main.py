from typing import Dict, Optional
import os
import time

import swisseph as swe
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel


# -----------------------------
# Response Models (for GPT Actions stability)
# -----------------------------
class LocationModel(BaseModel):
    lat: float
    lon: float


class AyanamsaModel(BaseModel):
    name: Optional[str] = None
    degrees: Optional[float] = None


class AnglesModel(BaseModel):
    asc: float
    asc_sign: str
    dsc: float
    mc: float
    mc_sign: str
    ic: float


class BodyModel(BaseModel):
    longitude: float
    sign: str
    deg_in_sign: float
    house_whole_sign: int
    display: str


class ChartResponse(BaseModel):
    jd_utc: float
    timezone: str
    dt_local: str
    dt_utc: str
    location: LocationModel
    zodiac: str
    ayanamsa: AyanamsaModel
    angles: AnglesModel
    bodies: Dict[str, BodyModel]


# -----------------------------
# App
# -----------------------------
app = FastAPI()


# -----------------------------
# Logging middleware
# -----------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    ua = request.headers.get("user-agent", "")
    accept = request.headers.get("accept", "")
    print(f"UA: {ua}")
    print(f"ACCEPT: {accept}")
    print(f"INCOMING {request.method} {request.url}")

    response = await call_next(request)

    ct = response.headers.get("content-type", "")
    cl = response.headers.get("content-length", "")
    ms = int((time.time() - start) * 1000)
    print(f"STATUS {response.status_code} ct={ct} len={cl} ms={ms} path={request.url.path}")
    return response


# -----------------------------
# OpenAPI servers (for GPT Actions)
# -----------------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title="Swiss Ephemeris Chart API",
        version="1.0.0",
        description="Swiss Ephemeris (pyswisseph) Whole Sign chart API for GPT Actions.",
        routes=app.routes,
    )

    schema["servers"] = [{"url": "https://swiss-ephemeris-api-gpnc.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


# -----------------------------
# Swiss Ephemeris setup
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(BASE_DIR, "ephe")
os.environ["SE_EPHE_PATH"] = EPHE_PATH
swe.set_ephe_path(EPHE_PATH + os.sep)


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
    "chiron": swe.CHIRON,
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
def norm360(x: float) -> float:
    return x % 360.0


def sign_index(lon: float) -> int:
    return int(norm360(lon) // 30)


def deg_in_sign(lon: float) -> float:
    return norm360(lon) % 30.0


def format_deg_sign(lon: float) -> str:
    sidx = sign_index(lon)
    deg = deg_in_sign(lon)
    deg_i = int(deg)
    minutes = int((deg - deg_i) * 60)
    return f"{deg_i}°{minutes:02d}' {SIGNS[sidx]}"


def whole_sign_house_for_lon(lon: float, asc_sign_idx: int) -> int:
    p_sign = sign_index(lon)
    return ((p_sign - asc_sign_idx) % 12) + 1


def planet_payload(lon: float, asc_sign_idx: int) -> Dict:
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
# Routes
# -----------------------------
@app.get("/")
def home():
    return {"status": "Swiss API is running", "version": "latlon-2025-12-20-01"}


@app.api_route("/", methods=["HEAD"], include_in_schema=False)
def home_head():
    return Response(status_code=200)


@app.get("/openai", include_in_schema=False)
def openai_probe():
    return {"status": "ok"}


@app.get("/chart", response_model=ChartResponse)
def chart(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: float = 0.0,
    tz_name: str = Query(...),
    lat: float = Query(..., description="Latitude, e.g. 41.3083"),
    lon: float = Query(..., description="Longitude, e.g. -72.9279"),
    zodiac: str = "tropical",
    ayanamsa: str = "fagan_bradley",
):
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
        _, ascmc = swe.houses_ex(jd_ut, lat, lon, b"P")
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

        # 3) Bodies (whole sign)
        bodies_out: Dict[str, Dict] = {}
        south_nodes_to_add: Dict[str, Dict] = {}

        for name, code in BODIES.items():
            lon_ecl = norm360(swe.calc_ut(jd_ut, code, flags)[0][0])
            bodies_out[name] = planet_payload(lon_ecl, asc_sign_idx)

            if name == "north_node_true":
                south_nodes_to_add["south_node_true"] = planet_payload(norm360(lon_ecl + 180.0), asc_sign_idx)
            if name == "north_node_mean":
                south_nodes_to_add["south_node_mean"] = planet_payload(norm360(lon_ecl + 180.0), asc_sign_idx)

        bodies_out.update(south_nodes_to_add)

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
            "bodies": bodies_out,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
