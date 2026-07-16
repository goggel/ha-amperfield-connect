"""Tests for the Amperfield Modbus client."""

from __future__ import annotations

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
