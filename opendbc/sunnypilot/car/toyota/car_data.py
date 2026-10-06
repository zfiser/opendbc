"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from opendbc.can.parser import CANParser
from opendbc.sunnypilot.car.car_data import make_car_data_item


def build_car_data(cp: CANParser) -> list[structs.CarStateSP.CarDataItem]:
  """Extra Toyota data for the car data page. Add one item per signal found in the DBC."""
  items = []

  # UI_SETTING (0x611), unit follows the cluster units setting, same flag the cruise speed code uses
  odometer_seen = cp.ts_nanos["UI_SETTING"]["ODOMETER"] > 0
  is_metric = cp.vl["BODY_CONTROL_STATE_2"]["UNITS"] in (1, 2)
  odometer = cp.vl["UI_SETTING"]["ODOMETER"] if odometer_seen else None
  items.append(make_car_data_item("odometer", "Odometer", odometer, "km" if is_metric else "mi"))

  # ENGINE_RPM (0x1C4), 0 is a valid value on a hybrid running on the electric motor, so go by the message being received
  rpm_seen = cp.ts_nanos["ENGINE_RPM"]["RPM"] > 0
  rpm = max(cp.vl["ENGINE_RPM"]["RPM"], 0.0) if rpm_seen else None
  items.append(make_car_data_item("rpm", "Engine RPM", rpm, "rpm"))

  return items
