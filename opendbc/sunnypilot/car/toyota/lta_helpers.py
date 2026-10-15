"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Two helpers for Toyota cars with LTA (angle) steering.
"""

# --- after the driver lets go of the wheel ---------------------------------------------------------------------------
# The angle sent to the EPS may only change at a limited rate (ANGLE_LIMITS, also enforced by the panda). After a turn the
# driver unwinds the wheel faster than that, so for a few seconds the command still points into the curve and the EPS
# pulls the wheel back into it. While that lasts the LTA torque is wound down (TORQUE_WIND_DOWN 0, always allowed), until
# the command has caught up with the wheel. Only while the command is still on its way to the model's target in the same
# direction the wheel already went: once the command has reached the target, a remaining difference to the wheel is a real
# steering demand (the road still curves) and the torque comes back.
CATCH_UP_DEG = 8.0  # the command counts as caught up within this many degrees of the wheel
RECENT_OVERRIDE = 3.0  # s, only right after the driver steered
MAX_HOLD = 4.0  # s, never longer than this


class ReleaseHold:
  def __init__(self):
    self._since_pressed = float("inf")
    self._held = 0.0

  def update(self, lat_active: bool, steering_pressed: bool, command_deg: float, wheel_deg: float, target_deg: float, dt: float) -> bool:
    """True while the LTA torque has to stay wound down. Call at the rate of the LTA message."""
    if not lat_active:
      self._since_pressed, self._held = float("inf"), 0.0
      return False
    if steering_pressed:
      self._since_pressed, self._held = 0.0, 0.0
      return False  # while the driver steers the torque is handled by the driver torque check
    self._since_pressed += dt
    behind_wheel = abs(command_deg - wheel_deg) > CATCH_UP_DEG
    chasing_target = abs(target_deg - command_deg) > CATCH_UP_DEG and (target_deg - command_deg) * (wheel_deg - command_deg) > 0
    if behind_wheel and chasing_target and self._since_pressed <= RECENT_OVERRIDE and self._held < MAX_HOLD:
      self._held += dt
      return True
    self._since_pressed = float("inf")  # caught up (or gave up): back to normal until the next override
    return False


# --- short EPS fault reports ------------------------------------------------------------------------------------------
# LTA_STATE 3 and 17 are counted as permanent faults ("LKAS Fault: Restart the Car"). The EPS also reports them for a
# moment and recovers at once; seen on the RAV4 2023 for under 0.1 s while openpilot started steering. A short report is a
# temporary fault, only one that lasts is permanent.
PERMANENT_AFTER = 0.5  # s


class LtaFaultFilter:
  def __init__(self, permanent_after: float = PERMANENT_AFTER):
    self._permanent_after = permanent_after
    self._seen = 0.0

  def update(self, in_permanent_state: bool, dt: float) -> tuple[bool, bool]:
    """(temporary, permanent) for a permanent fault state reported by LTA_STATE this frame."""
    if not in_permanent_state:
      self._seen = 0.0
      return False, False
    self._seen += dt
    if self._seen >= self._permanent_after:
      return False, True
    return True, False
