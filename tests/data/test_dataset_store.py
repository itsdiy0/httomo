from os import PathLike
from typing import List, Literal
from unittest.mock import ANY
import numpy as np
import pytest
from pytest_mock import MockerFixture
from httomo.data.dataset_store import DataSetStoreReader, DataSetStoreWriter
from mpi4py import MPI
from httomo.runner.auxiliary_data import AuxiliaryData

from httomo.runner.dataset import DataSetBlock
from httomo.utils import make_3d_shape_from_shape


@pytest.mark.parametrize("slicing_dim", [0, 1, 2])
def test_writer_can_set_sizes_and_shapes_dim(
    tmp_path: PathLike, slicing_dim: Literal[0, 1, 2]
):
    global_shape = (30, 15, 20)
    chunk_shape_t = list(global_shape)
    chunk_shape_t[slicing_dim] = 5
    chunk_shape = make_3d_shape_from_shape(chunk_shape_t)
    global_index_t = [0, 0, 0]
    global_index_t[slicing_dim] = 5
    global_index = make_3d_shape_from_shape(global_index_t)
    writer = DataSetStoreWriter(
        slicing_dim=slicing_dim,
        comm=MPI.COMM_SELF,
        temppath=tmp_path,
    )
    block = DataSetBlock(
        data=np.ones(chunk_shape, dtype=np.float32),
        aux_data=AuxiliaryData(angles=np.ones(global_shape[0], dtype=np.float32)),
        chunk_shape=chunk_shape,
        slicing_dim=slicing_dim,
        global_shape=global_shape,
        block_start=0,
        chunk_start=global_index[slicing_dim],
    )
    writer.write_block(block)

    assert writer.global_shape == global_shape
    assert writer.chunk_shape == chunk_shape
    assert writer.global_index == global_index
    assert writer.slicing_dim == slicing_dim


def test_reader_throws_if_no_data(tmp_path: PathLike):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_SELF,
        temppath=tmp_path,
    )
    with pytest.raises(ValueError) as e:
        writer.make_reader()

    assert "no data" in str(e)


@pytest.mark.parametrize("file_based", [False, True])
def test_can_write_and_read_blocks(
    mocker: MockerFixture, tmp_path: PathLike, file_based: bool
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )

    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3
    block1 = DataSetBlock(
        data=global_data[chunk_start : chunk_start + 2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=0,
        slicing_dim=0,
        chunk_start=chunk_start,
    )
    block2 = DataSetBlock(
        data=global_data[chunk_start + 2 : chunk_start + 2 + 2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=2,
        slicing_dim=0,
        chunk_start=chunk_start,
    )

    if file_based:
        mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)
    writer.write_block(block1)
    writer.write_block(block2)

    reader = writer.make_reader()

    rblock1 = reader.read_block(0, 2)
    rblock2 = reader.read_block(2, 2)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == chunk_shape
    assert reader.global_index == (chunk_start, 0, 0)
    assert reader.slicing_dim == 0

    assert isinstance(rblock1.data, np.ndarray)
    assert isinstance(rblock2.data, np.ndarray)

    np.testing.assert_array_equal(rblock1.data, block1.data)
    np.testing.assert_array_equal(rblock2.data, block2.data)


@pytest.mark.parametrize("file_based", [False, True])
def test_write_after_read_throws(
    mocker: MockerFixture,
    dummy_block: DataSetBlock,
    tmp_path: PathLike,
    file_based: bool,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )

    if file_based:
        mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)
    writer.write_block(dummy_block)

    writer.make_reader()

    with pytest.raises(ValueError):
        writer.write_block(dummy_block)


def test_writer_closes_file_on_finalize(
    mocker: MockerFixture, dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )

    mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)
    writer.write_block(dummy_block)
    fileclose = mocker.patch.object(writer._h5file, "close")
    writer.finalize()

    fileclose.assert_called_once()


def test_making_reader_closes_file_and_deletes(
    mocker: MockerFixture, dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)
    writer.write_block(dummy_block)

    reader = writer.make_reader()

    assert writer._h5file is None
    assert writer.filename is not None
    assert writer.filename.exists()
    assert isinstance(reader, DataSetStoreReader)
    assert reader.filename == writer.filename
    assert reader._h5file is not None
    assert reader._h5file.get("data", None) is not None

    reader.finalize()

    assert not writer.filename.exists()


