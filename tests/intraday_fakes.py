"""Invented Garmin answers for the intraday tests (no real health data)."""

from datetime import UTC, datetime


def ms(*args, tz=UTC):
    """Epoch milliseconds of a date/time."""
    return int(datetime(*args, tzinfo=tz).timestamp() * 1000)


def hr_payload(rows, descriptors=True):
    """``dailyHeartRate`` answer; rows = [(epoch ms, bpm)]."""
    payload = {"heartRateValues": [list(r) for r in rows]}
    if descriptors:
        payload["heartRateValueDescriptors"] = [
            {"key": "timestamp", "index": 0}, {"key": "heartrate", "index": 1}]
    return payload


def bb_payload(rows):
    """Body Battery report list; rows = [(epoch ms, level)] (column 2 of Garmin's 4)."""
    return [{
        "bodyBatteryValuesArray": [[ts, "MEASURED", level, 1.0] for ts, level in rows],
        "bodyBatteryValueDescriptorDTOList": [
            {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
            {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryStatus"},
            {"bodyBatteryValueDescriptorIndex": 2, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
            {"bodyBatteryValueDescriptorIndex": 3, "bodyBatteryValueDescriptorKey": "bodyBatteryVersion"},
        ],
    }]


def spo2_payload(rows):
    return {"averageSpO2": 95, "spO2HourlyAverages": [list(r) for r in rows]}
