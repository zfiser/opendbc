"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from opendbc.can.parser import CANParser
from opendbc.sunnypilot.car.car_data import make_car_data_item

KPA_TO_PSI = 0.14503774
TEMPERATURE_OFFSET = 40  # degrees C, the usual Toyota offset, a guess for this message


def tire_pressure(raw: float, is_metric: bool) -> tuple[float, str]:
  """kPa from the car, shown as kPa in metric and as psi otherwise."""
  return (raw, "kPa") if is_metric else (raw * KPA_TO_PSI, "psi")


def tire_temperature(raw: float, is_metric: bool) -> tuple[float, str]:
  celsius = raw - TEMPERATURE_OFFSET
  return (celsius, "C") if is_metric else (celsius * 9 / 5 + 32, "F")


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

  # Both tiles are guesses and are shown whatever the value is, even a not available marker, so they can be compared with the dash.
  # TPMS_PRESSURE (0x3A6): four little-endian values seen as 264, only the first one is used. It did not follow the real
  # pressure in the recordings of 2026-10-07 (constant while the tires warmed up).
  if cp.ts_nanos["TPMS_PRESSURE"]["PRESSURE_1"] > 0:
    value, unit = tire_pressure(cp.vl["TPMS_PRESSURE"]["PRESSURE_1"], is_metric)
    items.append(make_car_data_item("tire_pressure_guess", "Tire pressure?", value, unit))

  # TPMS_TEMPERATURE (0x3A7): first 16-bit big-endian value minus 40 degrees C, a pure guess (the recordings had 0x03FF)
  if cp.ts_nanos["TPMS_TEMPERATURE"]["TEMPERATURE_1"] > 0:
    value, unit = tire_temperature(cp.vl["TPMS_TEMPERATURE"]["TEMPERATURE_1"], is_metric)
    items.append(make_car_data_item("tire_temperature_guess", "Tire temp?", value, unit))

  return items
