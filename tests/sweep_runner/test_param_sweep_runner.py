import pytest
from pytest_mock import MockerFixture

import numpy as np

from httomo.runner.auxiliary_data import AuxiliaryData
from httomo.runner.dataset import DataSetBlock
from httomo.runner.pipeline import Pipeline
from httomo.sweep_runner.param_sweep_runner import ParamSweepRunner
from httomo.sweep_runner.stages import Stages
from tests.testing_utils import make_test_loader, make_test_method


def test_without_prepare_block_property_raises_error(mocker: MockerFixture):
    loader = make_test_loader(mocker)
    pipeline = Pipeline(loader=loader, methods=[])
    stages = Stages(before_sweep=[], sweep=[], after_sweep=[])
    runner = ParamSweepRunner(pipeline=pipeline, stages=stages)
    with pytest.raises(ValueError) as e:
        runner.block
    assert "Block from input data has not yet been loaded" in str(e)


def test_after_prepare_block_attr_contains_data(mocker: MockerFixture):
    GLOBAL_SHAPE = PREVIEWED_SLICES_SHAPE = (180, 3, 160)
    data = np.arange(np.prod(PREVIEWED_SLICES_SHAPE), dtype=np.uint16).reshape(
        PREVIEWED_SLICES_SHAPE
    )
    aux_data = AuxiliaryData(np.ones(PREVIEWED_SLICES_SHAPE[0], dtype=np.float32))
    block = DataSetBlock(
        data=data,
        aux_data=aux_data,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        chunk_start=0,
        chunk_shape=GLOBAL_SHAPE,
        block_start=0,
    )
    loader = make_test_loader(mocker, block=block)
    pipeline = Pipeline(loader=loader, methods=[])
    stages = Stages(before_sweep=[], sweep=[], after_sweep=[])
    runner = ParamSweepRunner(pipeline=pipeline, stages=stages)
    runner.prepare()
    assert runner.block is not None
    np.testing.assert_array_equal(runner.block.data, data)


def tests_prepare_raises_error_if_too_many_sino_slices(mocker: MockerFixture):
    TOO_MANY_SINO_SLICES = 10
    GLOBAL_SHAPE = PREVIEWED_SLICES_SHAPE = (180, TOO_MANY_SINO_SLICES, 160)
    data = np.arange(np.prod(PREVIEWED_SLICES_SHAPE), dtype=np.uint16).reshape(
        PREVIEWED_SLICES_SHAPE
    )
    aux_data = AuxiliaryData(np.ones(PREVIEWED_SLICES_SHAPE[0], dtype=np.float32))
    block = DataSetBlock(
        data=data,
        aux_data=aux_data,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        chunk_start=0,
        chunk_shape=GLOBAL_SHAPE,
        block_start=0,
    )
    loader = make_test_loader(mocker, block=block)
    pipeline = Pipeline(loader=loader, methods=[])
    stages = Stages(before_sweep=[], sweep=[], after_sweep=[])
    runner = ParamSweepRunner(pipeline=pipeline, stages=stages)

    with pytest.raises(ValueError) as e:
        runner.prepare()

    err_str = (
        "Parameter sweep runs support input data containing <= 7 sinogram slices, "
        "input data contains 10 slices"
    )
    assert err_str in str(e)


@pytest.mark.parametrize("non_sweep_stage", ["before", "after"])
def test_execute_non_sweep_stage_modifies_block(
    mocker: MockerFixture,
    non_sweep_stage: str,
):
    # Define dummy block for loader to provide
    GLOBAL_SHAPE = PREVIEWED_SLICES_SHAPE = (180, 3, 160)
    data = np.ones(PREVIEWED_SLICES_SHAPE, dtype=np.float32)
    aux_data = AuxiliaryData(np.ones(PREVIEWED_SLICES_SHAPE[0], dtype=np.float32))
    block = DataSetBlock(
        data=data,
        aux_data=aux_data,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        chunk_start=0,
        chunk_shape=GLOBAL_SHAPE,
        block_start=0,
    )
    loader = make_test_loader(mocker, block=block)

    # Define two dummy methods to be in the "before sweep" stage in the runner
    def dummy_method_1(block: DataSetBlock):  # type: ignore
        block.data = block.data * 2
        return block

    def dummy_method_2(block: DataSetBlock):  # type: ignore
        block.data = block.data * 3
        return block

    # Patch `the `execute() method in the mock method wrapper objects so then the functions
    # that are used for the two methods executed in the stage are the two dummy methods defined
    # above
    m1 = make_test_method(mocker=mocker, method_name="method_1")
    mocker.patch.object(target=m1, attribute="execute", side_effect=dummy_method_1)
    m2 = make_test_method(mocker=mocker, method_name="method_2")
    mocker.patch.object(target=m2, attribute="execute", side_effect=dummy_method_2)

    # Define pipeline, stages, runner objects, and execute the methods in the stage
    # before/after the sweep
    #
    # NOTE: the pipeline object is only needed for providing the loader, and the methods needed
    # for the purpose of this test are only the ones in the "before/after sweep" stage, which
    # is why the pipeline and stages object both have only partial pipeline information
    pipeline = Pipeline(loader=loader, methods=[])
    if non_sweep_stage == "before":
        stages = Stages(
            before_sweep=[m1, m2],
            sweep=[],
            after_sweep=[],
        )
    else:
        stages = Stages(
            before_sweep=[],
            sweep=[],
            after_sweep=[m1, m2],
        )

    runner = ParamSweepRunner(pipeline=pipeline, stages=stages)
    runner.prepare()
    if non_sweep_stage == "before":
        runner.execute_before_sweep()
    else:
        runner.execute_after_sweep()

    # Inspect the block data after the "before sweep" stage has completed, asserting that the
    # data reflects what the combination of two dummy methods in that stage should produce
    assert runner.block.data.shape == PREVIEWED_SLICES_SHAPE
    expected_block_data = data * 2 * 3
    np.testing.assert_array_equal(runner.block.data, expected_block_data)
