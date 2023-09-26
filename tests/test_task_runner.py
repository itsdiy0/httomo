from unittest import mock
import pytest
import numpy as np

from httomo.task_runner import (
    MethodFunc,
    PlatformSection,
    _update_max_slices,
    _determine_platform_sections,
)
from httomo.utils import Pattern


def _dummy():
    pass


def make_test_method(
    gpu=False,
    is_loader=False,
    pattern=Pattern.projection,
    module_name="testmodule",
    wrapper_function=None,
    calc_max_slices=None,
):
    return MethodFunc(
        cpu=not gpu,
        gpu=gpu,
        is_loader=is_loader,
        module_name=module_name,
        pattern=pattern,
        method_func=_dummy,
        wrapper_func=wrapper_function,
        calc_max_slices=calc_max_slices,
    )


def test_determine_platform_sections_single() -> None:
    methods = [make_test_method(is_loader=True, module_name="testloader")]
    sections = _determine_platform_sections(methods, save_all=False)

    assert len(sections) == 1
    s0 = sections[0]
    assert s0.gpu is False
    assert s0.methods == methods
    assert s0.pattern == methods[0].pattern


def test_determine_platform_sections_two_cpu() -> None:
    methods = [
        make_test_method(is_loader=True, module_name="testloader"),
        make_test_method(),
    ]
    sections = _determine_platform_sections(methods, save_all=False)

    assert len(sections) == 1
    s0 = sections[0]
    assert s0.gpu is False
    assert s0.methods == methods
    assert s0.pattern == methods[0].pattern


def test_determine_platform_sections_pattern_change() -> None:
    methods = [
        make_test_method(
            is_loader=True, module_name="testloader", pattern=Pattern.projection
        ),
        make_test_method(pattern=Pattern.sinogram),
    ]
    sections = _determine_platform_sections(methods, save_all=False)

    assert len(sections) == 2
    s0 = sections[0]
    assert s0.gpu is False
    assert s0.methods == [methods[0]]
    assert s0.pattern == methods[0].pattern
    s1 = sections[1]
    assert s1.gpu is False
    assert s1.methods == [methods[1]]
    assert s1.pattern == methods[1].pattern


def test_determine_platform_sections_platform_change() -> None:
    methods = [
        make_test_method(is_loader=True, module_name="testloader"),
        make_test_method(gpu=True),
    ]
    sections = _determine_platform_sections(methods, save_all=False)

    assert len(sections) == 2
    s0 = sections[0]
    assert s0.gpu is False
    assert s0.methods == [methods[0]]
    assert s0.pattern == methods[0].pattern
    s1 = sections[1]
    assert s1.gpu is True
    assert s1.methods == [methods[1]]
    assert s1.pattern == methods[1].pattern


@pytest.mark.parametrize(
    "pattern1, pattern2, expected",
    [
        (Pattern.projection, Pattern.all, Pattern.projection),
        (Pattern.all, Pattern.projection, Pattern.projection),
        (Pattern.sinogram, Pattern.all, Pattern.sinogram),
        (Pattern.all, Pattern.sinogram, Pattern.sinogram),
        (Pattern.all, Pattern.all, Pattern.all),
    ],
    ids=[
        "proj-all-proj",
        "all-proj-proj",
        "sino-all-sino",
        "all-sino-sino",
        "all-all-all",
    ],
)
def test_determine_platform_sections_pattern_all_combine(
    pattern1: Pattern, pattern2: Pattern, expected: Pattern
) -> None:
    methods = [
        make_test_method(pattern=pattern1, is_loader=True, module_name="testloader"),
        make_test_method(pattern=pattern2),
    ]
    sections = _determine_platform_sections(methods, save_all=False)

    assert len(sections) == 1
    s0 = sections[0]
    assert s0.gpu is False
    assert s0.methods == methods
    assert s0.pattern == expected


def test_platform_section_max_slices():
    data_shape = (1000, 24, 42)
    dict_datasets_pipeline={}
    dict_datasets_pipeline['tomo'] = np.float32(np.zeros(data_shape))
    section = PlatformSection(
        gpu=True,
        pattern=Pattern.projection,        
        reslice=False,
        max_slices=0,
        methods=[
            make_test_method(
                pattern=Pattern.projection, gpu=True, calc_max_slices=[{'datasets': ['tomo']}, {'multipliers': [1]}, {'methods': ['direct']}]
            ),
            make_test_method(
                pattern=Pattern.projection, gpu=True, calc_max_slices=[{'datasets': ['tomo']}, {'multipliers': [1]}, {'methods': ['direct']}]
            ),
            make_test_method(
                pattern=Pattern.projection, gpu=True, calc_max_slices=[{'datasets': ['tomo']}, {'multipliers': [1]}, {'methods': ['direct']}]
            ),
        ],
    )
    with mock.patch(
        "httomo.task_runner._get_available_gpu_memory", return_value=100000
    ):
        output_dims,dtype = _update_max_slices(section, 0, data_shape, np.float32(), dict_datasets_pipeline)

    assert output_dims == data_shape
    assert dtype == np.float32()