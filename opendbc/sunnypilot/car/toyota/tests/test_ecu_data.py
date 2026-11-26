"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pytest

from opendbc.car import structs
from opendbc.car.structs import CarParams
from opendbc.car.toyota.interface import CarInterface
from opendbc.car.toyota.values import CAR, ToyotaSafetyFlags
from opendbc.sunnypilot.car.interfaces import setup_interfaces
from opendbc.sunnypilot.car.toyota import ecu_data as ed
from opendbc.sunnypilot.car.toyota.values import ToyotaSafetyFlagsSP

# replies of the RAV4 2023 hybrid on 24 Nov 2026 (analysis 2026-11-23_diag, probe 1 and 2, tyres from tpms_raw.py)
REPLIES = {
  "221F5C": "621f5c39", "22106C": "62106c0c34", "221F05": "621f0539", "221040": "621040cfc039", "2210A5": "6210a538393a",
  "2210A6": "6210a6353636", "2210A8": "6210a8373738", "2210B2": "6210b23c", "2210A7": "6210a739393a3a", "2215EE": "6215ee2e20",
  "2215F7": "6215f78603", "2215F8": "6215f80207", "221F42": "621f423741", "22107E": "62107e24e0", "221002": "6210022e08",
  "22106E": "62106e00", "221814": "62181441b541d74159414741eb419c", "2121": "61215e", "2149": "61490000", "214A": "614a0000",
  "2116": "61163535363500", "2130": "6130b0aeafb000",
}
EXPECTED = {  # what the dash / the probe showed that day
  "diag_oil_temp": 17, "diag_12v_km": 3124, "diag_coolant": 17, "diag_transaxle_oil": 17, "diag_12v_v": 14.48, "diag_12v_a": 5.87,
  "diag_12v_temp": 11.9, "diag_12v_smooth": 14.14, "diag_hv_temp1": 15.71, "diag_cabin": 17.0, "diag_compressor": 0,
  "diag_tire_t_fl": 13, "diag_tire_t_rl": 14, "diag_tire_p_fl": 253.4, "diag_tire_p_fr": 250.0,
}


class Clock:
  def __init__(self):
    self.t = 0.0

  def __call__(self):
    return self.t


def reader():
  clock = Clock()
  return ed.EcuDataReader(now=clock), clock


def reply_frames(r: ed.EcuRead, payload: bytes) -> list[bytes]:
  """The ECU's ISO-TP frames for a payload (single frame, or first + consecutive frames), with the sub-address."""
  pre = bytes([r.sub]) if r.sub is not None else b""
  room = 7 - len(pre)
  if len(payload) <= room:
    return [pre + bytes([len(payload)]) + payload]
  frames = [pre + bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:room - 1]]
  rest, n = payload[room - 1:], 1
  while rest:
    frames.append(pre + bytes([0x20 | (n & 0xF)]) + rest[:room])
    rest, n = rest[room:], n + 1
  return frames


def run_one_round(rd, clock):
  """Every read once: send, answer like the car did, step the clock."""
  sent = []
  clock.t = ed.START_DELAY
  for _ in ed.READS:
    out = rd.frames_to_send()
    assert len(out) == 1
    sent += out
    r = next(x for x in ed.READS if x.tx == out[0].address and ed.request_frame(x) == out[0].dat)
    frames = reply_frames(r, bytes.fromhex(REPLIES[r.req.hex().upper()]))
    rd.on_can([(0, [(r.rx, frames[0], 0)])])
    fc = rd.frames_to_send()
    if len(frames) > 1:
      assert fc == [ed.CanData(r.tx, ed.flow_control_frame(r), 0)]
      sent += fc
      rd.on_can([(0, [(r.rx, f, 0) for f in frames[1:]])])
    else:
      assert fc == []
    clock.t += ed.SPACING
  return sent


