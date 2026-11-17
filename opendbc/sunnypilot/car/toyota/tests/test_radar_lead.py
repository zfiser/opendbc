"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.car import structs
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.values import CAR
from opendbc.sunnypilot.car.toyota.car_data import RADAR_STALE_NS, build_radar_data, create_radar_parser

MS = 1_000_000


def lead_dist(metres: float) -> bytes:
  raw = round(metres * 20)  # 0.05 m steps, (byte1 & 0x0F) << 8 | byte2
  return bytes([0x5a, (raw >> 8) & 0x0F, raw & 0xFF, 0, 0, 0, 0, 0])


def lead_speed(mps: float) -> bytes:
  raw = round((mps + 128) * 256)  # 16 bits in bytes 3-4, /256 - 128
  return bytes([0xa5, 0, 0, (raw >> 8) & 0xFF, raw & 0xFF, 0, 0, 0])


def radar_frames(metres: float, mps: float, bus: int = 1):
  return [(0x237, lead_dist(metres), bus), (0x235, lead_speed(mps), bus)]


def by_key(items):
  return {i.key: i for i in items}


def rav4_2023_cp():
  return CarInterface.get_non_essential_params(CAR.TOYOTA_RAV4_TSS2_2023)


class TestRadarLead:
  def test_only_on_the_rav4_2023(self):
    assert create_radar_parser(rav4_2023_cp()) is not None
    assert create_radar_parser(CarInterface.get_non_essential_params(CAR.TOYOTA_RAV4_TSS2)) is None

  def test_decodes_distance_and_speed(self):
    rcp = create_radar_parser(rav4_2023_cp())
    assert build_radar_data(rcp) == []  # nothing until the first message
    rcp.update([(10 * MS, radar_frames(100.2, -4.33))])
    items = by_key(build_radar_data(rcp))
    assert items["radar_distance"].valid and abs(items["radar_distance"].value - 100.2) < 1e-6
    assert items["radar_rel_speed"].valid and abs(items["radar_rel_speed"].value + 4.33) < 0.004

  def test_other_bus_is_ignored(self):
    rcp = create_radar_parser(rav4_2023_cp())
    rcp.update([(10 * MS, radar_frames(50.0, 1.0, bus=0))])
    assert build_radar_data(rcp) == []

  def test_no_lead(self):
    rcp = create_radar_parser(rav4_2023_cp())
    rcp.update([(10 * MS, radar_frames(0.0, 0.0))])
    items = by_key(build_radar_data(rcp))
    assert not items["radar_distance"].valid and not items["radar_rel_speed"].valid

  def test_stale_when_the_radar_bus_goes_quiet(self):
    rcp = create_radar_parser(rav4_2023_cp())
    rcp.update([(10 * MS, radar_frames(60.0, 0.5))])
    rcp.update([(10 * MS + RADAR_STALE_NS // 2, [(0x100, bytes(8), 0)])])  # other traffic only
    assert by_key(build_radar_data(rcp))["radar_distance"].valid
    rcp.update([(10 * MS + RADAR_STALE_NS + MS, [(0x100, bytes(8), 0)])])
    assert build_radar_data(rcp) == []  # no radar data at all (not "no lead"): users fall back to the dashboard distance


class TestRadarLeadInTheCarInterface:
  def test_car_can_validity_is_not_touched(self):
    # the radar parser is not one of the car's parsers: with or without radar frames the car state flags come out the same
    CP = rav4_2023_cp()
    results = []
    for with_radar in (False, True):
      CI = CarInterface(CP, structs.CarParamsSP())
      assert CI.CS.radar_cp is not None and CI.CS.radar_cp not in CI.can_parsers.values()
      out = None
      for i in range(50):
        frames = radar_frames(42.0, -1.5) if with_radar else []
        out = CI.update([(i * 10 * MS, frames)])
      results.append(out)
    (cs_without, sp_without), (cs_with, sp_with) = results
    assert cs_without.canValid == cs_with.canValid and cs_without.canTimeout == cs_with.canTimeout
    assert "radar_distance" not in by_key(sp_without.carData)
    assert abs(by_key(sp_with.carData)["radar_distance"].value - 42.0) < 1e-6

  def test_a_broken_radar_parser_does_not_break_the_car_state(self):
    CI = CarInterface(rav4_2023_cp(), structs.CarParamsSP())

    class Broken:
      ts_nanos = vl = None

      def update(self, _):
        raise RuntimeError("boom")

    CI.CS.radar_cp = Broken()
    CI.CS.optional_can_parsers = [CI.CS.radar_cp]
    cs, sp = CI.update([(0, [])])
    assert cs is not None and "radar_distance" not in by_key(sp.carData)
