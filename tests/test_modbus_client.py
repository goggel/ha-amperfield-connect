"""Tests for the Amperfied Modbus client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.amperfield_connect import modbus_client as module


class Response:
    """Minimal successful pymodbus response."""

    def __init__(self, registers: list[int]) -> None:
        self.registers = registers

    def isError(self) -> bool:  # noqa: N802 - pymodbus API name
        return False


class ErrorResponse:
    """Minimal pymodbus exception response."""

    def __init__(self, exception_code: int) -> None:
        self.exception_code = exception_code

    def isError(self) -> bool:  # noqa: N802 - pymodbus API name
        return True

    def __str__(self) -> str:
        return f"Modbus error {self.exception_code}"


class FakePymodbusClient:
    """Controllable async pymodbus client."""

    def __init__(self) -> None:
        self.connected = True
        self.input_calls: list[tuple[int, int]] = []
        self.holding_calls: list[tuple[int, int]] = []
        self.input_handler = None
        self.holding_handler = None
        self.write_register = AsyncMock(return_value=Response([]))

    async def connect(self) -> bool:
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False

    async def read_input_registers(self, *, address: int, count: int):
        self.input_calls.append((address, count))
        if self.input_handler is not None:
            return await self.input_handler(address, count)
        return Response(list(range(address, address + count)))

    async def read_holding_registers(self, *, address: int, count: int):
        self.holding_calls.append((address, count))
        if self.holding_handler is not None:
            return await self.holding_handler(address, count)
        return Response([0] * count)


def make_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[module.AmperfieldModbusClient, FakePymodbusClient]:
    """Create a client with a fake pymodbus transport."""
    monkeypatch.setattr(module, "MODBUS_DELAY", 0)
    client = module.AmperfieldModbusClient("wallbox.local", 502)
    transport = FakePymodbusClient()
    client._client = transport  # noqa: SLF001 - intentional transport seam
    return client, transport


@pytest.mark.asyncio
async def test_selected_values_are_read_as_one_contiguous_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adjacent requested registers should use one Modbus transaction."""
    client, transport = make_client(monkeypatch)

    data = await client.fetch_selected_data(
        {"charging_state", "current_l1", "current_l2", "current_l3"}
    )

    assert transport.input_calls == [(5, 4)]
    assert data == {
        "charging_state": 5,
        "current_l1": 0.6,
        "current_l2": 0.7,
        "current_l3": 0.8,
    }


@pytest.mark.asyncio
async def test_transport_failure_is_not_converted_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead connection must fail the coordinator poll."""
    client, transport = make_client(monkeypatch)

    async def fail(_address: int, _count: int):
        raise OSError("connection reset")

    transport.input_handler = fail

    with pytest.raises(module.AmperfieldConnectionError):
        await client.fetch_selected_data({"charging_state"})


@pytest.mark.asyncio
async def test_illegal_address_isolated_to_optional_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported key should be unknown without masking supported keys."""
    client, transport = make_client(monkeypatch)

    async def respond(address: int, count: int):
        if (address, count) == (5000, 2):
            return ErrorResponse(module.MODBUS_ILLEGAL_ADDRESS)
        if address == 5001:
            return ErrorResponse(module.MODBUS_ILLEGAL_ADDRESS)
        return Response([3200])

    transport.input_handler = respond
    data = await client.fetch_selected_data({"max_power_set", "phase_switch_state"})

    assert data == {"max_power_set": 3200, "phase_switch_state": None}
    assert transport.input_calls == [(5000, 2), (5000, 1), (5001, 1)]