def test_can_write_and_read_block_with_different_sizes(tmp_path: PathLike):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3
    block1 = DataSetBlock(
        data=global_data[chunk_start : chunk_start + 2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=0,
        slicing_dim=0,
        chunk_start=chunk_start,
    )
    block2 = DataSetBlock(
        data=global_data[chunk_start + 2 : chunk_start + 2 + 2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=2,
        slicing_dim=0,
        chunk_start=chunk_start,
    )

    writer.write_block(block1)
    writer.write_block(block2)

    reader = writer.make_reader()

    rblock = reader.read_block(0, 4)

    np.testing.assert_array_equal(
        rblock.data, global_data[chunk_start : chunk_start + 4, :, :]
    )


def test_writing_inconsistent_global_shapes_fails(tmp_path: PathLike):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3
    aux_data = AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0] + 10, dtype=np.float32))
    block1 = DataSetBlock(
        data=global_data[:2, :, :],
        aux_data=aux_data,
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=0,
        slicing_dim=0,
        chunk_start=chunk_start,
    )
    block2 = DataSetBlock(
        data=global_data[:2, :, :],
        aux_data=aux_data,
        global_shape=(GLOBAL_SHAPE[0] + 1, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2]),
        chunk_shape=chunk_shape,
        block_start=2,
        slicing_dim=0,
        chunk_start=chunk_start,
    )

    writer.write_block(block1)
    with pytest.raises(ValueError) as e:
        writer.write_block(block2)

    assert "inconsistent shape" in str(e)


def test_writing_inconsistent_chunk_shapes_fails(tmp_path: PathLike):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3
    block1 = DataSetBlock(
        data=global_data[:2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=0,
        slicing_dim=0,
        chunk_start=chunk_start,
    )
    block2 = DataSetBlock(
        data=global_data[2:2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=(chunk_shape[0] - 1, chunk_shape[1], chunk_shape[2]),
        block_start=2,
        slicing_dim=0,
        chunk_start=chunk_start,
    )

    writer.write_block(block1)
    with pytest.raises(ValueError) as e:
        writer.write_block(block2)

    assert "inconsistent shape" in str(e)


def test_writing_inconsistent_global_index_fails(tmp_path: PathLike):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3
    block1 = DataSetBlock(
        data=global_data[:2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=0,
        slicing_dim=0,
        chunk_start=chunk_start,
    )
    block2 = DataSetBlock(
        data=global_data[2:2, :, :],
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=2,
        slicing_dim=0,
        chunk_start=chunk_start + 2,
    )

    writer.write_block(block1)
    with pytest.raises(ValueError) as e:
        writer.write_block(block2)

    assert "inconsistent shape" in str(e)


def test_create_new_data_goes_to_file_on_memory_error(
    mocker: MockerFixture, dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )

    mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)
    createh5_mock = mocker.patch.object(
        writer, "_create_h5_data", return_value=dummy_block.data
    )

    writer.write_block(dummy_block)

    createh5_mock.assert_called_with(
        writer.global_shape,
        dummy_block.data.dtype,
        ANY,
        writer.comm,
    )


def test_create_new_data_goes_to_file_on_memory_limit(
    mocker: MockerFixture, tmp_path: PathLike
):
    GLOBAL_SHAPE = (500, 10, 10)
    data = np.ones(GLOBAL_SHAPE, dtype=np.float32)
    aux_data = AuxiliaryData(
        angles=np.ones(data.shape[0], dtype=np.float32),
        darks=2.0 * np.ones((2, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2]), dtype=np.float32),
        flats=1.0 * np.ones((2, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2]), dtype=np.float32),
    )
    block = DataSetBlock(
        data=data[0:2, :, :],
        aux_data=aux_data,
        slicing_dim=0,
        block_start=0,
        chunk_start=0,
        global_shape=GLOBAL_SHAPE,
        chunk_shape=GLOBAL_SHAPE,
    )
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        memory_limit_bytes=block.data.nbytes + 5,  # only one block will fit in memory
    )

    createh5_mock = mocker.patch.object(
        writer, "_create_h5_data", return_value=block.data
    )

    writer.write_block(block)

    createh5_mock.assert_called_with(
        writer.global_shape,
        block.data.dtype,
        ANY,
        writer.comm,
    )


def test_calls_reslice(
    mocker: MockerFixture, dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )

    writer.write_block(dummy_block)

    reslice_mock = mocker.patch.object(DataSetStoreReader, "_reslice")
    d = writer._data
    writer.make_reader(new_slicing_dim=1)

    reslice_mock.assert_called_with(0, 1, d)


