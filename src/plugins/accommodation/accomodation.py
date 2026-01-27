from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
import os
import requests
import logging
from datetime import datetime, timedelta, timezone, date
from astral import moon
import pytz
from io import BytesIO
import math

logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={long}&units={units}&exclude=minutely&appid={api_key}"
AIR_QUALITY_URL = "http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={long}&appid={api_key}"
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={long}&limit=1&appid={api_key}"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&hourly=temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,surface_pressure,visibility&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current_weather=true&timezone=auto&models=best_match&forecast_days={forecast_days}"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={long}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone=auto"
OPEN_METEO_UNIT_PARAMS = {
    "standard": "temperature_unit=kelvin&wind_speed_unit=ms&precipitation_unit=mm",
    "metric":   "temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm",
    "imperial": "temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
}

class Accommodation(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        lat = float(settings.get('latitude'))
        long = float(settings.get('longitude'))
        if not lat or not long:
            raise RuntimeError("Szerokość i długość są wymagane.")

        units = settings.get('units')
        if not units or units not in ['metric', 'imperial', 'standard']:
            raise RuntimeError("Jednostki są wymagane.")

        weather_provider = settings.get('weatherProvider', 'OpenMeteo')

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="24h")
        tz = pytz.timezone(timezone)

        try:
            if weather_provider == "OpenMeteo":
                forecast_days = 7
                weather_data = self.get_open_meteo_data(lat, long, units, forecast_days + 1)
                aqi_data = self.get_open_meteo_air_quality(lat, long)
                template_params = self.parse_open_meteo_data(weather_data, aqi_data, tz, units, time_format, lat)
            else:
                raise RuntimeError(f"Nieznany dostawca pogody: {weather_provider}")
        except Exception as e:
            logger.error(f"{weather_provider} request failed: {str(e)}")
            raise RuntimeError(f"{weather_provider} request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        template_params["plugin_settings"] = settings

        image = self.render_image(dimensions, "accommodation.html", "accommodation.css", template_params)

        if not image:
            raise RuntimeError("Problem ze zrobieniem screenshota, proszę sprawdź logi.")
        return image

    def parse_open_meteo_data(self, weather_data, aqi_data, tz, units, time_format, lat):
        current = weather_data.get("current_weather", {})
        dt = datetime.fromisoformat(current.get('time')).astimezone(tz) if current.get('time') else datetime.now(tz)
        weather_code = current.get("weathercode", 0)
        is_day = current.get("is_day", 1)
        current_icon = self.map_weather_code_to_icon(weather_code, is_day)

        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current.get("temperature", 0))),
            "feels_like": str(round(current.get("apparent_temperature", current.get("temperature", 0)))),
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }

        data['forecast'] = self.parse_open_meteo_forecast(weather_data.get('daily', {}), tz, is_day, lat)
        data['data_points'] = self.parse_open_meteo_data_points(weather_data, aqi_data, tz, units, time_format)

        return data

    def map_weather_code_to_icon(self, weather_code, is_day):

        icon = "01d" # Default to clear day icon

        if weather_code in [0]:   # Clear sky
            icon = "01d"
        elif weather_code in [1]: # Mainly clear
            icon = "022d"
        elif weather_code in [2]: # Partly cloudy
            icon = "02d"
        elif weather_code in [3]: # Overcast
            icon = "04d"
        elif weather_code in [51, 61, 80]: # Drizzle, showers, rain: Light
            icon = "51d"
        elif weather_code in [53, 63, 81]: # Drizzle, showers, rain: Moderatr
            icon = "53d"
        elif weather_code in [55, 65, 82]: # Drizzle, showers, rain: Heavy
            icon = "09d"
        elif weather_code in [45]: # Fog
            icon = "50d"
        elif weather_code in [48]: # Icy fog
            icon = "48d"
        elif weather_code in [56, 66]: # Light freezing Drizzle
            icon = "56d"
        elif weather_code in [57, 67]: # Freezing Drizzle
            icon = "57d"
        elif weather_code in [71, 85]: # Snow fall: Slight
            icon = "71d"
        elif weather_code in [73]:     # Snow fall: Moderate
            icon = "73d"
        elif weather_code in [75, 86]: # Snow fall: Heavy
            icon = "13d"
        elif weather_code in [77]:     # Snow grain
            icon = "77d"
        elif weather_code in [95]: # Thunderstorm
            icon = "11d"
        elif weather_code in [96, 99]: # Thunderstorm with slight and heavy hail
            icon = "11d"

        if is_day == 0:
            if icon == "01d":
                icon = "01n"      # Clear sky night
            elif icon == "022d":
                icon = "022n"     # Mainly clear night
            elif icon == "02d":
                icon = "02n"      # Partly cloudy night
            elif icon == "10d":
                icon = "10n"      # Rain night

        return icon

    def parse_open_meteo_forecast(self, daily_data, tz, is_day, lat):
        """
        Parse the daily forecast from Open-Meteo API and calculate moon phase and illumination using the local 'astral' library.
        """
        times = daily_data.get('time', [])
        weather_codes = daily_data.get('weathercode', [])
        temp_max = daily_data.get('temperature_2m_max', [])
        temp_min = daily_data.get('temperature_2m_min', [])

        forecast = []

        for i in range(0, len(times)):
            dt = datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc).astimezone(tz)
            day_label = dt.strftime("%a")

            code = weather_codes[i] if i < len(weather_codes) else 0
            weather_icon = self.map_weather_code_to_icon(code, is_day)
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            timestamp = int(dt.replace(hour=12, minute=0, second=0).timestamp())
            target_date: date = dt.date() + timedelta(days=1)

            try:
                phase_age = moon.phase(target_date)
                phase_name_north_hemi = get_moon_phase_name(phase_age)
                LUNAR_CYCLE_DAYS = 29.530588853
                phase_fraction = phase_age / LUNAR_CYCLE_DAYS
                illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
            except Exception as e:
                logger.error(f"Error calculating moon phase for {target_date}: {e}")
                illum_pct = 0
                phase_name = "newmoon"
            moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)

            forecast.append({
                "day": day_label,
                "high": int(temp_max[i]) if i < len(temp_max) else 0,
                "low": int(temp_min[i]) if i < len(temp_min) else 0,
                "icon": weather_icon_path,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path
            })

        return forecast

    def parse_open_meteo_data_points(self, weather_data, aqi_data, tz, units, time_format):
        """Parses current data points from Open-Meteo API response."""
        data_points = []
        daily_data = weather_data.get('daily', {})
        current_data = weather_data.get('current_weather', {})
        hourly_data = weather_data.get('hourly', {})

        current_time = datetime.now(tz)

        # Sunrise
        sunrise_times = daily_data.get('sunrise', [])
        if sunrise_times:
            sunrise_dt = datetime.fromisoformat(sunrise_times[0]).astimezone(tz)
            data_points.append({
                "label": "Wschód",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logging.error(f"Sunrise not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Sunset
        sunset_times = daily_data.get('sunset', [])
        if sunset_times:
            sunset_dt = datetime.fromisoformat(sunset_times[0]).astimezone(tz)
            data_points.append({
                "label": "Zachód",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logging.error(f"Sunset not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Wind
        wind_speed = current_data.get("windspeed", 0)
        wind_deg = current_data.get("winddirection", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        wind_unit = UNITS[units]["speed"]
        data_points.append({
            "label": "Wiatr", "measurement": wind_speed, "unit": wind_unit,
            "icon": self.get_plugin_dir('icons/wind.png'), "arrow": wind_arrow
        })

        # Humidity
        current_humidity = "N/A"
        humidity_hourly_times = hourly_data.get('time', [])
        humidity_values = hourly_data.get('relative_humidity_2m', [])
        for i, time_str in enumerate(humidity_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    current_humidity = int(humidity_values[i])
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for humidity.")
                continue
        data_points.append({
            "label": "Wilgotność", "measurement": current_humidity, "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        # Pressure
        current_pressure = "N/A"
        pressure_hourly_times = hourly_data.get('time', [])
        pressure_values = hourly_data.get('surface_pressure', [])
        for i, time_str in enumerate(pressure_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    current_pressure = int(pressure_values[i])
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for pressure.")
                continue
        data_points.append({
            "label": "Ciśnienie", "measurement": current_pressure, "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        # UV Index
        uv_index_hourly_times = aqi_data.get('hourly', {}).get('time', [])
        uv_index_values = aqi_data.get('hourly', {}).get('uv_index', [])
        current_uv_index = "N/A"
        for i, time_str in enumerate(uv_index_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    current_uv_index = uv_index_values[i]
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for UV Index.")
                continue
        data_points.append({
            "label": "Indeks UV", "measurement": current_uv_index, "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        # Visibility
        current_visibility = "N/A"
        visibility_hourly_times = hourly_data.get('time', [])
        visibility_values = hourly_data.get('visibility', [])
        for i, time_str in enumerate(visibility_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    visibility = visibility_values[i]
                    if units == "imperial":
                        current_visibility = int(round(visibility, 0))
                        unit_label = "ft"
                    else:
                        current_visibility = round(visibility / 1000, 1)
                        unit_label = "km"
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for visibility.")
                continue

        visibility_str = f">{current_visibility}" if isinstance(current_visibility, (int, float)) and (
            (units == "imperial" and current_visibility >= 32808) or
            (units != "imperial" and current_visibility >= 10)
        ) else current_visibility

        data_points.append({
            "label": "Widoczność", "measurement": visibility_str, "unit": unit_label,
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        # Air Quality
        aqi_hourly_times = aqi_data.get('hourly', {}).get('time', [])
        aqi_values = aqi_data.get('hourly', {}).get('european_aqi', [])
        current_aqi = "N/A"
        for i, time_str in enumerate(aqi_hourly_times):
            try:
                if datetime.fromisoformat(time_str).astimezone(tz).hour == current_time.hour:
                    current_aqi = round(aqi_values[i], 1)
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} for AQI.")
                continue
        scale = ""
        if current_aqi:
            scale = ["Good","Fair","Moderate","Poor","Very Poor","Ext Poor"][min(current_aqi//20,5)]
        data_points.append({
            "label": "Jakość Powietrza", "measurement": current_aqi,
            "unit": scale, "icon": self.get_plugin_dir('icons/aqi.png')
        })

        return data_points

    def get_wind_arrow(self, wind_deg: float) -> str:
        DIRECTIONS = [
            ("↓", 22.5),    # North (N)
            ("↙", 67.5),    # North-East (NE)
            ("←", 112.5),   # East (E)
            ("↖", 157.5),   # South-East (SE)
            ("↑", 202.5),   # South (S)
            ("↗", 247.5),   # South-West (SW)
            ("→", 292.5),   # West (W)
            ("↘", 337.5),   # North-West (NW)
            ("↓", 360.0)    # Wrap back to North
        ]
        wind_deg = wind_deg % 360
        for arrow, upper_bound in DIRECTIONS:
            if wind_deg < upper_bound:
                return arrow

        return "↑"

    def get_open_meteo_data(self, lat, long, units, forecast_days):
        unit_params = OPEN_METEO_UNIT_PARAMS[units]
        url = OPEN_METEO_FORECAST_URL.format(lat=lat, long=long, forecast_days=forecast_days) + f"&{unit_params}"
        response = requests.get(url)

        if not 200 <= response.status_code < 300:
            logging.error(f"Failed to retrieve Open-Meteo weather data: {response.content}")
            raise RuntimeError("Nie udało się pobrać danych pogodowych Open-Meteo.")

        return response.json()

    def get_open_meteo_air_quality(self, lat, long):
        url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long)
        response = requests.get(url)
        if not 200 <= response.status_code < 300:
            logging.error(f"Failed to retrieve Open-Meteo air quality data: {response.content}")
            raise RuntimeError("Nie udało się pobrać danych o jakości powietrza Open-Meteo.")

        return response.json()

    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        """Format datetime based on 12h or 24h preference"""
        if time_format == "24h":
            return dt.strftime("%H:00" if hour_only else "%H:%M")

        if include_am_pm:
            fmt = "%I %p" if hour_only else "%I:%M %p"
        else:
            fmt = "%I" if hour_only else "%I:%M"

        return dt.strftime(fmt).lstrip("0")
