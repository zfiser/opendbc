"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from opendbc.can.parser import CANParser
from opendbc.sunnypilot.car.car_data import make_car_data_item

LEAD_DISTANCE_NONE = 250  # DSU_CRUISE.LEAD_DISTANCE is 252 when the radar has no lead (253 was seen too)


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

  # ENGINE_TEMPERATURE (0x3B9) byte 5: engine coolant temperature in degrees C, a guess that fits every recording: 20-24 on a cold
  # start, rising only while the engine runs, 50-60 after a few minutes and up to about 88 on long drives. Not confirmed otherwise.
  if cp.ts_nanos["ENGINE_TEMPERATURE"]["ENGINE_TEMP"] > 0:
    celsius = cp.vl["ENGINE_TEMPERATURE"]["ENGINE_TEMP"]
    items.append(make_car_data_item("engine_temp", "Engine temp", celsius if is_metric else celsius * 9 / 5 + 32, "C" if is_metric else "F"))

  # DSU_CRUISE (0x365) byte 4 is the distance to the radar lead in whole metres on the RAV4 2023, matched against the vision
  # lead in the 2026-10 recordings (median difference 1.2 m). It is reported while stock ACC is off as well.
  if cp.ts_nanos["DSU_CRUISE"]["LEAD_DISTANCE"] > 0:
    distance = cp.vl["DSU_CRUISE"]["LEAD_DISTANCE"]
    items.append(make_car_data_item("lead_distance", "Lead distance", distance if distance < LEAD_DISTANCE_NONE else None, "m"))

  # BRAKE (0xA6) BRAKE_FORCE is "hybrid only: force applied by friction brakes". In the 2026-10 recordings it was above zero
  # whenever the pedal was pressed and almost never (0.2%) while slowing down without the pedal, which is regen.
  if cp.ts_nanos["BRAKE"]["BRAKE_FORCE"] > 0:
    items.append(make_car_data_item("friction_brake_force", "Friction brake", cp.vl["BRAKE"]["BRAKE_FORCE"], "N"))

  return items
