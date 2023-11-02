import pytest
from pytest_mock import MockerFixture
from httomo.runner.pipeline import Pipeline
from httomo.runner.platform_section import sectionize
from httomo.utils import Pattern
from tests.runner.testing_utils import make_test_loader, make_test_method

def test_determine_single_method(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[make_test_method(mocker, method_name="testmethod")],
    )
    s = sectionize(p, False)
    assert len(s) == 1
    assert s[0].methods[0].method_name == "testmethod"


def test_sectionizer_can_iterate_saveall(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, method_name=f"testmethod{i}") for i in range(3)
        ],
    )

    s = sectionize(p, True)
    assert len(s) == 3
    methodnames = [m.methods[0].method_name for m in s]
    assert methodnames == ["testmethod0", "testmethod1", "testmethod2"]


def test_sectionizer_two_cpu(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, pattern=Pattern.projection),
            make_test_method(mocker, pattern=Pattern.projection),
        ],
    )
    s = sectionize(p, False)
    assert len(s) == 1
    s0 = s[0]
    assert len(s0) == 2
    assert s0.pattern == Pattern.projection


def test_sectionizer_pattern_change(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, pattern=Pattern.projection),
            make_test_method(mocker, pattern=Pattern.sinogram),
        ],
    )
    s = sectionize(p, False)
    assert len(s) == 2
    s0 = s[0]
    assert len(s0) == 1
    assert s0.pattern == Pattern.projection
    s1 = s[1]
    assert len(s1) == 1
    assert s1.pattern == Pattern.sinogram


def test_sectionizer_platform_change(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, gpu=True),
            make_test_method(mocker, gpu=False),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 2
    s0 = s[0]
    assert len(s0) == 1
    assert s0.gpu is True
    s1 = s[1]
    assert len(s1) == 1
    assert s1.gpu is False


@pytest.mark.parametrize(
    "loader_pattern, pattern1, pattern2, expected",
    [
        (Pattern.all, Pattern.projection, Pattern.all, Pattern.projection),
        (Pattern.all, Pattern.all, Pattern.projection, Pattern.projection),
        (Pattern.all, Pattern.sinogram, Pattern.all, Pattern.sinogram),
        (Pattern.all, Pattern.all, Pattern.sinogram, Pattern.sinogram),
        (Pattern.all, Pattern.all, Pattern.all, Pattern.projection),
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
    mocker: MockerFixture,
    loader_pattern: Pattern,
    pattern1: Pattern,
    pattern2: Pattern,
    expected: Pattern,
):
    loader = make_test_loader(mocker, loader_pattern)
    p = Pipeline(
        loader=loader,
        methods=[
            make_test_method(mocker, pattern=pattern1),
            make_test_method(mocker, pattern=pattern2),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 1
    s0 = s[0]
    assert s0.gpu is False
    assert len(s0) == 2
    assert s0.pattern == expected
    assert loader.pattern == expected


def test_sectionizer_save_result_triggers_new_section(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, pattern=Pattern.projection, save_result=True),
            make_test_method(mocker, pattern=Pattern.projection),
            make_test_method(mocker, pattern=Pattern.projection, save_result=True),
            make_test_method(mocker, pattern=Pattern.projection),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 3
    assert len(s[0]) == 1
    assert len(s[1]) == 2
    assert len(s[2]) == 1


def test_sectionizer_global_stats_triggers_new_section(mocker: MockerFixture):
    p = Pipeline(
        loader=make_test_loader(mocker),
        methods=[
            make_test_method(mocker, pattern=Pattern.projection, glob_stats=True),
            make_test_method(mocker, pattern=Pattern.projection),
            make_test_method(mocker, pattern=Pattern.projection, glob_stats=True),
            make_test_method(mocker, pattern=Pattern.projection),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 3
    assert len(s[0]) == 1
    assert len(s[1]) == 2
    assert len(s[2]) == 1


@pytest.mark.parametrize(
    "pattern1,pattern2,needs_reslice",
    [
        (Pattern.projection, Pattern.projection, False),
        (Pattern.projection, Pattern.all, False),
        (Pattern.all, Pattern.projection, False),
        (Pattern.sinogram, Pattern.sinogram, False),
        (Pattern.sinogram, Pattern.all, False),
        (Pattern.all, Pattern.sinogram, False),
        (Pattern.projection, Pattern.sinogram, True),
        (Pattern.sinogram, Pattern.projection, True),
    ],
    ids=[
        "proj-proj",
        "proj-all",
        "all-proj",
        "sino-sino",
        "sino-all",
        "all-sino",
        "proj-sino",
        "sino-proj",
    ],
)
def test_sectionizer_needs_reslice(
    mocker: MockerFixture, pattern1: Pattern, pattern2: Pattern, needs_reslice: bool
):
    loader = make_test_loader(mocker)
    p = Pipeline(
        loader=loader,
        methods=[
            make_test_method(mocker, pattern=pattern1, gpu=True),
            make_test_method(mocker, pattern=pattern2, gpu=False),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 2
    assert s[0].reslice == needs_reslice
    assert s[1].reslice is False
    assert loader.pattern == s[0].pattern


@pytest.mark.parametrize(
    "pattern",
    [Pattern.projection, Pattern.sinogram, Pattern.all],
    ids=["proj", "sino", "all"],
)
def test_sectionizer_inherits_pattern_from_before_if_all(
    mocker: MockerFixture, pattern: Pattern
):
    loader = make_test_loader(mocker, Pattern.projection)
    p = Pipeline(
        loader=loader,
        methods=[
            make_test_method(mocker, pattern=pattern, gpu=True),
            make_test_method(mocker, pattern=Pattern.all, gpu=False),
        ],
    )

    s = sectionize(p, False)
    assert len(s) == 2
    assert s[0].reslice is False
    assert s[1].reslice is False
    assert (
        s[1].pattern == Pattern.projection
        if pattern == Pattern.all
        else pattern
    )


@pytest.mark.parametrize("loader_pattern", [Pattern.projection, Pattern.sinogram])
def test_sectionizer_inherits_loader_pattern(
    mocker: MockerFixture, loader_pattern: Pattern
):
    p = Pipeline(
        loader=make_test_loader(mocker, pattern=loader_pattern),
        methods=[make_test_method(mocker, pattern=Pattern.all, gpu=True)],
    )

    s = sectionize(p, False)
    assert len(s) == 1
    assert s[0].reslice is False
    assert s[0].pattern == loader_pattern


def test_sectionizer_sets_reslice_in_loader(mocker: MockerFixture):
    loader = make_test_loader(mocker, pattern=Pattern.sinogram)
    p = Pipeline(
        loader=loader,
        methods=[make_test_method(mocker, pattern=Pattern.projection, gpu=True)],
    )

    s = sectionize(p, False)
    assert len(s) == 1
    assert s[0].reslice is False
    assert loader.pattern == Pattern.sinogram
    assert loader.reslice is True
