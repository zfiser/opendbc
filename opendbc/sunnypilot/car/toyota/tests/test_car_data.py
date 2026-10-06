"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

from opendbc.sunnypilot.car.car_data import make_car_data_item
from opendbc.sunnypilot.car.toyota.car_data import build_car_data


def _cp(odometer: float, odometer_ts: int, units: int, rpm: float = 0.0, rpm_ts: int = 0):
  return SimpleNamespace(
    vl={"UI_SETTING": {"ODOMETER": odometer}, "BODY_CONTROL_STATE_2": {"UNITS": units}, "ENGINE_RPM": {"RPM": rpm}},
    ts_nanos={"UI_SETTING": {"ODOMETER": odometer_ts}, "ENGINE_RPM": {"RPM": rpm_ts}},
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
