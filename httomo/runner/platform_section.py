from typing import Iterator, List

import mpi4py
from httomo.runner.pipeline import Pipeline
from httomo.utils import Colour, Pattern, log_once
from httomo.runner.backend_wrapper import BackendWrapper


class PlatformSection:
    """Represents on section of a pipeline that can be executed on the same platform,
    and has the same dataset pattern."""

    def __init__(
        self,
        gpu: bool,
        pattern: Pattern,
        reslice: bool,
        max_slices: int,
        methods: List[BackendWrapper],
        save_result: bool = False
    ):
        self.gpu = gpu
        self.pattern = pattern
        self.reslice = reslice
        self.max_slices = max_slices
        self.methods = methods
        self.save_result = save_result

    def __iter__(self) -> Iterator[BackendWrapper]:
        return iter(self.methods)

    def __len__(self) -> int:
        return len(self.methods)

    def __getitem__(self, idx: int) -> BackendWrapper:
        return self.methods[idx]


def sectionize(pipeline: Pipeline, save_all: bool = False) -> List[PlatformSection]:
    sections: List[PlatformSection] = []

    # The functions below are internal to reduce duplication

    def should_save_after(method: BackendWrapper) -> bool:
        if method.config_params.get("save_result"):
            try:
                method._config_params.pop("save_result")
            except:
                pass
            return True
        if save_all:
            return True
        else:
            return False

    def needs_global_input(method: BackendWrapper) -> bool:
        return method.config_params.get("glob_stats", False)

    def is_pattern_compatible(a: Pattern, b: Pattern) -> bool:
        return a == Pattern.all or b == Pattern.all or a == b

    # loop carried variables, to build up the sections
    current_gpu: bool = False
    current_pattern: Pattern = pipeline.loader_pattern
    current_methods: List[BackendWrapper] = []
    save_previous_result: bool = False

    def finish_section(needs_reslice=False, should_save_after=False):
        if len(current_methods) > 0:
            sections.append(
                PlatformSection(
                    current_gpu,
                    current_pattern,
                    needs_reslice,
                    0,
                    current_methods,
                    save_result=should_save_after,
                )
            )

    for i, method in enumerate(pipeline):
        pattern_changed = not is_pattern_compatible(current_pattern, method.pattern)
        platform_changed = method.is_gpu != current_gpu
        start_main_pipeline = i == pipeline.main_pipeline_start
        global_input = needs_global_input(method)
        start_new_section = (
            global_input
            or save_previous_result
            or pattern_changed
            or platform_changed
            or start_main_pipeline
        )

        if start_new_section:
            finish_section(pattern_changed, save_previous_result or global_input)
            current_gpu = method.is_gpu
            if method.pattern != Pattern.all:
                current_pattern = method.pattern
            current_methods = [method]
        else:
            current_methods.append(method)
            if current_pattern == Pattern.all:
                current_pattern = method.pattern
        save_previous_result = should_save_after(method)

    finish_section(should_save_after=save_previous_result)

    _backpropagate_section_patterns(pipeline, sections)
    _finalize_patterns(pipeline, sections)
    _set_method_patterns(sections)

    return sections


def _backpropagate_section_patterns(
    pipeline: Pipeline, sections: List[PlatformSection]
):
    """Performs a backward sweep through the patterns of each section, propagating
    from the last section backwards in case the previous ones have Pattern.all.
    This makes sure the loader eventually gets the pattern that the section that follows
    has.

    Only special case: All methods have Pattern.all, which is handled separately
    """
    last_pattern = Pattern.all
    for s in reversed(sections):
        if s.pattern == Pattern.all:
            s.pattern = last_pattern
        last_pattern = s.pattern
    if pipeline.loader_pattern == Pattern.all:
        pipeline.loader_pattern = last_pattern
    elif pipeline.loader_pattern != last_pattern:
        pipeline.loader_reslice = True


def _finalize_patterns(
    pipeline: Pipeline,
    sections: List[PlatformSection],
    default_pattern=Pattern.projection,
):
    # final possible ambiguity: everything is Pattern.all -> pick projection by default
    if len(sections) > 0 and sections[0].pattern == Pattern.all:
        log_once(
            "All pipeline sections support all patterns: choosing projection",
            mpi4py.MPI.COMM_WORLD,
            Colour.YELLOW,
            level=2,
        )
        for s in sections:
            s.pattern = default_pattern
        pipeline.loader_pattern = default_pattern

    assert all(s.pattern != Pattern.all for s in sections)
    assert pipeline.loader_pattern != Pattern.all


def _set_method_patterns(sections: List[PlatformSection]):
    for s in sections:
        for m in s:
            m.pattern = s.pattern