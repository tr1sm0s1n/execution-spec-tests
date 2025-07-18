"""Test bad TXCREATE cases."""

import pytest

from ethereum_test_base_types import Bytes
from ethereum_test_base_types.base_types import Address, Hash
from ethereum_test_forks import Fork
from ethereum_test_tools import (
    Account,
    Alloc,
    Environment,
    EVMCodeType,
    StateTestFiller,
    Transaction,
    compute_eofcreate_address,
)
from ethereum_test_tools.vm.opcode import Opcodes as Op
from ethereum_test_types.eof.v1 import Container, Section
from ethereum_test_types.eof.v1.constants import MAX_BYTECODE_SIZE, MAX_INITCODE_SIZE
from ethereum_test_vm.bytecode import Bytecode

from .. import EOF_FORK_NAME
from ..eip7069_extcall.spec import EXTCALL_FAILURE, EXTCALL_REVERT, LEGACY_CALL_FAILURE
from ..eip7620_eof_create.helpers import (
    aborting_container,
    slot_call_or_create,
    slot_call_result,
    slot_code_should_fail,
    slot_code_worked,
    slot_counter,
    slot_create_address,
    slot_max_depth,
    slot_returndata,
    slot_returndata_size,
    smallest_initcode_subcontainer,
    smallest_runtime_subcontainer,
    value_canary_should_not_change,
    value_canary_to_be_overwritten,
    value_code_worked,
)
from .spec import TXCREATE_FAILURE

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-7873.md"
REFERENCE_SPEC_VERSION = "1115fe6110fcc0efc823fb7f8f5cd86c42173efe"

