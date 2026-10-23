import pytest

from qa_agent.control.pid import PIDController, PIDGains


def _controller(kp=0.0, ki=0.0, kd=0.0, output_min=-100.0, output_max=100.0, initial_output=None):
    return PIDController(
        PIDGains(kp=kp, ki=ki, kd=kd),
        output_min=output_min,
        output_max=output_max,
        initial_output=initial_output,
        clock=lambda: 0.0,  # unused; every call below passes an explicit `now`
    )


def test_output_min_greater_than_max_raises():
    with pytest.raises(ValueError):
        PIDController(PIDGains(1, 0, 0), output_min=5.0, output_max=1.0)


def test_first_update_has_zero_dt_and_no_integral_or_derivative_contribution():
    pid = _controller(kp=2.0, ki=1.0, kd=1.0, initial_output=0.0)
    output = pid.update(setpoint=10.0, measured_value=4.0, now=0.0)
    # dt == 0 on the first call -> only the proportional term can fire.
    assert output == pytest.approx(2.0 * (10.0 - 4.0))


def test_proportional_only_response():
    pid = _controller(kp=3.0, initial_output=0.0)
    pid.update(setpoint=0.0, measured_value=0.0, now=0.0)
    output = pid.update(setpoint=10.0, measured_value=4.0, now=1.0)
    assert output == pytest.approx(3.0 * 6.0)


def test_integral_accumulates_over_time():
    pid = _controller(ki=1.0, initial_output=0.0)
    pid.update(setpoint=1.0, measured_value=0.0, now=0.0)  # error=1, dt=0, no accumulation yet
    out_1s = pid.update(setpoint=1.0, measured_value=0.0, now=1.0)  # integral += 1*1 = 1
    out_2s = pid.update(setpoint=1.0, measured_value=0.0, now=2.0)  # integral += 1*1 = 2
    assert out_1s == pytest.approx(1.0)
    assert out_2s == pytest.approx(2.0)


def test_derivative_responds_to_change_in_error():
    pid = _controller(kd=1.0, initial_output=0.0)
    pid.update(setpoint=0.0, measured_value=0.0, now=0.0)  # error=0
    output = pid.update(setpoint=0.0, measured_value=-5.0, now=1.0)  # error=5, d(error)/dt = 5/1
    assert output == pytest.approx(5.0)


def test_output_clamps_at_max():
    pid = _controller(kp=100.0, output_min=-1.0, output_max=1.0, initial_output=0.0)
    output = pid.update(setpoint=1000.0, measured_value=0.0, now=0.0)
    assert output == 1.0


def test_output_clamps_at_min():
    pid = _controller(kp=100.0, output_min=-1.0, output_max=1.0, initial_output=0.0)
    output = pid.update(setpoint=-1000.0, measured_value=0.0, now=0.0)
    assert output == -1.0


def test_anti_windup_recovers_without_overshoot_after_unclamping():
    """Drive the controller to saturation with a large, sustained error,
    then flip the error to the opposite sign. Without anti-windup, the
    accumulated integral would be so large that the output stays pinned
    at the wrong extreme for a long time after the error reverses. With
    the integral bounded to the range that alone could saturate the
    output, it should un-pin promptly."""
    pid = _controller(kp=0.0, ki=1.0, output_min=-10.0, output_max=10.0, initial_output=0.0)
    for t in range(1, 1000):
        pid.update(setpoint=1000.0, measured_value=0.0, now=float(t))
    assert pid.output == 10.0  # saturated high

    # Reverse the error sign for a few ticks -- should move off the
    # saturated extreme quickly, not stay pinned for ~1000 more ticks.
    output_after_reversal = None
    for t in range(1000, 1005):
        output_after_reversal = pid.update(setpoint=-1000.0, measured_value=0.0, now=float(t))
    assert output_after_reversal < 10.0


def test_reset_clears_state():
    pid = _controller(kp=1.0, ki=1.0, initial_output=0.0)
    pid.update(setpoint=10.0, measured_value=0.0, now=0.0)
    pid.update(setpoint=10.0, measured_value=0.0, now=1.0)
    pid.reset(output=0.0)
    # Immediately after reset, dt is 0 again (no prev_time) so only the
    # proportional term fires, as if this were the very first update.
    output = pid.update(setpoint=10.0, measured_value=0.0, now=100.0)
    assert output == pytest.approx(10.0)


def test_get_state_and_from_state_round_trip():
    pid = _controller(kp=1.0, ki=0.5, kd=0.1, output_min=-50.0, output_max=50.0, initial_output=0.0)
    pid.update(setpoint=5.0, measured_value=0.0, now=0.0)
    pid.update(setpoint=5.0, measured_value=1.0, now=1.0)
    state = pid.get_state()

    restored = PIDController.from_state(
        PIDGains(kp=1.0, ki=0.5, kd=0.1), output_min=-50.0, output_max=50.0, state=state, clock=lambda: 0.0
    )

    # Continuing from the restored state should produce the same next
    # output as continuing the original controller would have.
    expected = pid.update(setpoint=5.0, measured_value=2.0, now=2.0)
    actual = restored.update(setpoint=5.0, measured_value=2.0, now=2.0)
    assert actual == pytest.approx(expected)
