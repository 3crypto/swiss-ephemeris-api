from typing import Dict, Optional
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

    # display-only fields
    asc_display: Optional[str] = None
    dsc_display: Optional[str] = None
    mc_display: Optional[str] = None
    ic_display: Optional[str] = None

    # NEW: Whole Sign house numbers
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
