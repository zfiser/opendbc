"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from opendbc.sunnypilot.car.toyota.lta_helpers import ReleaseHold, LtaFaultFilter, MAX_HOLD, PERMANENT_AFTER

DT = 0.02  # the LTA message rate


class TestReleaseHold:
  def test_the_pull_after_the_turn_on_2026_10_13(self):
    # route 00000029, 52.70 min: right turn, the driver lets go, the sent angle lags the wheel by up to 30 deg
    #          (command sent, wheel, target)   values every 0.25 s from the log
    trace = [(-50, -33, -22), (-46, -19, -13), (-42, -10, -8), (-38, -3, -5), (-33, -4, -3), (-29, -6, -3), (-25, -10, -4),
             (-21, -10, -4), (-17, -9, -3), (-12, -7, -1), (-8, -7, 0), (-4, -7, -2)]
    h = ReleaseHold()
    h.update(True, True, -67, -63, -69, DT)  # still steering
    holds = []
    for cmd, wheel, target in trace:
      for _ in range(12):  # 0.25 s at 50 Hz
        holds.append(h.update(True, False, cmd, wheel, target, DT))
    per_step = [any(holds[i * 12:(i + 1) * 12]) for i in range(len(trace))]
    assert all(per_step[:8])  # wound down for the first 2 s, while the command points 10-30 deg into the old curve
    assert not per_step[-1]  # caught up: back to normal

  def test_no_hold_when_the_command_already_follows_the_wheel(self):
    h = ReleaseHold()
    h.update(True, True, -20, -20, -20, DT)
    assert not h.update(True, False, -18, -15, -14, DT)

  def test_no_hold_when_the_road_still_curves(self):
    # the driver straightened the wheel, but the model still wants the curve and the command is already at the target
    h = ReleaseHold()
    h.update(True, True, -40, -5, -40, DT)
    assert not h.update(True, False, -40, 0, -38, DT)

  def test_only_right_after_an_override(self):
    h = ReleaseHold()
    assert not h.update(True, False, -50, -10, -10, DT)  # no driver steering before: normal lag, nothing to do

  def test_never_longer_than_the_limit(self):
    h = ReleaseHold()
    h.update(True, True, -90, -90, -90, DT)
    steps = int((MAX_HOLD + 1.0) / DT)
    results = [h.update(True, False, -90, 0, 0, DT) for _ in range(steps)]
    assert results[0] and not results[-1]
    assert sum(results) * DT <= 3.0 + DT  # bounded by the 3 s window after the release as well

  def test_off_when_not_steering(self):
    h = ReleaseHold()
    h.update(True, True, -50, -50, -50, DT)
    assert not h.update(False, False, -50, 0, 0, DT)

  def test_the_driver_steering_again_restarts_it(self):
    h = ReleaseHold()
    h.update(True, True, -50, -50, -50, DT)
    assert h.update(True, False, -50, -20, -10, DT)
    assert not h.update(True, True, -50, -20, -10, DT)  # pressing: the driver torque check handles it
    assert h.update(True, False, -48, -15, -10, DT)


class TestLtaFaultFilter:
  def test_the_blip_on_2026_10_15_is_temporary(self):
    # route 00000032, 1.187 min: LTA_STATE 3 for under 0.1 s, then normal again
    f = LtaFaultFilter()
    results = [f.update(True, 0.01) for _ in range(8)] + [f.update(False, 0.01)]
    assert all(temp and not perm for temp, perm in results[:8])
    assert results[-1] == (False, False)

  def test_a_lasting_fault_is_permanent(self):
    f = LtaFaultFilter()
    steps = int(PERMANENT_AFTER / 0.01) + 2
    results = [f.update(True, 0.01) for _ in range(steps)]
    assert results[0] == (True, False)
    assert results[-1] == (False, True)

  def test_no_fault_no_report(self):
    assert LtaFaultFilter().update(False, 0.01) == (False, False)