pytestmark = pytest.mark.valid_from(EOF_FORK_NAME)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "revert",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x08\xc3\x79\xa0", id="Error(string)"),
    ],
)
def test_initcode_revert(state_test: StateTestFiller, pre: Alloc, revert: bytes):
    """Verifies proper handling of REVERT in initcode."""
    env = Environment()
    revert_size = len(revert)

    initcode_subcontainer = Container(
        name="Initcode Subcontainer that reverts",
        sections=[
            Section.Code(
                code=Op.MSTORE(0, Op.PUSH32(revert)) + Op.REVERT(32 - revert_size, revert_size),
            ),
        ],
    )
    initcode_hash = initcode_subcontainer.hash

    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash))
        + Op.SSTORE(slot_returndata_size, Op.RETURNDATASIZE)
        + Op.RETURNDATACOPY(Op.SUB(32, Op.RETURNDATASIZE), 0, Op.RETURNDATASIZE)
        + Op.SSTORE(slot_returndata, Op.MLOAD(0))
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP
    )

    post = {
        contract_address: Account(
            storage={
                slot_create_address: TXCREATE_FAILURE,
                slot_returndata_size: revert_size,
                slot_returndata: revert,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=10_000_000,
        sender=sender,
        initcodes=[initcode_subcontainer],
    )
    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "initcode_hash",
    [
        Bytes("").keccak256(),
        Bytes("00" * 32),
        Bytes("FF" * 32),
        Bytes("EF01").keccak256(),
        smallest_runtime_subcontainer.hash,
    ],
)
@pytest.mark.parametrize("tx_initcode_count", [1, 255, 256])
def test_txcreate_invalid_hash(
    state_test: StateTestFiller, pre: Alloc, tx_initcode_count: int, initcode_hash: Hash
):
    """Verifies proper handling of REVERT in initcode."""
    env = Environment()

    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash))
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP
    )

    post = {
        contract_address: Account(
            storage={
                slot_create_address: TXCREATE_FAILURE,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=10_000_000,
        sender=sender,
        initcodes=[smallest_initcode_subcontainer] * tx_initcode_count,
    )
    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
def test_initcode_aborts(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """Verifies correct handling of a halt in EOF initcode."""
    env = Environment()
    sender = pre.fund_eoa()
    initcode_hash = aborting_container.hash
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash))
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP,
    )
    # Storage in slot_create_address should not have the address,
    post = {
        contract_address: Account(
            storage={
                slot_create_address: TXCREATE_FAILURE,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=10_000_000,
        sender=sender,
        initcodes=[aborting_container],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


"""
Size of the initcode portion of test_txcreate_deploy_sizes, but as the runtime code is dynamic, we
have to use a pre-calculated size
"""
initcode_size = 32


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "target_deploy_size",
    [
        pytest.param(0x4000, id="large"),
        pytest.param(MAX_BYTECODE_SIZE, id="max"),
        pytest.param(MAX_BYTECODE_SIZE + 1, id="overmax"),
        pytest.param(MAX_INITCODE_SIZE - initcode_size - 1, id="below_initcodemax"),
        pytest.param(MAX_INITCODE_SIZE - initcode_size, id="initcodemax"),
    ],
)
def test_txcreate_deploy_sizes(
    state_test: StateTestFiller,
    pre: Alloc,
    target_deploy_size: int,
):
    """Verifies a mix of runtime contract sizes mixing success and multiple size failure modes."""
    env = Environment()

    runtime_container = Container(
        sections=[
            Section.Code(
                code=Op.JUMPDEST * (target_deploy_size - len(smallest_runtime_subcontainer))
                + Op.STOP,
            ),
        ]
    )

    initcode_subcontainer = Container(
        name="Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.RETURNCODE[0](0, 0),
            ),
            Section.Container(container=runtime_container),
        ],
    )
    assert initcode_size == len(initcode_subcontainer) - len(runtime_container)

    assert initcode_size == (len(initcode_subcontainer) - len(runtime_container)), (
        "initcode_size is wrong, expected initcode_size is %d, calculated is %d"
        % (
            initcode_size,
            len(initcode_subcontainer) - len(runtime_container),
        )
    )
    initcode_hash = initcode_subcontainer.hash

    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash))
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP
    )
    # Storage in 0 should have the address,
    # Storage 1 is a canary of 1 to make sure it tried to execute, which also covers cases of
    #   data+code being greater than initcode_size_max, which is allowed.
    success = target_deploy_size <= MAX_BYTECODE_SIZE
    post = {
        contract_address: Account(
            storage={
                slot_create_address: compute_eofcreate_address(contract_address, 0)
                if success
                else TXCREATE_FAILURE,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account()
        if success
        else Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=20_000_000,
        sender=sender,
        initcodes=[initcode_subcontainer],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "auxdata_size",
    [
        pytest.param(MAX_BYTECODE_SIZE - len(smallest_runtime_subcontainer), id="maxcode"),
        pytest.param(MAX_BYTECODE_SIZE - len(smallest_runtime_subcontainer) + 1, id="overmaxcode"),
        pytest.param(0x10000 - 60, id="almost64k"),
        pytest.param(0x10000 - 1, id="64k-1"),
        pytest.param(0x10000, id="64k"),
        pytest.param(0x10000 + 1, id="over64k"),
    ],
)
def test_auxdata_size_failures(state_test: StateTestFiller, pre: Alloc, auxdata_size: int):
    """Exercises a number of auxdata size violations, and one maxcode success."""
    env = Environment()
    auxdata_bytes = b"a" * auxdata_size

    initcode_subcontainer = Container(
        name="Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE) + Op.RETURNCODE[0](0, Op.CALLDATASIZE),
            ),
            Section.Container(container=smallest_runtime_subcontainer),
        ],
    )

    sender = pre.fund_eoa()
    initcode_hash = initcode_subcontainer.hash
    contract_address = pre.deploy_contract(
        code=Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE)
        + Op.SSTORE(
            slot_create_address,
            Op.TXCREATE(tx_initcode_hash=initcode_hash, input_size=Op.CALLDATASIZE),
        )
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP,
    )

    deployed_container_size = len(smallest_runtime_subcontainer) + auxdata_size

    # Storage in 0 will have address in first test, 0 in all other cases indicating failure
    # Storage 1 in 1 is a canary to see if TXCREATE opcode halted
    success = deployed_container_size <= MAX_BYTECODE_SIZE
    post = {
        contract_address: Account(
            storage={
                slot_create_address: compute_eofcreate_address(contract_address, 0)
                if deployed_container_size <= MAX_BYTECODE_SIZE
                else 0,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account()
        if success
        else Account.NONEXISTENT,
    }

    tx = Transaction(
        to=contract_address,
        gas_limit=20_000_000,
        sender=sender,
        initcodes=[initcode_subcontainer],
        data=auxdata_bytes,
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(1, id="1_wei"),
        pytest.param(10**9, id="1_gwei"),
    ],
)
def test_txcreate_insufficient_stipend(
    state_test: StateTestFiller,
    pre: Alloc,
    value: int,
):
    """
    Exercises an TXCREATE that fails because the calling account does not have enough ether to
    pay the stipend.
    """
    env = Environment()
    sender = pre.fund_eoa(10**11)
    initcode_hash = smallest_initcode_subcontainer.hash

    contract_address = pre.deploy_contract(
        code=Op.SSTORE(
            slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash, value=value)
        )
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP,
        balance=value - 1,
    )
    # create will fail but not trigger a halt, so canary at storage 1 should be set
    # also validate target created contract fails
    post = {
        contract_address: Account(
            storage={
                slot_create_address: TXCREATE_FAILURE,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=20_000_000,
        sender=sender,
        initcodes=[smallest_initcode_subcontainer],
    )
    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
def test_insufficient_initcode_gas(state_test: StateTestFiller, pre: Alloc, fork: Fork):
    """Exercises an TXCREATE when there is not enough gas for the constant charge."""
    env = Environment()

    initcode_container = Container(
        sections=[
            Section.Code(
                code=Op.RETURNCODE[0](0, 0),
            ),
            Section.Container(container=smallest_runtime_subcontainer),
        ],
    )
    initcode_hash = initcode_container.hash

    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_create_address, Op.TXCREATE(tx_initcode_hash=initcode_hash))
        + Op.SSTORE(slot_code_should_fail, value_code_worked)
        + Op.STOP,
        storage={
            slot_create_address: value_canary_should_not_change,
            slot_code_should_fail: value_canary_should_not_change,
        },
    )
    # enough gas for everything but EVM opcodes and EIP-150 reserves
    # FIXME: should not use that calculator!!!
    # FIXME: the -1000 is a wild guess - revisit this
    gas_limit = (
        32_000 - 1_000 + fork.transaction_intrinsic_cost_calculator()(calldata=initcode_container)
    )
    # out_of_gas is triggered, so canary won't set value
    # also validate target created contract fails
    post = {
        contract_address: Account(
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=gas_limit,
        sender=sender,
        initcodes=[initcode_container],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
def test_insufficient_gas_memory_expansion(
    state_test: StateTestFiller,
    pre: Alloc,
    fork: Fork,
):
    """Exercises TXCREATE when the memory for auxdata has not been expanded but is requested."""
    env = Environment()

    auxdata_size = 0x5000
    initcode_hash = smallest_initcode_subcontainer.hash
    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(
            slot_create_address,
            Op.TXCREATE(tx_initcode_hash=initcode_hash, input_size=auxdata_size),
        )
        + Op.SSTORE(slot_code_should_fail, slot_code_worked)
        + Op.STOP,
        storage={
            slot_create_address: value_canary_should_not_change,
            slot_code_should_fail: value_canary_should_not_change,
        },
    )
    # enough gas for everything but EVM opcodes and EIP-150 reserves
    auxdata_size_words = (auxdata_size + 31) // 32
    gas_limit = (
        32_000
        + 3 * auxdata_size_words
        + auxdata_size_words * auxdata_size_words // 512
        + fork.transaction_intrinsic_cost_calculator()(calldata=smallest_initcode_subcontainer)
    )
    # out_of_gas is triggered, so canary won't set value
    # also validate target created contract fails
    post = {
        contract_address: Account(
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=gas_limit,
        sender=sender,
        initcodes=[smallest_initcode_subcontainer],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
def test_insufficient_returncode_auxdata_gas(
    state_test: StateTestFiller,
    pre: Alloc,
    fork: Fork,
):
    """Exercises a RETURNCODE when there is not enough gas for the initcode charge."""
    env = Environment()

    auxdata_size = 0x5000
    initcode_container = Container(
        name="Large Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.RETURNCODE[0](0, auxdata_size),
            ),
            Section.Container(container=smallest_runtime_subcontainer),
        ],
    )
    initcode_hash = initcode_container.hash

    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.TXCREATE(tx_initcode_hash=initcode_hash)
        + Op.STOP,
        storage={
            slot_code_worked: value_canary_to_be_overwritten,
        },
    )
    # 63/64ths is not enough to cover RETURNCODE memory expansion. Unfortunately the 1/64th left
    # won't realistically accommodate a SSTORE
    auxdata_size_words = (auxdata_size + 31) // 32
    gas_limit = (
        32_000
        + 2600  # SSTORE
        + 3 * auxdata_size_words
        + auxdata_size_words * auxdata_size_words // 512
        + fork.transaction_intrinsic_cost_calculator()(calldata=initcode_container)
    )
    # out_of_gas is triggered in the initcode context, so canary will set value
    # also validate target created contract fails
    post = {
        contract_address: Account(
            storage={
                slot_code_worked: value_code_worked,
            },
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=gas_limit,
        sender=sender,
        initcodes=[initcode_container],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "opcode",
    [
        Op.STATICCALL,
        Op.EXTSTATICCALL,
    ],
)
@pytest.mark.parametrize("endowment", [0, 1])  # included to verify static flag check comes first
@pytest.mark.parametrize(
    "initcode",
    [smallest_initcode_subcontainer, aborting_container],
    ids=["working_initcode", "aborting_code"],
)
def test_static_flag_txcreate(
    state_test: StateTestFiller,
    pre: Alloc,
    opcode: Op,
    endowment: int,
    initcode: Container,
):
    """Verifies correct handling of the static call flag with TXCREATE."""
    env = Environment()
    initcode_hash = initcode.hash
    sender = pre.fund_eoa()
    contract_address = pre.deploy_contract(
        code=Op.TXCREATE(tx_initcode_hash=initcode_hash, value=endowment) + Op.STOP,
    )
    calling_code = (
        Op.SSTORE(slot_call_result, opcode(address=contract_address))
        + Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.STOP
    )
    calling_address = pre.deploy_contract(
        calling_code,
        # Need to override the global value from the `with_all_evm_code_types` marker.
        evm_code_type=EVMCodeType.EOF_V1 if opcode == Op.EXTSTATICCALL else EVMCodeType.LEGACY,
    )

    post = {
        calling_address: Account(
            storage={
                slot_call_result: EXTCALL_FAILURE
                if opcode == Op.EXTSTATICCALL
                else LEGACY_CALL_FAILURE,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account.NONEXISTENT,
    }
    tx = Transaction(
        to=calling_address,
        gas_limit=10_000_000,
        sender=sender,
        initcodes=[initcode],
    )

    state_test(env=env, pre=pre, post=post, tx=tx)


magic_value_call = 0xCA11
magic_value_create = 0xCC12EA7E


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "who_fails",
    [magic_value_call, magic_value_create],
    ids=["call_fails", "create_fails"],
)
@pytest.mark.pre_alloc_modify
def test_eof_txcreate_msg_depth(
    state_test: StateTestFiller,
    pre: Alloc,
    who_fails: int,
    evm_code_type: EVMCodeType,
):
    """
    Test TXCREATE handles msg depth limit correctly (1024).
    NOTE: due to block gas limit and the 63/64th rule this limit is unlikely to be hit
          on mainnet.
    NOTE: See `tests/unscheduled/eip7692_eof_v1/eip7069_extcall/test_calls.py::test_eof_calls_msg_depth`
          for more explanations and comments. Most notable deviation from that test is that here
          calls and `TXCREATE`s alternate in order to reach the max depth. `who_fails` decides
          whether the failing depth 1024 will be on a call or on an `TXCREATE` to happen.
    """  # noqa: E501
    # Not a precise gas_limit formula, but enough to exclude risk of gas causing the failure.
    gas_limit = int(20000000 * (64 / 63) ** 1024)
    env = Environment(gas_limit=gas_limit)

    callee_address = Address(0x5000)

    # Memory offsets layout:
    # - 0  - input - msg depth
    # - 32 - output - msg depth
    # - 64 - output - call result
    # - 96 - output - magic value: create or call
    returndatacopy_block = Op.RETURNDATACOPY(32, 0, 96) + Op.REVERT(32, 96)
    deep_most_result_block = (
        Op.MSTORE(32, Op.ADD(Op.CALLDATALOAD(0), 1)) + Op.MSTORE(64, Op.NOOP) + Op.REVERT(32, 96)
    )
    rjump_offset = len(returndatacopy_block)
    initcode = Container.Code(
        Op.MSTORE(0, Op.ADD(Op.CALLDATALOAD(0), 1))
        + Op.MSTORE(96, magic_value_call)
        + Op.EXTCALL(address=callee_address, args_size=32)
        + Op.RETURNDATASIZE
        + Op.ISZERO
        + Op.RJUMPI[rjump_offset]
        + returndatacopy_block
        + deep_most_result_block
    )

    initcode_hash = initcode.hash
    sender = pre.fund_eoa()

    jump_code = (
        Op.RJUMPI[rjump_offset]
        if evm_code_type == EVMCodeType.EOF_V1
        else Op.ADD(Op.PC, rjump_offset + 3) + Op.JUMPI
    )
    callee_code = (
        Op.MSTORE(0, Op.ADD(Op.CALLDATALOAD(0), 1))
        + Op.MSTORE(96, magic_value_create)
        + Op.TXCREATE(tx_initcode_hash=initcode_hash, salt=Op.CALLDATALOAD(0), input_size=32)
        + Op.RETURNDATASIZE
        + Op.ISZERO
        + jump_code
        + returndatacopy_block
        + Op.JUMPDEST
        + deep_most_result_block
    )

    pre.deploy_contract(callee_code, address=callee_address)

    calling_contract_address = pre.deploy_contract(
        Container.Code(
            Op.MSTORE(0, Op.CALLDATALOAD(0))
            + Op.EXTCALL(address=callee_address, args_size=32)
            + Op.SSTORE(slot_max_depth, Op.RETURNDATALOAD(0))
            + Op.SSTORE(slot_call_result, Op.RETURNDATALOAD(32))
            + Op.SSTORE(slot_call_or_create, Op.RETURNDATALOAD(64))
            + Op.SSTORE(slot_code_worked, value_code_worked)
            + Op.STOP
        )
    )

    # Only bumps the msg call depth "register" and forwards to the `calling_contract_address`.
    # If it is used it makes the "failing" depth of 1024 to happen on TXCREATE, instead of CALL.
    passthrough_address = pre.deploy_contract(
        Container.Code(
            Op.MSTORE(0, 1) + Op.EXTCALL(address=calling_contract_address, args_size=32) + Op.STOP
        )
    )

    tx = Transaction(
        sender=sender,
        initcodes=[initcode],
        to=calling_contract_address if who_fails == magic_value_call else passthrough_address,
        gas_limit=gas_limit,
        data="",
    )

    calling_storage = {
        slot_max_depth: 1024,
        slot_code_worked: value_code_worked,
        slot_call_result: EXTCALL_REVERT if who_fails == magic_value_call else TXCREATE_FAILURE,
        slot_call_or_create: who_fails,
    }

    post = {
        calling_contract_address: Account(storage=calling_storage),
    }

    state_test(
        env=env,
        pre=pre,
        post=post,
        tx=tx,
    )


@pytest.mark.with_all_evm_code_types
def test_reentrant_txcreate(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """Verifies a reentrant TXCREATE case, where EIP-161 prevents conflict via nonce bump."""
    env = Environment()
    # Calls into the factory contract with 1 as input.
    reenter_code = Op.MSTORE(0, 1) + Op.EXTCALL(address=Op.CALLDATALOAD(32), args_size=32)
    # Initcode: if given 0 as 1st word of input will call into the factory again.
    #           2nd word of input is the address of the factory.
    initcontainer = Container(
        sections=[
            Section.Code(
                Op.SSTORE(slot_counter, Op.ADD(Op.SLOAD(slot_counter), 1))
                + Op.CALLDATALOAD(0)
                + Op.RJUMPI[len(reenter_code)]
                + reenter_code
                + Op.RETURNCODE[0](0, 0)
            ),
            Section.Container(smallest_runtime_subcontainer),
        ]
    )
    initcode_hash = initcontainer.hash
    # Factory: Passes on its input into the initcode. It's 0 first time, 1 the second time.
    #          Saves the result of deployment in slot 0 first time, 1 the second time.
    contract_address = pre.deploy_contract(
        code=Op.CALLDATACOPY(0, 0, 32)
        + Op.MSTORE(32, Op.ADDRESS)
        # 1st word - copied from input (reenter flag), 2nd word - `this.address`.
        + Op.SSTORE(
            Op.CALLDATALOAD(0),
            Op.TXCREATE(tx_initcode_hash=initcode_hash, input_size=64),
        )
        + Op.STOP,
        storage={0: 0xB17D, 1: 0xB17D},  # a canary to be overwritten
    )
    # Flow is: reenter flag 0 -> factory -> reenter flag 0 -> initcode -> reenter ->
    #          reenter flag 1 -> factory -> reenter flag 1 -> (!) initcode -> stop,
    # if the EIP-161 nonce bump is not implemented. If it is, it fails before second
    # inicode marked (!).
    # Storage in 0 should have the address from the outer TXCREATE.
    # Storage in 1 should have 0 from the inner TXCREATE.
    # For the created contract storage in `slot_counter` should be 1 as initcode executes only once
    post = {
        contract_address: Account(
            storage={
                0: compute_eofcreate_address(contract_address, 0),
                1: 0,
            }
        ),
        compute_eofcreate_address(contract_address, 0): Account(
            nonce=1, code=smallest_runtime_subcontainer, storage={slot_counter: 1}
        ),
    }
    tx = Transaction(
        to=contract_address,
        gas_limit=500_000,
        initcodes=[initcontainer],
        sender=pre.fund_eoa(),
    )
    state_test(env=env, pre=pre, post=post, tx=tx)


@pytest.mark.with_all_evm_code_types
@pytest.mark.parametrize(
    "reason",
    [
        "valid",
        "invalid_deploy_container",
        "invalid_initcode",
        "invalid_opcode_during_initcode",
        "invalid_opcode_with_sstore_during_initcode",
        "revert_opcode_during_initcode",
        "out_of_gas_during_initcode",
        "out_of_gas_when_returning_contract",
        "out_of_gas_when_returning_contract_due_to_memory_expansion",
    ],
)
def test_invalid_container_deployment(
    state_test: StateTestFiller,
    fork: Fork,
    pre: Alloc,
    reason: str,
):
    """Verify contract is not deployed when an invalid container deployment is attempted."""
    env = Environment()
    sender = pre.fund_eoa()

    # Valid defaults
    deployed_container = Container(
        sections=[
            Section.Code(code=Op.CALLF[1](Op.PUSH0, Op.PUSH0) + Op.STOP),
            Section.Code(code=Op.ADD + Op.RETF, code_inputs=2, code_outputs=1),
        ]
    )
    initcontainer: Container = Container(
        sections=[
            Section.Code(code=Op.RETURNCODE[0](0, 0)),
            Section.Container(deployed_container),
        ],
    )
    tx_gas_limit = 100_000
    fork_intrinsic_gas_calculator = fork.transaction_intrinsic_cost_calculator()
    fork_gas_costs = fork.gas_costs()

    # Modify defaults based on invalidity reason
    if reason == "invalid_deploy_container":
        deployed_container = Container(
            sections=[
                Section.Code(code=Op.CALLF[1](Op.PUSH0, Op.PUSH0) + Op.STOP),
                Section.Code(code=Op.ADD + Op.RETF, code_outputs=0),
            ]
        )
        initcontainer = Container(
            sections=[
                Section.Code(code=Op.RETURNCODE[0](0, 0)),
                Section.Container(deployed_container),
            ],
        )
    elif reason == "invalid_initcode":
        initcontainer = Container(
            sections=[
                Section.Code(code=Op.RETURNCODE[1](0, 0)),
                Section.Container(deployed_container),
            ],
        )
    elif (
        reason == "invalid_opcode_during_initcode"
        or reason == "invalid_opcode_with_sstore_during_initcode"
        or reason == "revert_opcode_during_initcode"
        or reason == "out_of_gas_during_initcode"
    ):
        invalid_code_path: Bytecode
        if reason == "invalid_opcode_with_sstore_during_initcode":
            invalid_code_path = Op.SSTORE(0, 1) + Op.INVALID
        elif reason == "revert_opcode_during_initcode":
            invalid_code_path = Op.REVERT(0, 0)
        elif reason == "out_of_gas_during_initcode":
            invalid_code_path = Op.MSTORE(0xFFFFFFFFFFFFFFFFFFFFFFFFFFF, 1)
        elif reason == "invalid_opcode_during_initcode":
            invalid_code_path = Op.INVALID
        else:
            raise Exception(f"invalid case: {reason}")
        initcontainer = Container(
            sections=[
                Section.Code(
                    code=Op.RJUMPI[len(invalid_code_path)](Op.PUSH0)
                    + invalid_code_path
                    + Op.RETURNCODE[0](0, 0)
                ),
                Section.Container(deployed_container),
            ],
        )
    elif reason == "out_of_gas_when_returning_contract":
        factory_gas_cost = (
            7 * fork_gas_costs.G_VERY_LOW
            + fork_gas_costs.G_STORAGE_SET
            + fork_gas_costs.G_COLD_SLOAD
            + fork_gas_costs.G_CREATE
        )
        initcode_gas_cost = 2 * fork_gas_costs.G_VERY_LOW
        tx_gas_limit = (
            fork_intrinsic_gas_calculator(calldata=initcontainer)
            + factory_gas_cost
            + (initcode_gas_cost - 1) * 64 // 63
        )
    elif reason == "out_of_gas_when_returning_contract_due_to_memory_expansion":
        factory_gas_cost = (
            7 * fork_gas_costs.G_VERY_LOW
            + fork_gas_costs.G_STORAGE_SET
            + fork_gas_costs.G_COLD_SLOAD
            + fork_gas_costs.G_CREATE
        )
        initcode_gas_cost = (
            # Code deposit gas cost
            len(deployed_container) * fork_gas_costs.G_CODE_DEPOSIT_BYTE
            # Two push opcodes
            + 2 * fork_gas_costs.G_VERY_LOW
        )
        tx_gas_limit = (
            fork_intrinsic_gas_calculator(calldata=initcontainer)
            + factory_gas_cost
            + initcode_gas_cost * 64 // 63
        )
        initcontainer = Container(
            sections=[
                Section.Code(code=Op.RETURNCODE[0](0xFFFFFFFFFFFFFFFFFFFFFFFFFFF, 0x1)),
                Section.Container(deployed_container),
            ],
        )
    elif reason == "valid":
        pass
    else:
        raise TypeError("Unexpected reason", reason)

    initcode_hash = initcontainer.hash
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(slot_code_worked, value_code_worked)
        + Op.TXCREATE(tx_initcode_hash=initcode_hash)
        + Op.STOP
    )

    tx = Transaction(
        to=contract_address,
        sender=sender,
        gas_limit=tx_gas_limit,
        initcodes=[initcontainer],
    )

    destination_contract_address = compute_eofcreate_address(contract_address, 0)

    post = (
        {
            destination_contract_address: Account.NONEXISTENT,
            contract_address: Account(
                nonce=1 if reason in ["invalid_initcode", "invalid_deploy_container"] else 2,
                storage={
                    slot_code_worked: value_code_worked,
                },
            ),
        }
        if reason != "valid"
        else {
            destination_contract_address: Account(nonce=1, code=deployed_container),
            contract_address: Account(
                nonce=2,
                storage={
                    slot_code_worked: value_code_worked,
                },
            ),
        }
    )

    state_test(
        env=env,
        pre=pre,
        post=post,
        tx=tx,
    )
