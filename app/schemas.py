from typing import Dict, Optional, Literal, List
from pydantic import BaseModel, Field, model_validator

# -----------------------------
# Natal Input Models (internal)
# -----------------------------

SignLiteral = Literal[
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

class NatalBodyInput(BaseModel):
    degree: int = Field(..., ge=0, le=29)
    minute: int = Field(..., ge=0, le=59)
    sign: SignLiteral
    house_whole_sign: int = Field(..., ge=1, le=12)


class NatalChartInput(BaseModel):
    zodiac: Literal["tropical", "sidereal"] = "tropical"
    ayanamsa: Optional[str] = None
    bodies: Dict[str, NatalBodyInput]

    @model_validator(mode="after")
    def validate_required_bodies(self):
        required = {
            "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
            "Uranus", "Neptune", "Pluto", "Chiron", "North Node",
            "Ascendant", "Midheaven", "Part of Fortune"
        }
        missing = required - set(self.bodies.keys())
        if missing:
            raise ValueError(f"Missing natal bodies: {sorted(missing)}")
        return self


# -----------------------------
# Frontend-facing Request Models
# -----------------------------

class NatalPlanetInput(BaseModel):
    """Single planet entry as sent by the frontend (array format)."""
    planet: str
    degree: int = Field(..., ge=0, le=29)
    minute: int = Field(..., ge=0, le=59)
    second: int = Field(default=0, ge=0, le=59)
    sign: SignLiteral
    house: int = Field(..., ge=1, le=12)


class ChartFromInputRequest(BaseModel):
    """
    Request body for /chart_from_input.
    Used when natal planet positions are already known (stored from a previous call).
    Computes transits against those natal positions.
    """
    natal_chart: List[NatalPlanetInput]
    transit_year: int
    transit_month: int
    transit_day: int
    transit_hour: int = 0
    transit_minute: int = 0
    transit_second: float = 0.0
    transit_tz_name: str
    transit_lat: float
    transit_lon: float
    zodiac: Literal["tropical", "sidereal"] = "tropical"
    ayanamsa: Optional[str] = None
    sect: str = "auto"
    mode: str = "qualifying"
    minute_tol_arcmin: float = 1.59


class DailyTransitsRequest(BaseModel):
    """
    Request body for /daily_transits.
    Used when only birth date/time/location is known — computes the natal chart first,
    then computes transits.
    """
    natal_year: int
    natal_month: int
    natal_day: int
    natal_hour: int = 0
    natal_minute: int = 0
    natal_second: float = 0.0
    natal_tz_name: str
    natal_lat: float
    natal_lon: float
    transit_year: int
    transit_month: int
    transit_day: int
    transit_hour: int = 0
    transit_minute: int = 0
    transit_second: float = 0.0
    transit_tz_name: str
    transit_lat: float
    transit_lon: float
    zodiac: Literal["tropical", "sidereal"] = "tropical"
    ayanamsa: Optional[str] = None
    sect: str = "auto"
    mode: str = "qualifying"
    minute_tol_arcmin: float = 1.59


# -----------------------------
# Response Models
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

    # display-only fields
    asc_display: Optional[str] = None
    dsc_display: Optional[str] = None
    mc_display: Optional[str] = None
    ic_display: Optional[str] = None

    # Whole Sign house numbers
    asc_house_whole_sign: Optional[int] = None
    dsc_house_whole_sign: Optional[int] = None
    mc_house_whole_sign: Optional[int] = None
    ic_house_whole_sign: Optional[int] = None


class BodyModel(BaseModel):
    longitude: float
    sign: str
    deg_in_sign: float
    house_whole_sign: int
    display: str
    speed: Optional[float] = None


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
# Qualifying Transit Response Models
# -----------------------------

class AspectModel(BaseModel):
    transiting_body: str
    natal_body: str
    aspect: str
    exact_angle: float
    orb_degrees: float
    applying: Optional[bool] = None


class QualifyingTransitResponse(BaseModel):
    natal_source: str
    transit_dt_local: str
    transit_dt_utc: str
    jd_ut: float
    zodiac: str
    ayanamsa: Optional[AyanamsaModel] = None
    natal_bodies: Dict[str, BodyModel]
    transit_bodies: Dict[str, BodyModel]
    qualifying_aspects: List[AspectModel]
