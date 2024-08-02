import logging
import pathlib
from typing import Tuple, Union
import numpy as np
import h5py
import hdf5plugin
import zarr
from zarr import storage
from mpi4py import MPI

import httomo
from httomo import globals
from httomo.runner.dataset import DataSetBlock
from httomo.utils import log_once, xp

__all__ = ["calculate_stats", "save_intermediate_data"]

# save a copy of the original guess_chunk if it needs to be restored
ORIGINAL_GUESS_CHUNK = h5py._hl.filters.guess_chunk

def calculate_stats(
    data: np.ndarray,
) -> Tuple[float, float, float, int]:
    """Calculating the statistics of the given array

    Args:
        data: (np.ndarray): a numpy array

    Returns:
        tuple[(float, float, float, int)]: (min, max, sum, total_elements)
    """

    # do this whereever the data is at the moment (GPU/CPU)
    if getattr(data, "device", None) is not None:
        # GPU
        data = xp.nan_to_num(data, copy=False, nan=0.0, posinf=0, neginf=0)
    else:
        # CPU
        data = np.nan_to_num(data, copy=False, nan=0.0, posinf=0, neginf=0)

    return (float(data.min()), float(data.max()), float(data.sum()), data.size)


def save_intermediate_data(
    data: np.ndarray,
    global_shape: Tuple[int, int, int],
    global_index: Tuple[int, int, int],
    slicing_dim: int,
    file: Union[h5py.File, zarr.DirectoryStore],
    frames_per_chunk: int,
    path: str,
    detector_x: int,
    detector_y: int,
    angles: np.ndarray,
) -> None:
    """Saves intermediate data to a file, including auxiliary"""
    if frames_per_chunk > data.shape[slicing_dim]:
        warn_message = (
            f"frames_per_chunk={frames_per_chunk} exceeds number of elements in "
            f"slicing dim={slicing_dim} of data with shape {data.shape}. Falling "
            "back to 1 frame per-chunk"
        )
        log_once(warn_message, logging.DEBUG)
        frames_per_chunk = 1

    if frames_per_chunk > 0:
        chunk_shape = [0, 0, 0]
        chunk_shape[slicing_dim] = frames_per_chunk
        DIMS = [0, 1, 2]
        non_slicing_dims = list(set(DIMS) - set([slicing_dim]))
        for dim in non_slicing_dims:
            chunk_shape[dim] = global_shape[dim]
        chunk_shape = tuple(chunk_shape)
    else:
        chunk_shape = None

    dataset: Union[h5py.Dataset, zarr.Array]
    if isinstance(file, h5py.File):
        _save_auxiliary_data_hdf5(file, angles, detector_x, detector_y)

        # monkey-patch guess_chunk in h5py for compression
        # this is to avoid FILL_TIME_ALLOC
        compression: Union[dict, hdf5plugin.Blosc]
        if httomo.globals.COMPRESS_INTERMEDIATE:
            compression = hdf5plugin.Blosc()
            h5py._hl.filters.guess_chunk = lambda *args, **kwargs: None
        else:
            compression = {}
            h5py._hl.filters.guess_chunk = ORIGINAL_GUESS_CHUNK

        # create a dataset creation property list
        if chunk_shape is not None: 
            dcpl = _dcpl_fill_never(chunk_shape, global_shape)
        else:
            dcpl = None

        # only create if not already present - otherwise return existing dataset
        dataset = file.require_dataset(
            path,
            global_shape,
            data.dtype,
            exact=True,
            chunks=None, # set in dcpl
            **compression,
            dcpl=dcpl,
        )
    else:
        _save_auxiliary_data_zarr(file, angles, detector_x, detector_y)
        dataset = zarr.open_array(
            store=file,
            path=path,
            shape=global_shape,
            chunks=chunk_shape,  # type: ignore
            dtype=data.dtype,
            compressor=(
                storage.default_compressor
                if httomo.globals.COMPRESS_INTERMEDIATE
                else None
            ),  # type: ignore
        )        

    _save_dataset_data(dataset, data, global_shape, global_index)


def _save_dataset_data(
    dataset: Union[h5py.Dataset, zarr.Array],
    data: np.ndarray,
    global_shape: Tuple[int, int, int],
    global_index: Tuple[int, int, int],
):
    start = np.array(global_index)
    stop = start + np.array(data.shape)
    assert getattr(data, "device", None) is None, "data must be on CPU for saving"
    assert stop[0] <= dataset.shape[0]
    assert stop[1] <= dataset.shape[1]
    assert stop[2] <= dataset.shape[2]
    assert dataset.shape == global_shape
    if isinstance(dataset, h5py.Dataset) and httomo.globals.COMPRESS_INTERMEDIATE:
        # Write operations must be collective when applying compression, see
        # https://github.com/h5py/h5py/issues/1564
        with dataset.collective:
            dataset[start[0] : stop[0], start[1] : stop[1], start[2] : stop[2]] = data
        return

    dataset[start[0] : stop[0], start[1] : stop[1], start[2] : stop[2]] = data


def _save_auxiliary_data_hdf5(
    file: h5py.File,
    angles: np.ndarray,
    detector_x: int,
    detector_y: int,
):
    # only save if not there yet
    if "/angles" in file:
        return

    file.create_dataset("angles", data=angles)

    file_name = pathlib.Path(file.filename).name
    file.create_dataset(file_name, data=[0, 0])
    g1 = file.create_group("data_dims")
    g1.create_dataset("detector_x_y", data=[detector_x, detector_y])


def _save_auxiliary_data_zarr(
    store: zarr.DirectoryStore,
    angles: np.ndarray,
    detector_x: int,
    detector_y: int,
):
    comm = MPI.COMM_WORLD
    if comm.rank != 0:
        return

    zarr.save(store=store, path="angles", data=angles)
    zarr.save(
        store=store, path="detector_x_y", detector_x=detector_x, detector_y=detector_y
    )


def _dcpl_fill_never(
    chunk_shape: Tuple[int, int, int],
    shape: Tuple[int, int, int],
) -> h5py.h5p.PropDCID:
    """Create a dcpl with specified chunk shape and never fill value."""
    # validate chunk shape (basically a copy from h5py)
    if isinstance(chunk_shape, int) and not isinstance(chunk_shape, bool):
        chunk_shape = (chunk_shape,)
    if isinstance(chunk_shape, tuple) and any(
            chunk > dim for dim, chunk in zip(shape, chunk_shape)
            if dim is not None):
        errmsg = ("Chunk shape must not be greater than data shape in any "
                  f"dimension. {chunk_shape} is not compatible with {shape}."
                  )
        raise ValueError(errmsg)

    # dcpl initialisation
    dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)

    dcpl.set_chunk(chunk_shape)

    # we are not going to resize the dataset
    dcpl.set_fill_time(h5py.h5d.FILL_TIME_NEVER)

    return dcpl
