import json
from urllib.parse import urlencode
from urllib.request import urlopen

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def get_json(url, **params):
    with urlopen(f"{url}?{urlencode(params)}", timeout=8) as response:
        return json.load(response)


def find_city(name):
    data = get_json(GEOCODING_URL, name=name, count=1, language="ru")
    results = data.get("results", [])
    if not results:
        return None
    city = results[0]
    label = ", ".join(dict.fromkeys(
        city[key] for key in ("name", "admin1", "country") if city.get(key)
    ))
    return label, city["latitude"], city["longitude"]


def get_weather(place):
    label, latitude, longitude = place
    data = get_json(
        WEATHER_URL,
        latitude=latitude,
        longitude=longitude,
        current="temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m",
        wind_speed_unit="ms",
        timezone="auto",
    )
    current = data["current"]
    return (
        f"📍 {label}\n"
        f"Температура: {current['temperature_2m']:+.1f} °C\n"
        f"Ощущается как: {current['apparent_temperature']:+.1f} °C\n"
        f"Влажность: {current['relative_humidity_2m']} %\n"
        f"Ветер: {current['wind_speed_10m']:.1f} м/с"
    )


if __name__ == "__main__":
    print(get_weather(find_city("Москва")))
