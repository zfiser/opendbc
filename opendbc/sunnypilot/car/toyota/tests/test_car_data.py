"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from types import SimpleNamespace

from opendbc.sunnypilot.car.car_data import make_car_data_item
from opendbc.sunnypilot.car.toyota.car_data import build_car_data


def _cp(odometer: float, odometer_ts: int, units: int):
  return SimpleNamespace(
    vl={"UI_SETTING": {"ODOMETER": odometer}, "BODY_CONTROL_STATE_2": {"UNITS": units}},
    ts_nanos={"UI_SETTING": {"ODOMETER": odometer_ts}},
  )


class TestCarData:
  def test_make_item_valid(self):
    item = make_car_data_item("odometer", "Odometer", 12345.0, "km")
    assert item.valid and item.value == 12345.0 and item.unit == "km" and item.key == "odometer"

  def test_make_item_invalid(self):
    for bad in (None, float("nan"), float("inf")):
      item = make_car_data_item("x", "X", bad, "km")
      assert not item.valid and item.value == 0.0

  def test_odometer_metric(self):
    items = build_car_data(_cp(54321, odometer_ts=1, units=1))
    assert len(items) == 1
    assert items[0].key == "odometer" and items[0].valid and items[0].value == 54321 and items[0].unit == "km"

  def test_odometer_imperial(self):
    items = build_car_data(_cp(100, odometer_ts=1, units=3))
    assert items[0].unit == "mi"

  def test_odometer_not_received(self):
    # message never seen on the bus: must be reported invalid, not as 0
    items = build_car_data(_cp(0, odometer_ts=0, units=1))
    assert not items[0].valid
