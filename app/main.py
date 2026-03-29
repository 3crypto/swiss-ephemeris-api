import os
import time

from fastapi import FastAPI, HTTPException, Query, Request, Response

from .schemas import ChartResponse, NatalChartInput
from .astro_core.settings import init_ephemeris
from .astro_core.ephemeris import compute_chart
from .astro_core.daily_transits import (
    DailyTransitRuleEngine,
    build_positions_from_chart_response,
    build_positions_from_natal_input,
    serialize_positions,
    sect_from_user_natal_input,
)

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


@app.post("/chart_from_input")
def chart_from_input(natal_chart: NatalChartInput):
    sign_to_index = {
        "Aries": 0,
        "Taurus": 1,
        "Gemini": 2,
        "Cancer": 3,
        "Leo": 4,
        "Virgo": 5,
        "Libra": 6,
        "Scorpio": 7,
        "Sagittarius": 8,
        "Capricorn": 9,
        "Aquarius": 10,
        "Pisces": 11,
    }

    def format_position(degree: int, minute: int, sign: str, house: int) -> str:
        return f"{degree:02d}°{minute:02d}′ {sign} (House {house})"

    try:
        bodies = {}

        for body_name, body in natal_chart.bodies.items():
            longitude = sign_to_index[body.sign] * 30 + body.degree + (body.minute / 60.0)
            deg_in_sign = body.degree + (body.minute / 60.0)

            bodies[body_name] = {
                "longitude": longitude,
                "sign": body.sign,
                "deg_in_sign": deg_in_sign,
                "house_whole_sign": body.house_whole_sign,
                "display": format_position(
                    degree=body.degree,
                    minute=body.minute,
                    sign=body.sign,
                    house=body.house_whole_sign,
                ),
                "speed": None,
            }

        asc = bodies["Ascendant"]["longitude"]
        mc = bodies["Midheaven"]["longitude"]
        dsc = (asc + 180.0) % 360.0
        ic = (mc + 180.0) % 360.0

        return {
            "source": "user_input",
            "zodiac": natal_chart.zodiac,
            "ayanamsa": {
                "name": natal_chart.ayanamsa,
                "degrees": None,
            },
            "angles": {
                "asc": asc,
                "asc_sign": bodies["Ascendant"]["sign"],
                "dsc": dsc,
                "mc": mc,
                "mc_sign": bodies["Midheaven"]["sign"],
                "ic": ic,
                "asc_display": bodies["Ascendant"]["display"],
                "dsc_display": None,
                "mc_display": bodies["Midheaven"]["display"],
                "ic_display": None,
                "asc_house_whole_sign": bodies["Ascendant"]["house_whole_sign"],
                "dsc_house_whole_sign": ((bodies["Ascendant"]["house_whole_sign"] + 5) % 12) + 1,
                "mc_house_whole_sign": bodies["Midheaven"]["house_whole_sign"],
                "ic_house_whole_sign": ((bodies["Midheaven"]["house_whole_sign"] + 5) % 12) + 1,
            },
            "bodies": bodies,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/daily_transits")
def daily_transits(
    natal_chart: NatalChartInput,
    transit_year: int = Query(...),
    transit_month: int = Query(...),
    transit_day: int = Query(...),
    transit_hour: int = 0,
    transit_minute: int = 0,
    transit_second: float = 0.0,
    transit_tz_name: str = Query(...),
    transit_lat: float = Query(...),
    transit_lon: float = Query(...),
    sect: str = "auto",
    minute_tol_arcmin: float = 1.59,
    zodiac: str = "tropical",
    ayanamsa: str = "fagan_bradley",
    mode: str = "qualifying",
):
    try:
        transit_chart = compute_chart(
            year=transit_year,
            month=transit_month,
            day=transit_day,
            hour=transit_hour,
            minute=transit_minute,
            second=transit_second,
            tz_name=transit_tz_name,
            lat=transit_lat,
            lon=transit_lon,
            zodiac=zodiac,
            ayanamsa=ayanamsa,
        )

        sect_norm = (sect or "auto").lower().strip()
        if sect_norm == "auto":
            sect_used = sect_from_user_natal_input(natal_chart)
        else:
            if sect_norm not in {"diurnal", "nocturnal"}:
                raise HTTPException(
                    status_code=400,
                    detail="sect must be 'auto', 'diurnal', or 'nocturnal'",
                )
            sect_used = sect_norm

        natal = build_positions_from_natal_input(natal_chart, sect=sect_used)
        transits = build_positions_from_chart_response(
            transit_chart,
            sect=sect_used,
            include_pof=False,
        )

        engine = DailyTransitRuleEngine(
            sect=sect_used,
            minute_tolerance_arcmin=minute_tol_arcmin,
        )
        mode_norm = (mode or "qualifying").lower().strip()

        natal_asc = natal["Ascendant"].longitude

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

        raise HTTPException(
            status_code=400,
            detail="mode must be one of: qualifying, all, both",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
