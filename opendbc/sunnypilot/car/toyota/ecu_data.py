"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

fork: values read from the car's ECUs once a minute (oil, coolant, inverters, 12 V battery, hybrid battery, cabin,
tyres) for the car data page, carData items "diag_*". Read-only requests (UDS 0x22 / Toyota 0x21), one every
SPACING seconds, so the whole list takes about a minute; while the UI shows the car data page's tiles (it touches
FOCUS_PATH, in RAM) the two values of those tiles (12 V current, transaxle oil) are also read once a second;
the panda allows exactly these frames and their ISO-TP flow control when the ECU_DATA safety flag is set (opendbc/safety/modes/toyota.h). The identifiers come from OBDb and answered on the RAV4
2023 hybrid on 24 Nov 2026 (analysis 2026-11-23_diag).

Nothing here may disturb the car: every entry point catches its own errors, a failing ECU only leaves its values out.
"""
import os
import time
from dataclasses import dataclass

from opendbc.car import structs
from opendbc.car.can_definitions import CanData
from opendbc.sunnypilot.car.car_data import make_car_data_item

ECU_DATA_CARS = ("TOYOTA_RAV4_TSS2_2023",)
BUS = 0
SPACING = 3.0  # s between two requests: 19 reads, about once a minute each
START_DELAY = 15.0  # s after the car process started (fingerprinting and engagement first)
TIMEOUT = 1.0  # s for a reply (the tyre ECU takes about 0.14 s per frame)
STALE = 180.0  # s, an older value is reported invalid
FOCUS_PATH = "/dev/shm/car_data_focus"  # touched by the UI about once a second while the tiles are on screen
FOCUS_FRESH = 3.0  # s, an older touch means the page is closed (or the UI is gone)
FOCUS_CHECK = 1.0  # s between two looks at the file
FAST_EVERY = 1.0  # s, each fast read while the page is open
FAST_REQS = (bytes.fromhex("2215F7"), bytes.fromhex("221040"))  # 12 V current, transaxle oil (the hybrid ECU)
TYRE_SUB = 0x2A  # the tyre pressure ECU behind the 0x750 gateway


@dataclass(frozen=True)
class Sig:
  key: str
  bit: int
  length: int
  mul: float = 1.0
  div: float = 1.0
  add: float = 0.0
  label: str = ""
  unit: str = ""
  zero_is_empty: bool = False  # raw 0 = no data (a tyre slot without a sensor reading), not a value


@dataclass(frozen=True)
class EcuRead:
  tx: int
  rx: int
  sub: int | None
  req: bytes  # service + identifier
  sigs: tuple[Sig, ...]


def _t(key, label, bit=0):
  return Sig(key, bit, 8, add=-40.0, label=label, unit="C")


READS: tuple[EcuRead, ...] = (
  EcuRead(0x700, 0x708, None, bytes.fromhex("221F5C"), (_t("diag_oil_temp", "Oil"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("221F05"), (_t("diag_coolant", "Coolant"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("221040"), (_t("diag_transaxle_oil", "Transaxle oil", 16),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2210A5"), (_t("diag_mg_inverter", "Motor inverter"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2210A6"), (_t("diag_rear_inverter_coolant", "Rear inverter coolant"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2210A8"), (_t("diag_gen_inverter", "Generator inverter"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2210B2"), (_t("diag_inverter_coolant", "Inverter coolant"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2210A7"), (_t("diag_boost_upper", "Boost upper"), _t("diag_boost_lower", "Boost lower", 8))),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2215EE"), (Sig("diag_12v_v", 0, 8, 0.31448, 1, 0.0125, "12V", "V"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2215F7"), (Sig("diag_12v_a", 0, 16, 38.147, 10000, -125, "12V current", "A"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("2215F8"), (Sig("diag_12v_temp", 0, 16, 1, 10, -40, "12V temp", "C"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("221F42"), (Sig("diag_12v_smooth", 0, 16, 1, 1000, 0, "12V smoothed", "V"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("22107E"), (Sig("diag_12v_relay", 0, 8, 61, 50000, 11.25, "12V before relay", "V"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("221002"), (Sig("diag_aux_v", 0, 16, 61, 50000, 0, "Aux", "V"),)),
  EcuRead(0x7D2, 0x7DA, None, bytes.fromhex("22106E"), (Sig("diag_ac_power", 0, 8, 1, 20, 0, "A/C power", "kW"),)),
  EcuRead(0x747, 0x74F, None, bytes.fromhex("221814"),
          tuple(Sig(f"diag_hv_temp{i + 1}", 16 * i, 16, 19531, 5e6, -50, f"HV battery {i + 1}", "C") for i in range(6))),
  EcuRead(0x7C4, 0x7CC, None, bytes.fromhex("2121"), (Sig("diag_cabin", 0, 8, 63.75, 255, -6.5, "Cabin", "C"),)),
  EcuRead(0x750, 0x758, TYRE_SUB, bytes.fromhex("2116"),
          tuple(Sig(f"diag_tire_t_{w}", 8 * i, 8, add=-40.0, label=f"Tyre {w}", unit="C", zero_is_empty=True)
                for i, w in enumerate(("fl", "fr", "rl", "rr")))),
  EcuRead(0x750, 0x758, TYRE_SUB, bytes.fromhex("2130"),
          tuple(Sig(f"diag_tire_p_{w}", 8 * i, 8, 100, 58, -50, f"Tyre {w}", "kPa", zero_is_empty=True)
                for i, w in enumerate(("fl", "fr", "rl", "rr")))),
)


def request_frame(r: EcuRead) -> bytes:
  """The 8-byte single frame of a request, zero padded: what the panda allows (TOYOTA_ECU_DATA_FRAMES)."""
  body = bytes([len(r.req)]) + r.req
  if r.sub is not None:
    body = bytes([r.sub]) + body
  return body + bytes(8 - len(body))


def flow_control_frame(r: EcuRead) -> bytes:
  body = bytes([0x30, 0x00, 0x00])
  if r.sub is not None:
    body = bytes([r.sub]) + body
  return body + bytes(8 - len(body))


def decode(r: EcuRead, payload: bytes) -> dict[str, float]:
  """Values of a positive reply (service + 0x40, the identifier echoed, then the data). Empty when it is not one."""
  head = len(r.req)
  if len(payload) <= head or payload[0] != r.req[0] + 0x40 or payload[1:head] != r.req[1:]:
    return {}
  data = payload[head:]
  out = {}
  for s in r.sigs:
    if s.bit + s.length > len(data) * 8:
      continue
    raw = (int.from_bytes(data, "big") >> (len(data) * 8 - s.bit - s.length)) & ((1 << s.length) - 1)
    if raw == 0 and s.zero_is_empty:
      continue  # the last good value stays until it is stale
    out[s.key] = raw * s.mul / s.div + s.add
  return out


FAST_READS = tuple(r for r in READS if r.req in FAST_REQS)


def page_open(path: str = FOCUS_PATH) -> bool:
  """The UI touched the focus file within FOCUS_FRESH seconds (both clocks are the device's wall clock)."""
  try:
    return time.time() - os.stat(path).st_mtime < FOCUS_FRESH
  except OSError:
    return False


class EcuDataReader:
  def __init__(self, now=time.monotonic, focus=page_open):
    self._now = now
    self._focus = focus
    self._focused = False
    self._focus_checked = -FOCUS_CHECK
    self._fast_last = dict.fromkeys(FAST_READS, -FAST_EVERY)
    self._start = now()
    self._next = self._start + START_DELAY
    self._index = 0
    self._pending: EcuRead | None = None
    self._sent_at = 0.0
    self._buf = b""
    self._need = 0
    self._outbox: list[CanData] = []
    self.values: dict[str, tuple[float, float]] = {}  # key -> (value, time)

  # called by the car controller (100 Hz): the frames to send now
  def frames_to_send(self) -> list[CanData]:
    try:
      now = self._now()
      if self._pending is not None and now - self._sent_at > TIMEOUT:
        self._pending = None  # no (complete) reply: skip it, next round again
      if self._pending is None and now >= self._start + START_DELAY:
        r = self._fast_due(now)
        if r is None and now >= self._next:
          r = READS[self._index]
          self._index = (self._index + 1) % len(READS)
          self._next = now + SPACING
        if r is not None:
          self._pending, self._sent_at, self._buf, self._need = r, now, b"", 0
          self._outbox.append(CanData(r.tx, request_frame(r), BUS))
      out, self._outbox = self._outbox, []
      return out
    except Exception:
      self._pending, self._outbox = None, []
      return []

  def _fast_due(self, now: float) -> EcuRead | None:
    """A fast read that is due while the page is open, else None. The file is looked at once per FOCUS_CHECK."""
    if now - self._focus_checked >= FOCUS_CHECK:
      self._focus_checked = now
      self._focused = bool(self._focus())
    if not self._focused:
      return None
    for r in FAST_READS:
      if now - self._fast_last[r] >= FAST_EVERY:
        self._fast_last[r] = now
        return r
    return None

  # called with the raw CAN of every car interface update
  def on_can(self, can_packets) -> None:
    if self._pending is None:
      return
    try:
      r = self._pending
      for _, frames in can_packets:
        for address, dat, src in frames:
          if address == r.rx and src == BUS:
            self._on_frame(r, bytes(dat))
            if self._pending is None:
              return
    except Exception:
      self._pending = None

  def _on_frame(self, r: EcuRead, dat: bytes) -> None:
    if r.sub is not None:
      if not dat or dat[0] != r.sub:
        return
      dat = dat[1:]
    if not dat:
      return
    kind = dat[0] >> 4
    if kind == 0:  # single frame
      n = dat[0] & 0x0F
      payload = dat[1:1 + n]
      if len(payload) >= 3 and payload[0] == 0x7F and payload[2] == 0x78:
        self._sent_at = self._now()  # "response pending": the ECU answers later
        return
      self._finish(r, payload)
    elif kind == 1:  # first frame of a longer reply: ask for the rest
      self._need = ((dat[0] & 0x0F) << 8) | dat[1]
      self._buf = dat[2:]
      self._outbox.append(CanData(r.tx, flow_control_frame(r), BUS))
    elif kind == 2 and self._need:  # consecutive frame
      self._buf += dat[1:]
      if len(self._buf) >= self._need:
        self._finish(r, self._buf[:self._need])

  def _finish(self, r: EcuRead, payload: bytes) -> None:
    now = self._now()
    for key, value in decode(r, payload).items():
      self.values[key] = (value, now)
    self._pending = None

  def items(self) -> list[structs.CarStateSP.CarDataItem]:
    """carData items of the values read so far (invalid once older than STALE)."""
    now = self._now()
    out = []
    for r in READS:
      for s in r.sigs:
        if s.key in self.values:
          value, t = self.values[s.key]
          out.append(make_car_data_item(s.key, s.label, value if now - t <= STALE else None, s.unit))
    return out
