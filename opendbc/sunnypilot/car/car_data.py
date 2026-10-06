"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs


def make_car_data_item(key: str, label: str, value: float | None, unit: str = "") -> structs.CarStateSP.CarDataItem:
  """One tile on the car data page. A missing or non-finite value is reported as invalid and shown as '--' by the UI."""
  valid = value is not None and value == value and abs(value) != float("inf")
  return structs.CarStateSP.CarDataItem(key=key, label=label, value=float(value) if valid else 0.0, unit=unit, valid=bool(valid))