@pytest.mark.parametrize("file_based", [False, True])
def test_reslice_single_block_single_process(
    mocker: MockerFixture,
    dummy_block: DataSetBlock,
    tmp_path: PathLike,
    file_based: bool,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
    )
    if file_based:
        mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)

    writer.write_block(dummy_block)

    assert writer.is_file_based is file_based

    reader = writer.make_reader(new_slicing_dim=1)

    block = reader.read_block(1, 2)

    assert reader.slicing_dim == 1
    assert reader.global_shape == writer.global_shape
    assert reader.chunk_shape == writer.chunk_shape
    assert reader.global_index == (0, 0, 0)

    assert block.global_shape == reader.global_shape
    assert block.shape == (reader.global_shape[0], 2, reader.global_shape[2])
    assert block.chunk_index == (0, 1, 0)
    assert block.chunk_shape == reader.chunk_shape

    assert reader.is_file_based is file_based

    np.testing.assert_array_equal(block.data, dummy_block.data[:, 1:3, :])
    np.testing.assert_array_equal(block.flats, dummy_block.flats)
    np.testing.assert_array_equal(block.darks, dummy_block.darks)
    np.testing.assert_array_equal(block.angles, dummy_block.angles)


@pytest.mark.mpi
@pytest.mark.skipif(
    MPI.COMM_WORLD.size != 2, reason="Only rank-2 MPI is supported with this test"
)
@pytest.mark.parametrize(
    "out_of_memory_ranks",
    [[], [1], [0, 1]],
    ids=[
        "out_of_memory=none",
        "out_of_memory=one process",
        "out_of_memory=both processes",
    ],
)
def test_full_integration_with_reslice(
    mocker: MockerFixture,
    tmp_path: PathLike,
    out_of_memory_ranks: List[int],
):
    ########### ARRANGE DATA and mocks

    GLOBAL_DATA_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_DATA_SHAPE), dtype=np.float32).reshape(
        GLOBAL_DATA_SHAPE
    )
    angles = np.ones(GLOBAL_DATA_SHAPE[0], dtype=np.float32)
    flats = 3 * np.ones((5, 10, 10), dtype=np.float32)
    darks = 2 * np.ones((5, 10, 10), dtype=np.float32)
    aux_data = AuxiliaryData(angles=angles, flats=flats, darks=darks)
    comm = MPI.COMM_WORLD
    assert comm.size == 2

    # start idx and size in slicing dim 0 for the writer
    chunk_start = 0 if comm.rank == 0 else GLOBAL_DATA_SHAPE[0] // 2
    chunk_size = GLOBAL_DATA_SHAPE[0] // 2

    block = DataSetBlock(
        data=global_data[chunk_start : chunk_start + chunk_size, :, :],
        aux_data=aux_data,
        global_shape=GLOBAL_DATA_SHAPE,
        block_start=0,
        chunk_start=chunk_start,
        chunk_shape=(chunk_size, GLOBAL_DATA_SHAPE[1], GLOBAL_DATA_SHAPE[2]),
    )

    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=comm,
        temppath=tmp_path,
    )

    if comm.rank in out_of_memory_ranks:
        # make it throw an exception, so it reverts to file-based store
        mocker.patch.object(writer, "_create_numpy_data", side_effect=MemoryError)

    ############# ACT

    # write full chunk-sized block
    writer.write_block(block)
    reader = writer.make_reader(new_slicing_dim=1)
    # read a smaller block, starting at index 1
    block = reader.read_block(1, 2)

    ############ ASSERT

    assert reader.slicing_dim == 1
    assert reader.global_shape == GLOBAL_DATA_SHAPE
    assert reader.global_shape == writer.global_shape
    assert reader.chunk_shape == (
        GLOBAL_DATA_SHAPE[0],
        GLOBAL_DATA_SHAPE[1] // 2,
        GLOBAL_DATA_SHAPE[2],
    )
    assert block.global_shape == reader.global_shape
    assert block.shape == (GLOBAL_DATA_SHAPE[0], 2, GLOBAL_DATA_SHAPE[2])
    assert block.chunk_index == (0, 1, 0)
    assert block.chunk_shape == reader.chunk_shape

    np.testing.assert_array_equal(block.flats, flats)
    np.testing.assert_array_equal(block.darks, darks)
    np.testing.assert_array_equal(block.angles, angles)

    if comm.rank == 0:
        assert writer.global_index == (0, 0, 0)
        assert reader.global_index == (0, 0, 0)
        np.testing.assert_array_equal(block.data, global_data[:, 1:3, :])
    elif comm.rank == 1:
        assert writer.global_index == (GLOBAL_DATA_SHAPE[0] // 2, 0, 0)
        assert reader.global_index == (0, GLOBAL_DATA_SHAPE[1] // 2, 0)
        np.testing.assert_array_equal(
            block.data,
            global_data[
                :, GLOBAL_DATA_SHAPE[1] // 2 + 1 : GLOBAL_DATA_SHAPE[1] // 2 + 3, :
            ],
        )
