import pytest
import numpy as np

from httomo.data.param_sweep_store import ParamSweepWriter
from httomo.runner.auxiliary_data import AuxiliaryData
from httomo.sweep_runner.param_sweep_block import ParamSweepBlock


def make_param_sweep_writer() -> ParamSweepWriter:
    NO_OF_SWEEPS = 5
    SWEEP_RES_SHAPE = (180, 3, 160)
    return ParamSweepWriter(
        no_of_sweeps=NO_OF_SWEEPS,
        single_shape=SWEEP_RES_SHAPE,
    )


def test_param_sweep_writer_get_no_of_sweeps():
    writer = make_param_sweep_writer()
    assert writer.no_of_sweeps == 5


def test_param_sweep_writer_get_concat_dim():
    writer = make_param_sweep_writer()
    assert writer.concat_dim == 1


def test_param_sweep_writer_get_single_shape():
    writer = make_param_sweep_writer()
    assert writer.single_shape == (180, 3, 160)


def test_param_sweep_writer_get_total_shape():
    writer = make_param_sweep_writer()
    assert writer.total_shape == (180, 3 * 5, 160)


def test_param_sweep_write_make_reader_errors_if_data_none():
    writer = make_param_sweep_writer()
    with pytest.raises(ValueError) as e:
        writer.make_reader()

    assert "no data has been written yet" in str(e)


def test_param_sweep_writer_reader_write_res_and_read():
    CONCAT_DIM = 1
    SWEEP_RES_SHAPE = (180, 3, 160)
    NO_OF_SWEEPS = 2
    TOTAL_SHAPE = (
        SWEEP_RES_SHAPE[0],
        SWEEP_RES_SHAPE[1] * NO_OF_SWEEPS,
        SWEEP_RES_SHAPE[2],
    )
    writer = ParamSweepWriter(
        no_of_sweeps=NO_OF_SWEEPS,
        single_shape=SWEEP_RES_SHAPE,
    )

    # Define an array that will contain data representing the fake result of two parameter
    # sweep executions.
    #
    # Two blocks will then be created from the dummy data in the array, written to the param
    # sweep store with the writer, and the result will be read from the param sweep store with
    # the reader
    data = np.arange(np.prod(SWEEP_RES_SHAPE) * NO_OF_SWEEPS, dtype=np.float32).reshape(
        TOTAL_SHAPE
    )

    # Define two blocks to write to the param sweep store
    aux_data = AuxiliaryData(np.ones(SWEEP_RES_SHAPE[0], dtype=np.float32))
    sweep_result_1 = ParamSweepBlock(
        data=data[:, : SWEEP_RES_SHAPE[CONCAT_DIM], :],
        aux_data=aux_data,
    )
    sweep_result_2 = ParamSweepBlock(
        data=data[:, SWEEP_RES_SHAPE[CONCAT_DIM] :, :],
        aux_data=aux_data,
    )

    # Write two different blocks to the param sweep store, to simulate writing the results of a
    # parameter sweep that was across two different values
    writer.write_sweep_result(sweep_result_1)
    writer.write_sweep_result(sweep_result_2)

    # Check the reader produces a block containing the middle slices from the two parameter
    # sweep results that were written to the parameter sweep store
    reader = writer.make_reader()
    block_with_middle_slices = reader.read_sweep_results()
    SWEEP_RESULT_ONE_MID_SLICE_IDX = 1
    SWEEP_RESULT_ONE_MID_SLICE = data[:, SWEEP_RESULT_ONE_MID_SLICE_IDX, :]
    SWEEP_RESULT_TWO_MID_SLICE_IDX = 4
    SWEEP_RESULT_TWO_MID_SLICE = data[:, SWEEP_RESULT_TWO_MID_SLICE_IDX, :]
    assert block_with_middle_slices.data.shape[CONCAT_DIM] == NO_OF_SWEEPS
    np.testing.assert_array_equal(
        block_with_middle_slices.data[:, 0, :], SWEEP_RESULT_ONE_MID_SLICE
    )
    np.testing.assert_array_equal(
        block_with_middle_slices.data[:, 1, :], SWEEP_RESULT_TWO_MID_SLICE
    )