@pytest.mark.asyncio
async def test_phase_switch_probe_only_accepts_illegal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Illegal address means unsupported; transport errors still propagate."""
    client, transport = make_client(monkeypatch)
    transport.input_handler = AsyncMock(
        return_value=ErrorResponse(module.MODBUS_ILLEGAL_ADDRESS)
    )
    assert await client.probe_phase_switching() is False

    transport.input_handler = AsyncMock(side_effect=OSError("offline"))
    with pytest.raises(module.AmperfieldConnectionError):
        await client.probe_phase_switching()


@pytest.mark.parametrize(
    "host",
    ["", "https://wallbox.local", "wallbox.local/path", "wallbox.local\nforged"],
)
def test_client_rejects_malformed_hosts(host: str) -> None:
    """Connection targets must be hosts, never URLs or log-control payloads."""
    with pytest.raises(ValueError):
        module.AmperfieldModbusClient(host, 502)


@pytest.mark.parametrize("port", [0, 65536, True])
def test_client_rejects_invalid_ports(port: int) -> None:
    """Only real TCP ports should reach the transport constructor."""
    with pytest.raises(ValueError):
        module.AmperfieldModbusClient("wallbox.local", port)


@pytest.mark.asyncio
async def test_generic_writer_enforces_allowlist_and_safe_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic helper must not allow arbitrary or unsafe register writes."""
    client, transport = make_client(monkeypatch)

    assert await client._write_using_register_map("charging_state", 1) is False
    assert await client._write_using_register_map("max_current", 100) is False
    assert await client._write_using_register_map("max_current", float("nan")) is False
    transport.write_register.assert_not_awaited()

    assert await client._write_using_register_map("max_current", 16) is True
    transport.write_register.assert_awaited_once_with(address=261, value=160)


def test_device_strings_cannot_inject_control_characters() -> None:
    """Device-controlled identification values must remain safe for logs."""
    decoder = module.REGISTER_MAP["serial_number"].decoder

    assert decoder([0x4142, 0x0A43, 0x0000]) == "AB\N{REPLACEMENT CHARACTER}C"


@pytest.mark.parametrize(
    ("key", "registers", "selected"),
    [
        ("charging_state", [], False),
        ("serial_number", [0x4142], False),
        ("energy_cycle", [1], True),
        ("charging_state", [1, 2], True),
    ],
)
@pytest.mark.asyncio
async def test_malformed_register_lengths_raise_protocol_error(
    monkeypatch: pytest.MonkeyPatch, key: str, registers: list[int], selected: bool
) -> None:
    """Neither identity nor numeric decoders may accept malformed replies."""
    client, transport = make_client(monkeypatch)
    transport.input_handler = AsyncMock(return_value=Response(registers))

    with pytest.raises(module.AmperfieldProtocolError, match="expected .* registers"):
        if selected:
            await client.fetch_selected_data({key})
        else:
            await client._read_using_register_map(key)


@pytest.mark.asyncio
async def test_closed_client_cannot_resume_or_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late flow rollback must never resurrect a permanently closed client."""
    client, transport = make_client(monkeypatch)
    transport.connect = AsyncMock(return_value=True)
    await client.suspend()
    await client.close()

    assert await client.resume() is False
    assert await client.connect() is False
    client._start_heartbeat()
    assert client._heartbeat_task is None
    transport.connect.assert_not_awaited()
    with pytest.raises(module.AmperfieldConnectionError, match="permanently closed"):
        await client.get_modbus_version()


@pytest.mark.asyncio
async def test_resume_queued_before_close_does_not_reopen_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal closure takes precedence over a rollback waiting for the lock."""
    client, transport = make_client(monkeypatch)
    transport.connect = AsyncMock(return_value=True)
    await client.suspend()
    await client._operation_lock.acquire()
    resume = asyncio.create_task(client.resume())
    await asyncio.sleep(0)
    close = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    client._operation_lock.release()
    resumed, _ = await asyncio.gather(resume, close)

    assert resumed is False
    assert client._heartbeat_task is None
    transport.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_suspended_client_resumes_heartbeat_and_closes_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary suspension remains reversible without weakening terminal close."""
    client, transport = make_client(monkeypatch)
    await client.suspend()
    assert await client.connect() is False
    assert await client.resume() is True
    heartbeat = client._heartbeat_task
    assert heartbeat is not None
    assert transport.connected
    await client.close()
    assert heartbeat.done()
    assert client._heartbeat_task is None
    assert not transport.connected


@pytest.mark.parametrize(
    ("mode", "key", "value", "allowed"),
    [
        ("current", "max_current", 10, True),
        ("current", "max_power_target", 3200, False),
        ("power", "max_current", 0, False),
        ("power", "max_current", 10, False),
        ("power", "phase_switch_control", 1, False),
        ("power", "max_power_target", 3200, True),
        ("power", "failsafe_current", 6, True),
    ],
)
@pytest.mark.asyncio
async def test_control_modes_prevent_conflicting_register_writes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    key: str,
    value: int,
    allowed: bool,
) -> None:
    """Current/phase commands and automatic power commands are exclusive."""
    client, transport = make_client(monkeypatch)
    client.control_mode = mode
    assert await client._write_using_register_map(key, value) is allowed
    assert transport.write_register.await_count == int(allowed)
