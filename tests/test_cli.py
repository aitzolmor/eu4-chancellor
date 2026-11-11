import pytest

from chancellor import __version__
from chancellor.app.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_unimplemented_command_exits_nonzero(capsys):
    assert main(["summary"]) == 1
    assert "not implemented" in capsys.readouterr().err
