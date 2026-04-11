import os
import time

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .schemas import ChartResponse, NatalChartInput, ChartFromInputRequest, DailyTransitsRequest
from .astro_core.settings import init_ephemeris
from .astro_core.ephemeris import compute_chart
from .astro_core.daily_transits import (
    DailyTransitRuleEngine,
    BodyPosition,
    build_positions_from_chart_response,
    build_positions_from_natal_input,
    serialize_positions,
    sect_from_user_natal_input,
    calc_part_of_fortune,
    whole_sign_house,
    SIGN_TO_INDEX,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPHE_PATH = os.path.join(PROJECT_ROOT, "ephe")


@app.on_event("startup")
def _startup():
    init_ephemeris(EPHE_PATH)


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


def _resolve_sect(sect_param: str, sun_house: int) -> str:
    """Determine sect from request param, falling back to auto-detect from Sun's house."""
    sect_norm = sect_param.lower().strip()
    if sect_norm == "auto":
        if 1 <= sun_house <= 6:
            return "nocturnal"
        if 7 <= sun_house <= 12:
            return "diurnal"
        raise HTTPException(status_code=400, detail=f"Cannot determine sect: invalid Sun house {sun_house}")
    if sect_norm not in {"diurnal", "nocturnal"}:
        raise HTTPException(status_code=400, detail="sect must be 'auto', 'diurnal', or 'nocturnal'")
    return sect_norm


def _run_engine(
    engine: DailyTransitRuleEngine,
    transits: dict,
    natal: dict,
    natal_asc: float,
    sect_used: str,
    minute_tol_arcmin: float,
    mode: str,
) -> dict:
    mode_norm = mode.lower().strip()

    if mode_norm == "qualifying":
        hits = engine.run_qualifying(transits=transits, natal=natal)
        return {
            "mode": "qualifying",
            "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
            "transits": serialize_positions(transits, ascendant_lon=natal_asc),
            "hits": [h.to_json() for h in hits],
        }

    if mode_norm == "all":
        hits = engine.run_all(transits=transits, natal=natal)
        return {
            "mode": "all",
            "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
            "transits": serialize_positions(transits, ascendant_lon=natal_asc),
            "hits": [h.to_json() for h in hits],
        }

    if mode_norm == "both":
        qualifying = engine.run_qualifying(transits=transits, natal=natal)
        all_hits = engine.run_all(transits=transits, natal=natal)
        return {
            "mode": "both",
            "rules": {"sect": sect_used, "minute_tol_arcmin": minute_tol_arcmin},
            "transits": serialize_positions(transits, ascendant_lon=natal_asc),
            "qualifying_hits": [h.to_json() for h in qualifying],
            "all_hits": [h.to_json() for h in all_hits],
        }

    raise HTTPException(status_code=400, detail="mode must be one of: qualifying, all, both")


@app.post("/chart_from_input")
def chart_from_input(request: ChartFromInputRequest):
    """
    Accepts natal planet positions (array format from frontend) + transit date/location.
    Computes transiting aspects to the provided natal positions.
    """
    try:
        # Index planets by name for easy lookup
        planets_by_name = {p.planet: p for p in request.natal_chart}

        sun = planets_by_name.get("Sun")
        if not sun:
            raise HTTPException(status_code=400, detail="Missing 'Sun' in natal_chart")

        sect_used = _resolve_sect(request.sect, sun.house)

        # Build natal positions dict from array
        natal: dict = {}
        for p in request.natal_chart:
            lon = SIGN_TO_INDEX[p.sign] * 30.0 + p.degree + (p.minute / 60.0)
            natal[p.planet] = BodyPosition(longitude=lon, speed=None)

        # Compute Part of Fortune only if the user didn't supply it
        if "Part of Fortune" not in natal:
            asc_pos = natal.get("Ascendant")
            sun_pos = natal.get("Sun")
            moon_pos = natal.get("Moon")
            if asc_pos and sun_pos and moon_pos:
                pof_lon = calc_part_of_fortune(
                    asc_lon=asc_pos.longitude,
                    sun_lon=sun_pos.longitude,
                    moon_lon=moon_pos.longitude,
                    sect=sect_used,
                )
                natal["Part of Fortune"] = BodyPosition(longitude=pof_lon)

        # Compute transit chart
        transit_chart = compute_chart(
            year=request.transit_year,
            month=request.transit_month,
            day=request.transit_day,
            hour=request.transit_hour,
            minute=request.transit_minute,
            second=request.transit_second,
            tz_name=request.transit_tz_name,
            lat=request.transit_lat,
            lon=request.transit_lon,
            zodiac=request.zodiac,
            ayanamsa=request.ayanamsa or "fagan_bradley",
        )

        transits = build_positions_from_chart_response(
            transit_chart,
            sect=sect_used,
            include_pof=False,
        )

        engine = DailyTransitRuleEngine(
            sect=sect_used,
            minute_tolerance_arcmin=request.minute_tol_arcmin,
        )

        natal_asc = natal["Ascendant"].longitude

        return _run_engine(
            engine=engine,
            transits=transits,
            natal=natal,
            natal_asc=natal_asc,
            sect_used=sect_used,
            minute_tol_arcmin=request.minute_tol_arcmin,
            mode=request.mode,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/daily_transits")
def daily_transits(request: DailyTransitsRequest):
    """
    Accepts birth date/time/location + transit date/time/location.
    Computes the natal chart from birth details, then computes transiting aspects.
    """
    try:
        ayanamsa = request.ayanamsa or "fagan_bradley"

        # Compute natal chart from birth details
        natal_chart = compute_chart(
            year=request.natal_year,
            month=request.natal_month,
            day=request.natal_day,
            hour=request.natal_hour,
            minute=request.natal_minute,
            second=request.natal_second,
            tz_name=request.natal_tz_name,
            lat=request.natal_lat,
            lon=request.natal_lon,
            zodiac=request.zodiac,
            ayanamsa=ayanamsa,
        )

        # Compute transit chart
        transit_chart = compute_chart(
            year=request.transit_year,
            month=request.transit_month,
            day=request.transit_day,
            hour=request.transit_hour,
            minute=request.transit_minute,
            second=request.transit_second,
            tz_name=request.transit_tz_name,
            lat=request.transit_lat,
            lon=request.transit_lon,
            zodiac=request.zodiac,
            ayanamsa=ayanamsa,
        )

        # Determine sect from natal Sun's house
        sect_norm = request.sect.lower().strip()
        if sect_norm == "auto":
            natal_bodies = natal_chart.get("bodies", {})
            natal_angles = natal_chart.get("angles", {})
            sun_body = natal_bodies.get("sun")
            if sun_body:
                asc_lon = natal_angles.get("asc", 0.0)
                sun_lon = sun_body.get("longitude", 0.0)
                sun_house = whole_sign_house(asc_lon, sun_lon)
                sect_used = "nocturnal" if 1 <= sun_house <= 6 else "diurnal"
            else:
                sect_used = "diurnal"
        else:
            if sect_norm not in {"diurnal", "nocturnal"}:
                raise HTTPException(
                    status_code=400,
                    detail="sect must be 'auto', 'diurnal', or 'nocturnal'",
                )
            sect_used = sect_norm

        natal = build_positions_from_chart_response(
            natal_chart,
            sect=sect_used,
            include_pof=True,
        )
        transits = build_positions_from_chart_response(
            transit_chart,
            sect=sect_used,
            include_pof=False,
        )

        engine = DailyTransitRuleEngine(
            sect=sect_used,
            minute_tolerance_arcmin=request.minute_tol_arcmin,
        )

        natal_asc = natal["Ascendant"].longitude

        return _run_engine(
            engine=engine,
            transits=transits,
            natal=natal,
            natal_asc=natal_asc,
            sect_used=sect_used,
            minute_tol_arcmin=request.minute_tol_arcmin,
            mode=request.mode,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
