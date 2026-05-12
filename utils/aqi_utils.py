def calculate_aqi(pm25, pm10):
    """
    Calculates the US EPA Air Quality Index (AQI) for PM2.5 and PM10.
    Returns the higher of the two indices.
    """

    def _linear(aqi_high, aqi_low, conc_high, conc_low, conc):
        return round(
            ((aqi_high - aqi_low) / (conc_high - conc_low)) * (conc - conc_low)
            + aqi_low
        )

    def aqi_pm25(c):
        if c <= 12.0:
            return _linear(50, 0, 12.0, 0, c)
        if c <= 35.4:
            return _linear(100, 51, 35.4, 12.1, c)
        if c <= 55.4:
            return _linear(150, 101, 55.4, 35.5, c)
        if c <= 150.4:
            return _linear(200, 151, 150.4, 55.5, c)
        if c <= 250.4:
            return _linear(300, 201, 250.4, 150.5, c)
        if c <= 350.4:
            return _linear(400, 301, 350.4, 250.5, c)
        if c <= 500.4:
            return _linear(500, 401, 500.4, 350.5, c)
        return 500

    def aqi_pm10(c):
        if c <= 54:
            return _linear(50, 0, 54, 0, c)
        if c <= 154:
            return _linear(100, 51, 154, 55, c)
        if c <= 254:
            return _linear(150, 101, 254, 155, c)
        if c <= 354:
            return _linear(200, 151, 354, 255, c)
        if c <= 424:
            return _linear(300, 201, 424, 355, c)
        if c <= 504:
            return _linear(400, 301, 504, 425, c)
        if c <= 604:
            return _linear(500, 401, 604, 505, c)
        return 500

    aqi25 = aqi_pm25(pm25)
    aqi10 = aqi_pm10(pm10)

    return max(aqi25, aqi10)


def get_aqi_category(aqi):
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"
