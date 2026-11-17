"""El tiempo de hoy en la ciudad de Ajustes, con Open-Meteo (gratuito, sin clave).

Solo sale del servidor el nombre de la ciudad (para buscar sus coordenadas) y esas coordenadas.
Si Open-Meteo no responde, la app sigue funcionando: el outfit se decide por la época del año.
"""
import logging
import time
from dataclasses import asdict, dataclass

import httpx

log = logging.getLogger("armario.tiempo")

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"
_CACHE_SECONDS = 30 * 60

_places: dict[str, tuple[float, float, str] | None] = {}
_forecasts: dict[str, tuple[float, "Weather"]] = {}

# Códigos WMO que devuelve Open-Meteo -> (descripción, icono de la app).
_CODES = {
    0: ("Despejado", "sunny"),
    1: ("Poco nuboso", "weather"),
    2: ("Parcialmente nublado", "weather"),
    3: ("Nublado", "cloud"),
    45: ("Niebla", "cloud"),
    48: ("Niebla", "cloud"),
    51: ("Llovizna", "rain"),
    53: ("Llovizna", "rain"),
    55: ("Llovizna", "rain"),
    61: ("Lluvia débil", "rain"),
    63: ("Lluvia", "rain"),
    65: ("Lluvia fuerte", "rain"),
    66: ("Lluvia helada", "rain"),
    67: ("Lluvia helada", "rain"),
    71: ("Nieve débil", "snow"),
    73: ("Nieve", "snow"),
    75: ("Nieve fuerte", "snow"),
    77: ("Nieve", "snow"),
    80: ("Chubascos", "rain"),
    81: ("Chubascos", "rain"),
    82: ("Chubascos fuertes", "rain"),
    85: ("Chubascos de nieve", "snow"),
    86: ("Chubascos de nieve", "snow"),
    95: ("Tormenta", "rain"),
    96: ("Tormenta con granizo", "rain"),
    99: ("Tormenta con granizo", "rain"),
}


@dataclass
class Weather:
    city: str
    temp_now: float
    temp_max: float
    temp_min: float
    rain_probability: int  # 0-100
    description: str
    icon: str

    def as_dict(self) -> dict:
        return asdict(self)


def describe(code: int | None) -> tuple[str, str]:
    return _CODES.get(code if code is not None else -1, ("Sin datos", "weather"))


def _locate(city: str, client: httpx.Client) -> tuple[float, float, str] | None:
    key = city.strip().lower()
    if key not in _places:
        response = client.get(_GEOCODE, params={"name": city.strip(), "count": 1, "language": "es"})
        response.raise_for_status()
        results = response.json().get("results") or []
        _places[key] = (
            (results[0]["latitude"], results[0]["longitude"], results[0].get("name", city)) if results else None
        )
    return _places[key]


def parse_forecast(city: str, data: dict) -> Weather:
    current, daily = data["current"], data["daily"]
    description, icon = describe(daily["weather_code"][0])
    return Weather(
        city=city,
        temp_now=round(current["temperature_2m"]),
        temp_max=round(daily["temperature_2m_max"][0]),
        temp_min=round(daily["temperature_2m_min"][0]),
        rain_probability=int(daily["precipitation_probability_max"][0] or 0),
        description=description,
        icon=icon,
    )


def today(city: str) -> Weather | None:
    """El tiempo de hoy, o None si no se puede saber (sin red, ciudad desconocida…)."""
    key = city.strip().lower()
    cached = _forecasts.get(key)
    if cached and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    try:
        with httpx.Client(timeout=8) as client:
            place = _locate(city, client)
            if not place:
                return None
            lat, lon, name = place
            response = client.get(
                _FORECAST,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
            response.raise_for_status()
            weather = parse_forecast(name, response.json())
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        log.warning("No se pudo leer el tiempo de %s: %s", city, exc)
        return None
    _forecasts[key] = (time.time(), weather)
    return weather
