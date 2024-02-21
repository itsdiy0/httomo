import subprocess
import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from httomo import __version__
from httomo.cli import transform_limit_str_to_bytes


def test_cli_version_shows_version():
    cmd = [sys.executable, "-m", "httomo", "--version"]
    assert __version__ == subprocess.check_output(cmd).decode().strip()


def test_cli_help_shows_help():
    cmd = [sys.executable, "-m", "httomo", "--help"]
    assert (
        subprocess.check_output(cmd)
        .decode()
        .strip()
        .startswith("Usage: python -m httomo")
    )

"""
# TODO possibly re-enable after yaml checker is complete
def test_cli_noargs_raises_error():
    cmd = [sys.executable, "-m", "httomo"]
    try:
        subprocess.check_output(cmd)
    except subprocess.CalledProcessError as e:
        assert e.returncode == 2
"""

"""
def test_cli_check_pass_data_file(standard_loader, standard_data):
    cmd = [sys.executable, "-m", "httomo", "check", standard_loader, standard_data]
    check_data_str = (
        "Checking that the paths to the data and keys in the YAML_CONFIG file "
        "match the paths and keys in the input file (IN_DATA)..."
    )
    assert check_data_str in subprocess.check_output(cmd).decode().strip()
"""

"""
def test_cli_pass_output_folder(
    standard_data, standard_loader, testing_pipeline, merge_yamls, output_folder
):
    merge_yamls(standard_loader, testing_pipeline)
    output_dir = "output_dir"  # dir created by the `output_folder` fixture
    httomo_output_dir = "test-output"  # subdir that should be created by httomo
    custom_output_dir = Path(output_dir, httomo_output_dir)
    cmd = [
        sys.executable,
        "-m",
        "httomo",
        "run",
        "--output-folder",
        httomo_output_dir,
        standard_data,
        "temp.yaml",
        output_dir,
    ]
    subprocess.check_output(cmd)
    assert Path(custom_output_dir, "user.log").exists()
"""

@pytest.mark.cupy
def test_cli_pass_gpu_id(cmd, standard_data, standard_loader, output_folder):
    cmd.insert(4, standard_data)
    cmd.insert(5, standard_loader)
    cmd.insert(6, output_folder)
    cmd.insert(7, "--gpu-id")
    cmd.insert(8, "100")

    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert "GPU Device not available for access." in result.stderr


@pytest.mark.parametrize("cli_parameter,limit_bytes", [
    ("0", 0),
    ("500", 500),
    ("500k", 500 * 1024),
    ("1M",  1024*1024),
    ("1m",  1024*1024),
    ("3g", 3 * 1024**3),
    ("3.2g", int(3.2 * 1024**3))
])
def test_cli_transforms_memory_limits(cli_parameter: str, limit_bytes: int):
    assert transform_limit_str_to_bytes(cli_parameter) == limit_bytes
    

@pytest.mark.parametrize("cli_parameter", [
    "abcd", "nolimit", "124A", "23ki"
])
def test_cli_fails_transforming_memory_limits(cli_parameter: str):
    with pytest.raises(ValueError) as e:
        transform_limit_str_to_bytes(cli_parameter)
        
    assert f"invalid memory limit string {cli_parameter}" in str(e)