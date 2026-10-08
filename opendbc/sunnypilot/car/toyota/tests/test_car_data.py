"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

from opendbc.sunnypilot.car.car_data import make_car_data_item
from opendbc.sunnypilot.car.toyota.car_data import build_car_data


def _cp(odometer: float, odometer_ts: int, units: int, rpm: float = 0.0, rpm_ts: int = 0,
        pressures=(0, 0, 0, 0), pressure_ts: int = 0, temps=(0, 0, 0, 0), temp_ts: int = 0,
        lead: float = 0.0, lead_ts: int = 0):
  return SimpleNamespace(
    vl={"UI_SETTING": {"ODOMETER": odometer}, "BODY_CONTROL_STATE_2": {"UNITS": units}, "DSU_CRUISE": {"LEAD_DISTANCE": lead}, "ENGINE_RPM": {"RPM": rpm},
        "TPMS_PRESSURE": {f"PRESSURE_{i + 1}": v for i, v in enumerate(pressures)},
        "TPMS_TEMPERATURE": {f"TEMPERATURE_{i + 1}": v for i, v in enumerate(temps)}},
    ts_nanos={"UI_SETTING": {"ODOMETER": odometer_ts}, "ENGINE_RPM": {"RPM": rpm_ts}, "DSU_CRUISE": {"LEAD_DISTANCE": lead_ts},
              "TPMS_PRESSURE": {"PRESSURE_1": pressure_ts}, "TPMS_TEMPERATURE": {"TEMPERATURE_1": temp_ts}},
  )


def _by_key(items):
  return {item.key: item for item in items}


class TestCarData:
  def test_make_item_valid(self):
    item = make_car_data_item("odometer", "Odometer", 12345.0, "km")
    assert item.valid and item.value == 12345.0 and item.unit == "km" and item.key == "odometer"

  def test_make_item_invalid(self):
    for bad in (None, float("nan"), float("inf")):
      item = make_car_data_item("x", "X", bad, "km")
      assert not item.valid and item.value == 0.0

  def test_odometer_metric(self):
    item = _by_key(build_car_data(_cp(54321, odometer_ts=1, units=1)))["odometer"]
    assert item.valid and item.value == 54321 and item.unit == "km"

  def test_odometer_imperial(self):
    assert _by_key(build_car_data(_cp(100, odometer_ts=1, units=3)))["odometer"].unit == "mi"

  def test_odometer_not_received(self):
    # message never seen on the bus: must be reported invalid, not as 0
    assert not _by_key(build_car_data(_cp(0, odometer_ts=0, units=1)))["odometer"].valid

  def test_lead_distance(self):
    item = _by_key(build_car_data(_cp(0, 0, 1, lead=23, lead_ts=1)))["lead_distance"]
    assert item.valid and item.value == 23 and item.unit == "m"

  def test_lead_distance_none_marker_is_invalid(self):
    for marker in (250, 252, 253, 255):
      assert not _by_key(build_car_data(_cp(0, 0, 1, lead=marker, lead_ts=1)))["lead_distance"].valid

  def test_lead_distance_not_received_is_absent(self):
    assert "lead_distance" not in _by_key(build_car_data(_cp(0, 0, 1)))

  def test_rpm(self):
    item = _by_key(build_car_data(_cp(0, 0, 1, rpm=1850.5, rpm_ts=1)))["rpm"]
    assert item.valid and item.value == 1850.5 and item.unit == "rpm"

  def test_rpm_zero_is_valid_when_received(self):
    # hybrid on the electric motor
    item = _by_key(build_car_data(_cp(0, 0, 1, rpm=0.0, rpm_ts=5)))["rpm"]
    assert item.valid and item.value == 0.0

  def test_rpm_negative_clamped(self):
    assert _by_key(build_car_data(_cp(0, 0, 1, rpm=-3.0, rpm_ts=1)))["rpm"].value == 0.0

  def test_rpm_not_received(self):
    assert not _by_key(build_car_data(_cp(0, 0, 1, rpm=500.0, rpm_ts=0)))["rpm"].valid

  def test_tire_pressure_guess_metric(self):
    item = _by_key(build_car_data(_cp(0, 0, 1, pressures=(264, 1, 2, 3), pressure_ts=1)))["tire_pressure_guess"]
    assert item.valid and item.value == 264 and item.unit == "kPa"

  def test_tire_pressure_guess_imperial(self):
    item = _by_key(build_car_data(_cp(0, 0, 3, pressures=(264, 0, 0, 0), pressure_ts=1)))["tire_pressure_guess"]
    assert item.unit == "psi" and abs(item.value - 38.3) < 0.05

  def test_tire_values_are_shown_even_if_they_look_like_markers(self):
    items = _by_key(build_car_data(_cp(0, 0, 1, pressures=(0x03FF, 0, 0, 0), pressure_ts=1, temps=(0x03FF, 0, 0, 0), temp_ts=1)))
    assert items["tire_pressure_guess"].value == 0x03FF
    assert items["tire_temperature_guess"].value == 0x03FF - 40

  def test_no_tire_tiles_when_the_messages_are_missing(self):
    items = _by_key(build_car_data(_cp(0, 0, 1, pressures=(264, 264, 264, 264), pressure_ts=0, temps=(65, 0, 0, 0), temp_ts=0)))
    assert not any(k.startswith("tire_") for k in items)

  def test_tire_temperature_guess(self):
    item = _by_key(build_car_data(_cp(0, 0, 1, temps=(65, 0, 0, 0), temp_ts=1)))["tire_temperature_guess"]
    assert item.value == 25 and item.unit == "C"

  def test_tire_temperature_guess_imperial(self):
    item = _by_key(build_car_data(_cp(0, 0, 3, temps=(65, 0, 0, 0), temp_ts=1)))["tire_temperature_guess"]
    assert item.unit == "F" and abs(item.value - 77) < 0.01
