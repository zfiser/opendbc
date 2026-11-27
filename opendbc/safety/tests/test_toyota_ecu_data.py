#!/usr/bin/env python3
"""fork: the ECU_DATA flag of the Toyota safety (read-only ECU data requests with stock longitudinal, see modes/toyota.h)."""
import unittest

from opendbc.car.toyota.values import ToyotaSafetyFlags
from opendbc.car.structs import CarParams
from opendbc.sunnypilot.car.toyota.values import ToyotaSafetyFlagsSP
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.common import make_msg
from opendbc.safety.tests.test_toyota import TOYOTA_COMMON_TX_MSGS, TestToyotaStockLongitudinalAngle

ECU_DATA_ADDRS = [0x700, 0x7D2, 0x747, 0x7C4, 0x750]

# the exact frames the reader sends (opendbc/sunnypilot/car/toyota/ecu_data.py)
READS = {
  0x700: ["221F5C"],
  0x7D2: ["221F05", "221040", "2210A5", "2210A6", "2210A8", "2210B2", "2210A7", "2215EE", "2215F7", "2215F8", "221F42",
          "22107E", "221002", "22106E"],
  0x747: ["221814"],
  0x7C4: ["2121"],
}
TYRE = ["2A02211600000000", "2A02213000000000", "2A30000000000000"]
FLOW_CONTROL = "3000000000000000"
TESTER_PRESENT_RADAR = "0F023E0000000000"


def frame(payload: str) -> bytes:
  b = bytes([len(payload) // 2]) + bytes.fromhex(payload)
  return b + bytes(8 - len(b))


def allowed_frames():
  out = [(addr, frame(r)) for addr, reads in READS.items() for r in reads]
  out += [(0x750, bytes.fromhex(t)) for t in TYRE]
  out += [(addr, bytes.fromhex(FLOW_CONTROL)) for addr in READS]
  return out


class TestToyotaEcuDataSafety(TestToyotaStockLongitudinalAngle):
  """The user's setup (stock longitudinal, LTA) with ECU_DATA: every standard Toyota test must still pass."""
  SAFETY_PARAM_SP = ToyotaSafetyFlagsSP.ECU_DATA
  TX_MSGS = TOYOTA_COMMON_TX_MSGS + [[a, 0] for a in ECU_DATA_ADDRS]

  def _send(self, addr: int, dat: bytes, bus: int = 0) -> bool:
    return self._tx(libsafety_py.make_CANPacket(addr, bus, dat))

  def test_allowed_frames(self):
    for addr, dat in allowed_frames():
      self.assertTrue(self._send(addr, dat), f"{addr:#x} {dat.hex()}")
    self.assertFalse(self._send(0x750, bytes.fromhex(TESTER_PRESENT_RADAR)))  # as without the flag: blocked in stock longitudinal

  def test_allowed_regardless_of_controls(self):
    for controls in (False, True):
      self.safety.set_controls_allowed(controls)
      for addr, dat in allowed_frames():
        self.assertTrue(self._send(addr, dat))

  def test_every_single_byte_change_is_blocked(self):
    allowed = set(allowed_frames())
    for addr, dat in allowed_frames():
      for i in range(8):
        for v in (0x00, 0x01, 0x10, 0x2E, 0x3E, 0xFF, dat[i] ^ 0x01):
          changed = dat[:i] + bytes([v]) + dat[i + 1:]
          if (addr, changed) in allowed:
            continue
          self.assertFalse(self._send(addr, changed), f"{addr:#x} {changed.hex()}")

  def test_dangerous_services_blocked(self):
    # write data (2E), routines (31), session (10), reset (11), clear codes (14), security (27), comm control (28),
    # tester present (3E), download (34), IO control (2F), and OBD clear (04)
    for addr in ECU_DATA_ADDRS:
      for svc in ("2E1F5C00", "3101FF00", "1003", "1101", "14FFFFFF", "2701", "280303", "3E00", "34004411", "2F100103", "04"):
        dat = frame(svc)
        if addr == 0x750:
          dat = bytes([0x2A]) + dat[:7]
        self.assertFalse(self._send(addr, dat), f"{addr:#x} {dat.hex()}")

  def test_other_bus_and_length_blocked(self):
    for addr, dat in allowed_frames():
      for bus in (1, 2):
        self.assertFalse(self._send(addr, dat, bus))
      self.assertFalse(self._send(addr, dat[:7]))

  def test_frame_only_on_its_own_ecu(self):
    for addr, dat in allowed_frames():
      for other in ECU_DATA_ADDRS:
        if other != addr and (other, dat) not in set(allowed_frames()):
          self.assertFalse(self._send(other, dat), f"{dat.hex()} on {other:#x}")

  def test_other_diagnostic_addresses_blocked(self):
    for addr in (0x7DF, 0x7E0, 0x7E2, 0x7A1, 0x7B0, 0x780, 0x701, 0x745):
      self.assertFalse(self._send(addr, frame("221F5C")))


class TestToyotaEcuDataFlagOff(TestToyotaStockLongitudinalAngle):
  """Without the flag the panda is as before: nothing on the ECU data addresses but the radar tester present."""

  def test_ecu_data_frames_blocked(self):
    for addr, dat in allowed_frames():
      self.assertFalse(self._tx(libsafety_py.make_CANPacket(addr, 0, dat)), f"{addr:#x} {dat.hex()}")


class TestToyotaEcuDataIgnoredWithOpenpilotLongitudinal(unittest.TestCase):
  """The flag has no effect with openpilot longitudinal (or SecOC): only the stock tester present on 0x750."""

  def test_ignored(self):
    safety = libsafety_py.libsafety
    safety.set_current_safety_param_sp(ToyotaSafetyFlagsSP.ECU_DATA)
    for param in (73 | ToyotaSafetyFlags.LTA, 73):
      safety.set_safety_hooks(CarParams.SafetyModel.toyota, param)
      safety.init_tests()
      for addr, dat in allowed_frames():
        self.assertFalse(safety.safety_tx_hook(libsafety_py.make_CANPacket(addr, 0, dat)), f"{addr:#x} {dat.hex()}")
      self.assertTrue(safety.safety_tx_hook(make_msg(0, 0x750, 8, bytes.fromhex(TESTER_PRESENT_RADAR))))
    safety.set_current_safety_param_sp(0)


if __name__ == "__main__":
  unittest.main()
