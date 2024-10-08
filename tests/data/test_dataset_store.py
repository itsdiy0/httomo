from os import PathLike
from pathlib import Path
from typing import Literal
from unittest.mock import ANY
import numpy as np
import pytest
from pytest_mock import MockerFixture
from httomo.data.dataset_store import DataSetStoreReader, DataSetStoreWriter
from mpi4py import MPI
import h5py
from httomo.runner.auxiliary_data import AuxiliaryData

from httomo.runner.dataset import DataSetBlock
from httomo.runner.dataset_store_backing import DataSetStoreBacking
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


@pytest.mark.parametrize(
    "store_backing", [DataSetStoreBacking.RAM, DataSetStoreBacking.File]
)
def test_can_write_and_read_blocks(
    tmp_path: PathLike,
    store_backing: DataSetStoreBacking,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=store_backing,
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


@pytest.mark.parametrize(
    "store_backing", [DataSetStoreBacking.RAM, DataSetStoreBacking.File]
)
def test_write_after_read_throws(
    dummy_block: DataSetBlock,
    tmp_path: PathLike,
    store_backing: DataSetStoreBacking,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=store_backing,
    )
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
        store_backing=DataSetStoreBacking.File,
    )

    writer.write_block(dummy_block)
    fileclose = mocker.patch.object(writer._h5file, "close")
    writer.finalize()

    fileclose.assert_called_once()


def test_making_reader_closes_file_and_deletes(
    dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=DataSetStoreBacking.File,
    )
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


def test_create_new_data_goes_to_file_for_file_store_backing(
    mocker: MockerFixture, dummy_block: DataSetBlock, tmp_path: PathLike
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=DataSetStoreBacking.File,
    )

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


@pytest.mark.parametrize(
    "store_backing", [DataSetStoreBacking.RAM, DataSetStoreBacking.File]
)
def test_reslice_single_block_single_process(
    dummy_block: DataSetBlock,
    tmp_path: PathLike,
    store_backing: DataSetStoreBacking,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=store_backing,
    )

    writer.write_block(dummy_block)

    expected_is_file_based = store_backing is DataSetStoreBacking.File
    assert writer.is_file_based is expected_is_file_based

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

    assert isinstance(reader, DataSetStoreReader)
    assert reader.is_file_based is expected_is_file_based

    np.testing.assert_array_equal(block.data, dummy_block.data[:, 1:3, :])
    np.testing.assert_array_equal(block.flats, dummy_block.flats)
    np.testing.assert_array_equal(block.darks, dummy_block.darks)
    np.testing.assert_array_equal(block.angles, dummy_block.angles)


@pytest.mark.mpi
@pytest.mark.skipif(
    MPI.COMM_WORLD.size != 2, reason="Only rank-2 MPI is supported with this test"
)
@pytest.mark.parametrize(
    "store_backing",
    [DataSetStoreBacking.RAM, DataSetStoreBacking.File],
)
def test_full_integration_with_reslice(
    tmp_path: PathLike,
    store_backing: DataSetStoreBacking,
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
        store_backing=store_backing,
    )

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


