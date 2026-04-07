from __future__ import annotations

import asyncio
from typing import Type

import httpx
from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


WMO_DESCRIPTIONS = {
    0: "晴朗",
    1: "少云",
    2: "多云",
    3: "阴天",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "冰粒",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "伴有小冰雹的雷暴",
    99: "伴有大冰雹的雷暴",
}

COMMON_LOCATIONS = {
    "北京": {"name": "北京", "latitude": 39.9042, "longitude": 116.4074, "admin1": "北京市", "country": "中国"},
    "上海": {"name": "上海", "latitude": 31.2304, "longitude": 121.4737, "admin1": "上海市", "country": "中国"},
    "南京": {"name": "南京", "latitude": 32.0603, "longitude": 118.7969, "admin1": "江苏省", "country": "中国"},
    "广州": {"name": "广州", "latitude": 23.1291, "longitude": 113.2644, "admin1": "广东省", "country": "中国"},
    "深圳": {"name": "深圳", "latitude": 22.5431, "longitude": 114.0579, "admin1": "广东省", "country": "中国"},
    "杭州": {"name": "杭州", "latitude": 30.2741, "longitude": 120.1551, "admin1": "浙江省", "country": "中国"},
    "成都": {"name": "成都", "latitude": 30.5728, "longitude": 104.0668, "admin1": "四川省", "country": "中国"},
    "重庆": {"name": "重庆", "latitude": 29.5630, "longitude": 106.5516, "admin1": "重庆市", "country": "中国"},
    "武汉": {"name": "武汉", "latitude": 30.5928, "longitude": 114.3055, "admin1": "湖北省", "country": "中国"},
    "西安": {"name": "西安", "latitude": 34.3416, "longitude": 108.9398, "admin1": "陕西省", "country": "中国"},
    "天津": {"name": "天津", "latitude": 39.0842, "longitude": 117.2009, "admin1": "天津市", "country": "中国"},
    "苏州": {"name": "苏州", "latitude": 31.2989, "longitude": 120.5853, "admin1": "江苏省", "country": "中国"},
}


class GetWeatherInput(BaseModel):
    query: str = Field(
        ...,
        description="The user's weather request or a city/location name, such as '北京现在天气' or 'Nanjing weather today'.",
    )


def _clean_location(query: str) -> str:
    cleaned = (query or "").strip()
    replacements = (
        "告诉我",
        "请问",
        "帮我",
        "为我",
        "查询",
        "查一下",
        "查查",
        "现在",
        "今天",
        "目前",
        "当前",
        "实时",
        "的",
        "天气情况",
        "天气",
        "当前天气",
        "现在天气",
        "今日天气",
        "今天天气",
        "情况",
        "气温",
        "温度",
        "怎么样",
        "如何",
        "多少",
        "一下",
        "吧",
        "呢",
        "呀",
        "？",
        "?",
        "。", 
        ".",
        "，",
        ",",
    )
    for token in replacements:
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned or query.strip()


def _wind_direction_text(degrees: float | int | None) -> str:
    if degrees is None:
        return "未知风向"
    directions = [
        "北风",
        "东北风",
        "东风",
        "东南风",
        "南风",
        "西南风",
        "西风",
        "西北风",
    ]
    index = int(((float(degrees) + 22.5) % 360) / 45)
    return directions[index]


class GetWeatherTool(BaseTool):
    name: str = "get_weather"
    description: str = (
        "Get the current weather for a city or place using Open-Meteo. "
        "Use this directly for weather questions instead of reading skill files."
    )
    args_schema: Type[BaseModel] = GetWeatherInput

    def _resolve_location(self, client: httpx.Client, query: str) -> dict[str, object]:
        location_query = _clean_location(query)
        for city, location in COMMON_LOCATIONS.items():
            if city in location_query or city in query:
                return location
        response = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={
                "name": location_query,
                "count": 1,
                "language": "zh",
                "format": "json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not results:
            raise ValueError(f"未找到地点：{location_query}")
        return results[0]

    def _fetch_open_meteo(self, client: httpx.Client, location: dict[str, object]) -> str:
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        city = str(location.get("name", "未知地点"))
        admin1 = str(location.get("admin1", "") or "")
        country = str(location.get("country", "") or "")
        response = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current_weather") or {}
        if not current:
            raise ValueError("天气服务未返回 current_weather 数据")

        temperature = current.get("temperature")
        weather_code = int(current.get("weathercode", -1))
        wind_speed = current.get("windspeed")
        wind_direction = _wind_direction_text(current.get("winddirection"))
        observed_at = str(current.get("time", "未知时间"))
        weather_text = WMO_DESCRIPTIONS.get(weather_code, f"未知天气代码 {weather_code}")
        location_label = city
        if admin1 and admin1 != city:
            location_label = f"{city}，{admin1}"
        if country and country not in location_label:
            location_label = f"{location_label}，{country}"

        return (
            f"{location_label} 当前天气：\n"
            f"- 温度：{temperature}°C\n"
            f"- 天气状况：{weather_text}\n"
            f"- 风速：{wind_speed} km/h，{wind_direction}\n"
            f"- 观测时间：{observed_at}\n"
            f"- 数据来源：Open-Meteo"
        )

    def _fetch_wttr_fallback(self, client: httpx.Client, query: str) -> str:
        location_query = _clean_location(query)
        response = client.get(
            f"https://wttr.in/{location_query}",
            params={"format": "j1"},
        )
        response.raise_for_status()
        payload = response.json()
        current = (payload.get("current_condition") or [{}])[0]
        if not current:
            raise ValueError("备用天气源未返回数据")
        temperature = current.get("temp_C")
        weather_text = ((current.get("lang_zh") or current.get("weatherDesc") or [{}])[0]).get("value", "未知")
        wind_speed = current.get("windspeedKmph")
        wind_direction = current.get("winddir16Point", "未知风向")
        observed_at = current.get("localObsDateTime", "未知时间")
        return (
            f"{location_query} 当前天气：\n"
            f"- 温度：{temperature}°C\n"
            f"- 天气状况：{weather_text}\n"
            f"- 风速：{wind_speed} km/h，{wind_direction}\n"
            f"- 观测时间：{observed_at}\n"
            f"- 数据来源：wttr.in"
        )

    def _run(
        self,
        query: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            with httpx.Client(follow_redirects=True, timeout=15) as client:
                location = self._resolve_location(client, query)
                return self._fetch_open_meteo(client, location)
        except Exception as primary_exc:
            try:
                with httpx.Client(follow_redirects=True, timeout=15) as client:
                    fallback = self._fetch_wttr_fallback(client, query)
                return f"{fallback}\n- 备注：Open-Meteo 失败，已切换备用天气源。"
            except Exception as fallback_exc:
                return f"天气查询失败：{primary_exc}; 备用源也失败：{fallback_exc}"

    async def _arun(
        self,
        query: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, None)