class TestEcuData:
  def test_decodes_the_recorded_replies(self):
    rd, clock = reader()
    run_one_round(rd, clock)
    for key, want in EXPECTED.items():
      assert rd.values[key][0] == pytest.approx(want, abs=0.06), key

  def test_empty_tyre_slots_are_no_values(self):
    # 24 Nov, parked: front left / right temperature slots were 0 (decoded as -40 C before), a pressure reply can be all 0
    temps = next(r for r in ed.READS if r.req.hex() == "2116")
    pressures = next(r for r in ed.READS if r.req.hex() == "2130")
    assert ed.decode(temps, bytes.fromhex("61160000353500")) == {"diag_tire_t_rl": 13.0, "diag_tire_t_rr": 13.0}
    assert ed.decode(pressures, bytes.fromhex("61300000000000")) == {}
    oil = ed.READS[0]
    assert ed.decode(oil, bytes.fromhex("621f5c00")) == {"diag_oil_temp": -40.0}  # elsewhere 0 is a real reading

  def test_spacing_and_start_delay(self):
    rd, clock = reader()
    assert rd.frames_to_send() == []
    clock.t = ed.START_DELAY - 0.01
    assert rd.frames_to_send() == []
    clock.t = ed.START_DELAY
    assert len(rd.frames_to_send()) == 1
    clock.t += ed.TIMEOUT + 0.1  # no answer: given up, but the next one only after SPACING
    assert rd.frames_to_send() == []
    clock.t = ed.START_DELAY + ed.SPACING
    assert len(rd.frames_to_send()) == 1
    assert ed.SPACING * len(ed.READS) <= 65  # about once a minute

  def test_every_sent_frame_passes_the_panda(self):
    from opendbc.safety.tests.libsafety import libsafety_py
    safety = libsafety_py.libsafety
    safety.set_current_safety_param_sp(ToyotaSafetyFlagsSP.ECU_DATA)
    safety.set_safety_hooks(CarParams.SafetyModel.toyota, 73 | ToyotaSafetyFlags.STOCK_LONGITUDINAL | ToyotaSafetyFlags.LTA)
    safety.init_tests()
    rd, clock = reader()
    sent = run_one_round(rd, clock)
    assert len(sent) > len(ed.READS)  # requests plus flow control
    for msg in sent:
      assert safety.safety_tx_hook(libsafety_py.make_CANPacket(msg.address, msg.src, msg.dat)), f"{msg.address:#x} {msg.dat.hex()}"
    safety.set_current_safety_param_sp(0)

  def test_stale_values_become_invalid(self):
    rd, clock = reader()
    run_one_round(rd, clock)
    assert all(i.valid for i in rd.items())
    clock.t += ed.STALE + 1
    assert not any(i.valid for i in rd.items())

  def test_negative_reply_and_garbage_are_harmless(self):
    rd, clock = reader()
    clock.t = ed.START_DELAY
    r = ed.READS[0]
    rd.frames_to_send()
    rd.on_can([(0, [(r.rx, bytes.fromhex("037f2231"), 0)])])  # request out of range
    rd.on_can([(0, [(r.rx, b"\xff" * 8, 0), (r.rx, b"", 0), (0x123, b"\x00", 0)])])
    rd.on_can("not a can list")
    assert rd.values == {}
    assert rd.frames_to_send() == []

  def test_reply_from_the_wrong_tyre_sub_address_ignored(self):
    rd, clock = reader()
    tyres = next(i for i, r in enumerate(ed.READS) if r.sub is not None)
    clock.t = ed.START_DELAY
    for _ in range(tyres + 1):
      rd._pending = None
      rd._next = 0.0
      out = rd.frames_to_send()
    r = ed.READS[tyres]
    assert out[0].address == 0x750
    rd.on_can([(0, [(0x758, bytes([0x0F, 0x10, 0x07, 0x61, 0x16, 0x35, 0x35, 0x36]), 0)])])  # the radar's sub-address
    assert rd.frames_to_send() == [] and rd._pending is r


class TestEcuDataSetup:
  def _setup(self, car, enabled, stock_long=True):
    CP = CarInterface.get_non_essential_params(car)
    CP.openpilotLongitudinalControl = not stock_long
    CP_SP = structs.CarParamsSP()
    setup_interfaces(CarInterface, CP, CP_SP, [{"ToyotaEcuData": "1" if enabled else "0"}])
    return CP, CP_SP

  def test_flag_only_when_enabled_on_the_rav4_2023_with_stock_longitudinal(self):
    assert self._setup(CAR.TOYOTA_RAV4_TSS2_2023, True)[1].safetyParam & ToyotaSafetyFlagsSP.ECU_DATA
    assert not self._setup(CAR.TOYOTA_RAV4_TSS2_2023, False)[1].safetyParam & ToyotaSafetyFlagsSP.ECU_DATA
    assert not self._setup(CAR.TOYOTA_RAV4_TSS2_2023, True, stock_long=False)[1].safetyParam & ToyotaSafetyFlagsSP.ECU_DATA
    assert not self._setup(CAR.TOYOTA_RAV4_TSS2, True)[1].safetyParam & ToyotaSafetyFlagsSP.ECU_DATA

  def test_reader_only_with_the_flag(self):
    CP = CarInterface.get_non_essential_params(CAR.TOYOTA_RAV4_TSS2_2023)
    assert CarInterface(CP, structs.CarParamsSP()).CS.ecu_data is None
    CP_SP = structs.CarParamsSP()
    CP_SP.safetyParam = ToyotaSafetyFlagsSP.ECU_DATA
    CI = CarInterface(CP, CP_SP)
    assert CI.CS.ecu_data is not None
    cs, sp = CI.update([(0, [])])  # a car state update with the reader works
    assert cs is not None
