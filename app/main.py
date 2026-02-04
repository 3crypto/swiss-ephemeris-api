import os
import time

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .schemas import ChartResponse
from .astro_core.settings import init_ephemeris
from .astro_core.ephemeris import compute_chart
from .astro_core.daily_transits import (
    DailyTransitRuleEngine,
    build_positions_from_chart_response,
    serialize_positions,
)

def sect_from_natal_chart(natal_chart: dict) -> str:
    """
    User-defined sect rule:
      - Sun in houses 1–6  => nocturnal
      - Sun in houses 7–12 => diurnal

    Expects natal_chart from compute_chart() where:
      natal_chart["bodies"]["sun"]["house_whole_sign"] exists.
    """
    bodies = natal_chart.get("bodies", {})
    sun = bodies.get("sun")
    if not sun:
        raise ValueError("Cannot determine sect: natal_chart is missing bodies['sun'].")

    house = sun.get("house_whole_sign")
    if house is None:
        raise ValueError("Cannot determine sect: natal_chart['bodies']['sun'] missing 'house_whole_sign'.")

    house_i = int(house)
    if 1 <= house_i <= 6:
        return "nocturnal"
    if 7 <= house_i <= 12:
        return "diurnal"

    raise ValueError(f"Cannot determine sect: invalid Sun house_whole_sign={house_i}.")


app = FastAPI()

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


# Swiss Ephemeris setup (expects /.../swiss_api/ephe)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHE_PATH = os.path.join(PROJECT_ROOT, "ephe")

@app.on_event("startup")
def _startup():
    init_ephemeris(EPHE_PATH)


@app.get("/")
def home():
    return {"status": "Swiss API is running"}

@app.api_route("/", methods=["HEAD"], include_in_schema=False)
def home_head():
    return Response(status_code=200)


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
    sect: str = "auto",
):
    try:
        return compute_chart(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=second,
            tz_name=tz_name,
            lat=lat,
            lon=lon,
            zodiac=zodiac,
            ayanamsa=ayanamsa,
            sect=sect,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/daily_transits")
def daily_transits(
    # natal inputs
    natal_year: int,
    natal_month: int,
    natal_day: int,
    natal_hour: int = 0,
    natal_minute: int = 0,
    natal_second: float = 0.0,
    natal_tz_name: str = Query(...),
    natal_lat: float = Query(...),
    natal_lon: float = Query(...),

    # transit inputs
    transit_year: int = Query(...),
    transit_month: int = Query(...),
    transit_day: int = Query(...),
    transit_hour: int = 0,
    transit_minute: int = 0,
    transit_second: float = 0.0,
    transit_tz_name: str = Query(...),
    transit_lat: float = Query(...),
    transit_lon: float = Query(...),

    # rules inputs
    sect: str = "auto",
    minute_tol_arcmin: float = 1.59,
    zodiac: str = "tropical",
    ayanamsa: str = "fagan_bradley",

    # output mode
    mode: str = "qualifying",  # "qualifying" | "all" | "both"
):
    try:
        # 1) Compute charts
        natal_chart = compute_chart(
            year=natal_year, month=natal_month, day=natal_day,
            hour=natal_hour, minute=natal_minute, second=natal_second,
            tz_name=natal_tz_name, lat=natal_lat, lon=natal_lon,
            zodiac=zodiac, ayanamsa=ayanamsa,
        )
        transit_chart = compute_chart(
            year=transit_year, month=transit_month, day=transit_day,
            hour=transit_hour, minute=transit_minute, second=transit_second,
            tz_name=transit_tz_name, lat=transit_lat, lon=transit_lon,
            zodiac=zodiac, ayanamsa=ayanamsa,
        )

        # 2) Determine sect_used BEFORE building positions (fixes your 400 error)
        sect_norm = (sect or "auto").lower().strip()
        if sect_norm == "auto":
            sect_used = sect_from_natal_chart(natal_chart)
        else:
            if sect_norm not in {"diurnal", "nocturnal"}:
                raise HTTPException(status_code=400, detail="sect must be 'auto', 'diurnal', or 'nocturnal'")
            sect_used = sect_norm

        # 3) Build positions
        #    - PoF always included for natal
        #    - PoF never included for transits
        natal = build_positions_from_chart_response(natal_chart, sect=sect_used, include_pof=True)
        transits = build_positions_from_chart_response(transit_chart, sect=sect_used, include_pof=False)

        # 4) Run engine
        engine = DailyTransitRuleEngine(sect=sect_used, minute_tolerance_arcmin=minute_tol_arcmin)
        mode_norm = (mode or "qualifying").lower().strip()

        if mode_norm == "qualifying":
            hits = engine.run_qualifying(transits=transits, natal=natal)
            return {
                "mode": "qualifying",
                "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
                "transits": serialize_positions(transits),
                "hits": [h.to_json() for h in hits],
            }

        if mode_norm == "all":
            hits = engine.run_all(transits=transits, natal=natal)
            return {
                "mode": "all",
                "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
                "transits": serialize_positions(transits),
                "hits": [h.to_json() for h in hits],
            }

        if mode_norm == "both":
            qualifying = engine.run_qualifying(transits=transits, natal=natal)
            all_hits = engine.run_all(transits=transits, natal=natal)
            return {
                "mode": "both",
                "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
                "transits": serialize_positions(transits),
                "qualifying_hits": [h.to_json() for h in qualifying],
                "all_hits": [h.to_json() for h in all_hits],
            }

        raise HTTPException(status_code=400, detail="mode must be one of: qualifying, all, both")

    except HTTPException:
        # Preserve explicit HTTP errors
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))




