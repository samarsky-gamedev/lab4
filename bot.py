import asyncio
import json
import logging
import os
import sqlite3
from contextlib import closing
from urllib.parse import urlencode
from urllib.request import urlopen

from telegram import BotCommand, KeyboardButton, ReplyKeyboardMarkup
from telegram.error import InvalidToken
from telegram.ext import Application, CommandHandler, MessageHandler, filters

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
DB_PATH = os.environ.get("WEATHER_DB", "weather.sqlite3")


def get_json(url, **params):
    with urlopen(f"{url}?{urlencode(params)}", timeout=8) as response:
        return json.load(response)


def find_city(name):
    data = get_json(GEOCODING_URL, name=name, count=1, language="ru")
    results = data.get("results", [])
    if not results:
        return None
    city = results[0]
    parts = (city.get(key) for key in ("name", "admin1", "country"))
    label = ", ".join(dict.fromkeys(part for part in parts if part))
    return label, city["latitude"], city["longitude"]


def get_weather(place):
    label, latitude, longitude = place
    data = get_json(
        WEATHER_URL,
        latitude=latitude,
        longitude=longitude,
        current=(
            "temperature_2m,apparent_temperature,"
            "relative_humidity_2m,wind_speed_10m"
        ),
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


def saved_city(user_id, place=None):
    with closing(sqlite3.connect(DB_PATH)) as db, db:
        if place is not None:
            db.execute(
                "INSERT OR REPLACE INTO cities VALUES (?, ?, ?, ?)",
                (user_id, *place),
            )
            return place
        return db.execute(
            "SELECT label, latitude, longitude FROM cities WHERE user_id = ?",
            (user_id,),
        ).fetchone()


async def start(update, context):
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геопозицию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Напишите город или отправьте геопозицию.\n"
        "/weather Казань — узнать погоду в Казани.\n"
        "/setcity Казань — сохранить город.\n"
        "/weather — узнать погоду в сохранённом городе.",
        reply_markup=keyboard,
    )


async def reply_weather(update, context):
    message = update.message
    user_id = update.effective_user.id
    command = (message.text or "").split(maxsplit=1)
    save = bool(command and command[0].split("@")[0].lower() == "/setcity")

    try:
        if message.location:
            location = message.location
            place = ("Ваша геопозиция", location.latitude, location.longitude)
        else:
            name = " ".join(context.args) if context.args is not None else (
                message.text.strip()
            )
            if name:
                if not 2 <= len(name) <= 100:
                    await message.reply_text(
                        "Введите название от 2 до 100 символов."
                    )
                    return
                place = await asyncio.to_thread(find_city, name)
                if place is None:
                    await message.reply_text(
                        "Город не найден. Проверьте название."
                    )
                    return
            elif save:
                await message.reply_text(
                    "Укажите город, например /setcity Казань."
                )
                return
            else:
                place = saved_city(user_id)
                if place is None:
                    await message.reply_text(
                        "Укажите город или сохраните его командой /setcity."
                    )
                    return

        if save:
            saved_city(user_id, place)
            answer = (
                f"Сохранённый город: {place[0]}. Узнать погоду — /weather."
            )
        else:
            answer = await asyncio.to_thread(get_weather, place)
    except sqlite3.Error:
        answer = "Не удалось открыть настройки. Попробуйте позже."
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        answer = "Сервис погоды временно недоступен. Попробуйте позже."

    await message.reply_text(answer)


async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Как пользоваться ботом"),
        BotCommand("weather", "Показать погоду"),
        BotCommand("setcity", "Сохранить город"),
    ])


async def log_error(update, context):
    logging.error("Ошибка Telegram: %s", type(context.error).__name__)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте переменную TELEGRAM_BOT_TOKEN.")

    # В базе хранится один выбранный город на пользователя Telegram.
    with closing(sqlite3.connect(DB_PATH)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS cities (user_id INTEGER PRIMARY KEY, "
            "label TEXT NOT NULL, latitude REAL NOT NULL, "
            "longitude REAL NOT NULL)"
        )

    private = filters.ChatType.PRIVATE
    app = Application.builder().token(token).post_init(set_commands).build()
    app.add_handler(CommandHandler("start", start, filters=private))
    app.add_handler(CommandHandler(
        ["weather", "setcity"], reply_weather, filters=private,
    ))
    app.add_handler(MessageHandler(
        private & (filters.LOCATION | (filters.TEXT & ~filters.COMMAND)),
        reply_weather,
    ))
    app.add_error_handler(log_error)
    try:
        app.run_polling(allowed_updates=["message"])
    except InvalidToken:
        raise SystemExit("Telegram не принял токен бота.") from None


if __name__ == "__main__":
    main()
