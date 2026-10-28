"""Registers every background job handler and exposes the active container to them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.jobs import JobRunner

if TYPE_CHECKING:
    from app.container import Container

_container: Container | None = None


def set_container(c: Container) -> None:
    global _container
    _container = c


def current_container() -> Container:
    assert _container is not None, "container not initialised"
    return _container


def register_all(runner: JobRunner) -> None:
    from app.services.exports import export_job
    from app.services.scene.versions import build_scene_job, scene_command_job
    from app.services.sketch.versions import (
        generate_sketch_job,
        previews_job,
        sketch_edit_job,
    )
    from app.services.statements import process_statement_job

    runner.register("statement.process", process_statement_job)
    runner.register("sketch.generate", generate_sketch_job)
    runner.register("sketch.edit", sketch_edit_job)
    runner.register("sketch.previews", previews_job)
    runner.register("scene.build", build_scene_job)
    runner.register("scene.command", scene_command_job)
    runner.register("export.create", export_job)
