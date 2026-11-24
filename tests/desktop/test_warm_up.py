"""The first-start warm-up: setup imports every module once, so the first real start is fast."""

import json

from spyglass_service.desktop.warm_up import warm_up_modules


def test_warm_up_loads_every_module_of_the_packages() -> None:
    summary = warm_up_modules(packages=("json",))
    assert summary.startswith("Loaded ")
    assert "Not loaded: none" in summary
    assert json.decoder is not None


def test_warm_up_names_a_module_that_fails_to_load(tmp_path, monkeypatch) -> None:
    package = tmp_path / "warmpkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "broken.py").write_text("raise RuntimeError('no')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    summary = warm_up_modules(packages=("warmpkg",))
    assert "warmpkg.broken" in summary
