"""Create a venv with this interpreter, refusing to mix existing Python versions."""
import pathlib
import subprocess
import sys
import venv


def setup(path):
    target = pathlib.Path(path)
    python = target / "bin" / "python"
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    if target.exists():
        if not python.exists():
            raise SystemExit(f"{target} exists without a usable Python; choose a fresh VENV.")
        actual = subprocess.check_output(
            [str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            text=True).strip()
        if actual != expected:
            raise SystemExit(f"{target} uses Python {actual}, requested {expected}. "
                             "Choose a fresh VENV or explicitly set PYTHON to the existing version.")
        print(f"Reusing {target} with Python {actual}; pip is invoked through this interpreter.")
    else:
        venv.EnvBuilder(with_pip=True).create(target)


if __name__ == "__main__":
    setup(sys.argv[1])
