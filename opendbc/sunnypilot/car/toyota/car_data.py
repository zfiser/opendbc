"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from opendbc.can.parser import CANParser
from opendbc.sunnypilot.car.car_data import make_car_data_item

LEAD_DISTANCE_NONE = 250  # DSU_CRUISE.LEAD_DISTANCE is 252 when the radar has no lead (253 was seen too)

RADAR_DBC = "toyota_rav4_2023_radar_fork"  # the radar lead object on the radar bus, see the comments in the DBC
RADAR_BUS = 1
RADAR_CARS = ("TOYOTA_RAV4_TSS2_2023",)  # decoded on this car only; other RADAR_ACC Toyotas may send something else
RADAR_STALE_NS = 300_000_000  # 0.3 s without a radar message (they come at 50 Hz) = no radar data


def create_radar_parser(CP) -> CANParser | None:
  """Parser for the radar lead on the radar bus, None on other cars. It is not one of the car's parsers (get_can_parsers): it
  never counts for canValid or canTimeout, a silent radar bus only makes the radar items invalid."""
  if CP.carFingerprint not in RADAR_CARS:
    return None
  return CANParser(RADAR_DBC, [("RADAR_LEAD_SPEED", float('nan')), ("RADAR_LEAD_DIST", float('nan'))], RADAR_BUS)


def build_radar_data(rcp: CANParser) -> list[structs.CarStateSP.CarDataItem]:
  """radar_distance (m, 0.05 m steps) and radar_rel_speed (m/s, positive = the gap opens) of the radar lead at 50 Hz, the raw
  data behind DSU_CRUISE.LEAD_DISTANCE. Invalid items without a lead; no items at all before the first message or when the
  messages stopped (no radar data, so a user can fall back to lead_distance)."""
  d_ts = rcp.ts_nanos["RADAR_LEAD_DIST"]["LEAD_DIST"]
  now = getattr(rcp, "_last_update_nanos", d_ts)  # time of the newest CAN data the parser saw, any bus
  if d_ts <= 0 or now - d_ts > RADAR_STALE_NS:
    return []
  v_ts = rcp.ts_nanos["RADAR_LEAD_SPEED"]["REL_SPEED"]
  distance = rcp.vl["RADAR_LEAD_DIST"]["LEAD_DIST"]
  lead = distance > 0
  speed_ok = lead and v_ts > 0 and now - v_ts <= RADAR_STALE_NS
  return [
    make_car_data_item("radar_distance", "Radar distance", distance if lead else None, "m"),
    make_car_data_item("radar_rel_speed", "Radar rel speed", rcp.vl["RADAR_LEAD_SPEED"]["REL_SPEED"] if speed_ok else None, "m/s"),
  ]


def build_car_data(cp: CANParser) -> list[structs.CarStateSP.CarDataItem]:
  """Extra Toyota data for the car data page. Add one item per signal found in the DBC."""
  items = []

  # UI_SETTING (0x611), unit follows the cluster units setting, same flag the cruise speed code uses
  # The unit comes from BODY_CONTROL_STATE_2 (UI_SETTING.UNITS reads 0 on the RAV4 2023). Until that message has arrived the
  # unit is not known: the odometer is reported invalid, a wrong unit would make the daily distance start over.
  odometer_seen = cp.ts_nanos["UI_SETTING"]["ODOMETER"] > 0 and cp.ts_nanos["BODY_CONTROL_STATE_2"]["UNITS"] > 0
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