@pytest.mark.parametrize(
    "store_backing", [DataSetStoreBacking.RAM, DataSetStoreBacking.File]
)
def test_can_write_blocks_with_padding_and_read(
    tmp_path: PathLike,
    store_backing: DataSetStoreBacking,
):
    writer = DataSetStoreWriter(
        slicing_dim=0,
        comm=MPI.COMM_WORLD,
        temppath=tmp_path,
        store_backing=store_backing,
    )

    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    padding = (2, 3)
    core_chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_shape = (
        core_chunk_shape[0] + padding[0] + padding[1],
        core_chunk_shape[1],
        core_chunk_shape[2],
    )
    core_chunk_start = 3
    chunk_start = core_chunk_start - padding[0]
    b1shape = (2, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    b1shape_padded = (b1shape[0] + padding[0] + padding[1], b1shape[1], b1shape[2])
    b1data_padded = -np.ones(b1shape_padded, dtype=np.float32)
    b1data_padded[padding[0] : padding[0] + 2, :, :] = global_data[
        core_chunk_start : core_chunk_start + 2, :, :
    ]
    block1 = DataSetBlock(
        data=b1data_padded,
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=-padding[0],
        slicing_dim=0,
        chunk_start=chunk_start,
        padding=padding,
    )
    b2shape = b1shape
    b2shape_padded = (b2shape[0] + padding[0] + padding[1], b2shape[1], b2shape[2])
    b2data_padded = -np.ones(b2shape_padded, dtype=np.float32)
    b2data_padded[padding[0] : padding[0] + 2, :, :] = global_data[
        core_chunk_start + 2 : core_chunk_start + 2 + 2, :, :
    ]
    block2 = DataSetBlock(
        data=b2data_padded,
        aux_data=AuxiliaryData(angles=np.ones(GLOBAL_SHAPE[0], dtype=np.float32)),
        global_shape=GLOBAL_SHAPE,
        chunk_shape=chunk_shape,
        block_start=2 - padding[0],
        slicing_dim=0,
        chunk_start=chunk_start,
        padding=padding,
    )

    writer.write_block(block1)
    writer.write_block(block2)

    reader = writer.make_reader()

    rblock1 = reader.read_block(0, 2)
    rblock2 = reader.read_block(2, 2)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == core_chunk_shape
    assert reader.global_index == (core_chunk_start, 0, 0)
    assert reader.slicing_dim == 0

    assert isinstance(rblock1.data, np.ndarray)
    assert isinstance(rblock2.data, np.ndarray)

    np.testing.assert_array_equal(
        rblock1.data, global_data[core_chunk_start : core_chunk_start + 2, :, :]
    )
    np.testing.assert_array_equal(
        rblock2.data, global_data[core_chunk_start + 2 : core_chunk_start + 2 + 2, :, :]
    )


def test_can_write_and_read_padded_blocks_filebased_center(
    mocker: MockerFixture, tmp_path: PathLike
):
    padding = (2, 2)
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (4, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    chunk_start = 3

    # write global data to file and fake the source
    file = Path(tmp_path) / "testfile.h5"
    with h5py.File(file, "w") as f:
        source_data = f.create_dataset("data", data=global_data)

    mock_source = mocker.create_autospec(
        DataSetStoreWriter,
        _data=source_data,
        is_file_based=True,
        filename=file,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        global_index=(chunk_start, 0, 0),
        chunk_shape=chunk_shape,
        finalise=mocker.MagicMock(),
        instance=True,
    )

    reader = DataSetStoreReader(mock_source, 0, padding=padding)
    padded_chunk_shape = (
        chunk_shape[0] + padding[0] + padding[1],
        chunk_shape[1],
        chunk_shape[2],
    )

    rblock1 = reader.read_block(0, 2)
    rblock2 = reader.read_block(2, 2)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == padded_chunk_shape
    assert reader.global_index == (chunk_start - padding[0], 0, 0)
    assert reader.slicing_dim == 0

    assert isinstance(rblock1.data, np.ndarray)
    assert isinstance(rblock2.data, np.ndarray)

    assert rblock1.is_padded is True
    assert rblock2.is_padded is True
    assert rblock1.padding == padding
    assert rblock2.padding == padding

    np.testing.assert_array_equal(
        rblock1.data,
        global_data[chunk_start - padding[0] : chunk_start + 2 + padding[1], :, :],
    )
    np.testing.assert_array_equal(
        rblock2.data,
        global_data[chunk_start - padding[0] + 2 : chunk_start + 4 + padding[1], :, :],
    )


def test_adapts_shapes_with_padding_and_reslicing(
    mocker: MockerFixture, tmp_path: PathLike
):
    padding = (2, 2)
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = GLOBAL_SHAPE  # the writer just ignores padding

    # write global data to file and fake the source
    file = Path(tmp_path) / "testfile.h5"
    with h5py.File(file, "w") as f:
        source_data = f.create_dataset("data", data=global_data)

    mock_source = mocker.create_autospec(
        DataSetStoreWriter,
        _data=source_data,
        is_file_based=True,
        filename=file,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        global_index=(0, 0, 0),
        chunk_shape=chunk_shape,
        finalise=mocker.MagicMock(),
        instance=True,
        comm=MPI.COMM_SELF,
    )

    reader = DataSetStoreReader(mock_source, slicing_dim=1, padding=padding)

    block = reader.read_block(0, 2)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == (
        GLOBAL_SHAPE[0],
        GLOBAL_SHAPE[1] + padding[0] + padding[1],
        GLOBAL_SHAPE[2],
    )
    assert reader.global_index == (0, -padding[0], 0)
    assert reader.slicing_dim == 1

    assert block.shape == (
        GLOBAL_SHAPE[0],
        2 + padding[0] + padding[1],
        GLOBAL_SHAPE[2],
    )
    assert block.padding == padding
    assert block.chunk_shape == reader.chunk_shape
    assert block.chunk_index == (0, -padding[0], 0)
    assert block.global_index == (0, -padding[0], 0)


@pytest.mark.parametrize("boundary", ["before", "after", "both"])
def test_can_write_and_read_padded_blocks_filebased_boundaries(
    mocker: MockerFixture,
    tmp_path: PathLike,
    boundary: Literal["before", "after", "both"],
):
    padding = (2, 2)
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (
        GLOBAL_SHAPE[0] if boundary == "both" else 4,
        GLOBAL_SHAPE[1],
        GLOBAL_SHAPE[2],
    )
    chunk_start = 0 if boundary == "before" else GLOBAL_SHAPE[0] - chunk_shape[0]

    # write global data to file and fake the source
    file = Path(tmp_path) / "testfile.h5"
    with h5py.File(file, "w") as f:
        source_data = f.create_dataset("data", data=global_data)

    mock_source = mocker.create_autospec(
        DataSetStoreWriter,
        _data=source_data,
        is_file_based=True,
        filename=file,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        global_index=(chunk_start, 0, 0),
        chunk_shape=chunk_shape,
        finalise=mocker.MagicMock(),
        instance=True,
    )

    reader = DataSetStoreReader(mock_source, 0, padding=padding)
    padded_chunk_shape = (
        chunk_shape[0] + padding[0] + padding[1],
        chunk_shape[1],
        chunk_shape[2],
    )

    blck_size = chunk_shape[0] // 2
    rblock1 = reader.read_block(0, blck_size)
    rblock2 = reader.read_block(blck_size, blck_size)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == padded_chunk_shape
    assert reader.global_index == (chunk_start - padding[0], 0, 0)
    assert reader.slicing_dim == 0

    assert isinstance(rblock1.data, np.ndarray)
    assert isinstance(rblock2.data, np.ndarray)

    assert rblock1.is_padded is True
    assert rblock2.is_padded is True
    assert rblock1.padding == padding
    assert rblock2.padding == padding

    b1expected = np.zeros(
        (
            blck_size + padding[0] + padding[1],
            GLOBAL_SHAPE[1],
            GLOBAL_SHAPE[2],
        ),
        dtype=np.float32,
    )
    b2expected = np.zeros_like(b1expected)
    if boundary == "before":
        b1expected[padding[0] :, :, :] = global_data[
            chunk_start : chunk_start + blck_size + padding[1], :, :
        ]
        # repeat on left edge
        b1expected[: padding[0], :, :] = global_data[0, :, :]
        b2expected[:] = global_data[
            chunk_start
            - padding[0]
            + blck_size : chunk_start
            + 2 * blck_size
            + padding[1],
            :,
            :,
        ]
    elif boundary == "after":
        b1expected[:] = global_data[
            chunk_start - padding[0] : chunk_start + blck_size + padding[1], :, :
        ]
        b2expected[: blck_size + padding[0], :, :] = global_data[
            chunk_start - padding[0] + blck_size : chunk_start + 2 * blck_size, :, :
        ]
        # repeat on right edge
        b2expected[blck_size + padding[0] :, :, :] = global_data[-1, :, :]
    else:
        b1expected[padding[0] :, :, :] = global_data[
            chunk_start : chunk_start + blck_size + padding[1], :, :
        ]
        # repeat on left edge
        b1expected[: padding[0], :, :] = global_data[0, :, :]
        b2expected[: blck_size + padding[0], :, :] = global_data[
            chunk_start - padding[0] + blck_size : chunk_start + 2 * blck_size, :, :
        ]
        # repeat on right edge
        b2expected[blck_size + padding[0] :, :, :] = global_data[-1, :, :]

    np.testing.assert_array_equal(rblock1.data, b1expected)
    np.testing.assert_array_equal(rblock2.data, b2expected)


@pytest.mark.mpi
@pytest.mark.skipif(
    MPI.COMM_WORLD.size != 2, reason="Only rank-2 MPI is supported with this test"
)
def test_can_write_and_read_padded_blocks_ram(mocker: MockerFixture):
    comm = MPI.COMM_WORLD
    padding = (2, 2)
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (5, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    if comm.rank == 0:
        chunk_start = 0
    else:
        chunk_start = 5

    source_data = np.copy(global_data[chunk_start : chunk_start + chunk_shape[0], :, :])

    mock_source = mocker.create_autospec(
        DataSetStoreWriter,
        _data=source_data,
        is_file_based=False,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        global_index=(chunk_start, 0, 0),
        chunk_shape=chunk_shape,
        finalise=mocker.MagicMock(),
        comm=comm,
        instance=True,
    )

    reader = DataSetStoreReader(mock_source, slicing_dim=0, padding=padding)
    padded_chunk_shape = (
        chunk_shape[0] + padding[0] + padding[1],
        chunk_shape[1],
        chunk_shape[2],
    )

    b1_size = chunk_shape[0] // 2
    b2_size = chunk_shape[0] - b1_size
    rblock1 = reader.read_block(0, b1_size)
    rblock2 = reader.read_block(b1_size, b2_size)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == padded_chunk_shape
    assert reader.global_index == (chunk_start - padding[0], 0, 0)
    assert reader.slicing_dim == 0

    assert isinstance(rblock1.data, np.ndarray)
    assert isinstance(rblock2.data, np.ndarray)

    assert rblock1.is_padded is True
    assert rblock2.is_padded is True
    assert rblock1.padding == padding
    assert rblock2.padding == padding

    rb1expected = np.empty(
        (b1_size + padding[0] + padding[1], chunk_shape[1], chunk_shape[2]),
        dtype=np.float32,
    )
    rb2expected = np.empty(
        (b2_size + padding[0] + padding[1], chunk_shape[1], chunk_shape[2]),
        dtype=np.float32,
    )
    if comm.rank == 0:
        # fill left part by extrapolating
        rb1expected[: padding[0], :, :] = global_data[0, :, :]
        rb1expected[padding[0] :, :, :] = global_data[: b1_size + padding[1], :, :]
        rb2expected[:, :, :] = global_data[
            b1_size - padding[0] : b1_size + b2_size + padding[1], :, :
        ]
    elif comm.rank == 1:
        rb1expected[:, :, :] = global_data[
            chunk_shape[0] - padding[0] : chunk_shape[0] + b1_size + padding[1], :, :
        ]
        rb2expected[: -padding[1], :, :] = global_data[
            -chunk_shape[0] - padding[0] + b1_size :, :, :
        ]
        # fill right part by extrapolating
        rb2expected[-padding[1] :, :, :] = global_data[-1, :, :]

    np.testing.assert_array_equal(rblock1.data, rb1expected)
    np.testing.assert_array_equal(rblock2.data, rb2expected)


@pytest.mark.mpi
@pytest.mark.skipif(
    MPI.COMM_WORLD.size != 2, reason="Only rank-2 MPI is supported with this test"
)
def test_adapts_shapes_with_padding_and_reslicing_mpi(
    mocker: MockerFixture, tmp_path: PathLike
):
    # first, we write with 2 MPI processes in slicing_dim 0 (faking the store)
    comm = MPI.COMM_WORLD
    GLOBAL_SHAPE = (10, 10, 10)
    global_data = np.arange(np.prod(GLOBAL_SHAPE), dtype=np.float32).reshape(
        GLOBAL_SHAPE
    )
    chunk_shape = (5, GLOBAL_SHAPE[1], GLOBAL_SHAPE[2])
    if comm.rank == 0:
        chunk_start = 0
    else:
        chunk_start = 5

    source_data = np.copy(global_data[chunk_start : chunk_start + chunk_shape[0], :, :])

    mock_source = mocker.create_autospec(
        DataSetStoreWriter,
        _data=source_data,
        is_file_based=False,
        slicing_dim=0,
        global_shape=GLOBAL_SHAPE,
        global_index=(chunk_start, 0, 0),
        chunk_shape=chunk_shape,
        finalise=mocker.MagicMock(),
        comm=comm,
        instance=True,
    )

    # now we read with padding in slicing_dim=1 (reslice required)
    padding = (2, 2)
    reader = DataSetStoreReader(mock_source, slicing_dim=1, padding=padding)

    chunk_size = GLOBAL_SHAPE[1] // 2
    b1_size = chunk_size // 2
    b2_size = chunk_size - b1_size
    block1 = reader.read_block(0, b1_size)
    block2 = reader.read_block(b1_size, b2_size)

    assert reader.global_shape == GLOBAL_SHAPE
    assert reader.chunk_shape == (
        GLOBAL_SHAPE[0],
        chunk_size + padding[0] + padding[1],
        GLOBAL_SHAPE[2],
    )
    assert reader.slicing_dim == 1
    if comm.rank == 0:
        assert reader.global_index == (0, -padding[0], 0)
    else:
        assert reader.global_index == (0, chunk_size - padding[0], 0)

    assert block1.shape == (
        GLOBAL_SHAPE[0],
        b1_size + padding[0] + padding[1],
        GLOBAL_SHAPE[2],
    )
    assert block1.padding == padding
    assert block1.chunk_shape == reader.chunk_shape
    assert block1.chunk_index == (0, -padding[0], 0)
    assert block1.global_index == reader.global_index

    assert block2.shape == (
        GLOBAL_SHAPE[0],
        b2_size + padding[0] + padding[1],
        GLOBAL_SHAPE[2],
    )
    assert block2.padding == padding
    assert block2.chunk_shape == reader.chunk_shape
    assert block2.chunk_index == (0, b1_size - padding[0], 0)
    assert block2.global_index == (0, reader.global_index[1] + b1_size, 0)

    b1expected = np.empty(block1.shape, dtype=np.float32)
    b2expected = np.empty(block2.shape, dtype=np.float32)
    if comm.rank == 0:
        b1expected[:, padding[0] :, :] = global_data[:, : b1_size + padding[1], :]
        b1expected[:, : padding[0], :] = global_data[:, 0:1, :]
        b2expected[:, :, :] = global_data[
            :, b1_size - padding[0] : chunk_size + padding[1], :
        ]
    else:
        b1expected[:, :, :] = global_data[
            :, chunk_size - padding[0] : chunk_size + b1_size + padding[1], :
        ]
        b2expected[:, : -padding[1], :] = global_data[:, -b2_size - padding[0] :, :]
        b2expected[:, -padding[1] :, :] = global_data[:, -1:, :]

    np.testing.assert_array_equal(block1.data, b1expected)
    np.testing.assert_array_equal(block2.data, b2expected)
