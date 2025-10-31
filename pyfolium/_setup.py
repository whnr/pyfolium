"""Development environment setup utilities."""

import subprocess
import sys


def setup_dev_environment():
    """Set up the development environment by installing pre-commit hooks.

    This is automatically called after `uv sync` to ensure pre-commit hooks
    are installed for all developers.
    """
    print("🔧 Setting up development environment...")

    try:
        # Install pre-commit hooks
        result = subprocess.run(
            ["pre-commit", "install"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            print("✓ Pre-commit hooks installed successfully")
            print("  Ruff will now run automatically before each commit")
        else:
            print("⚠ Failed to install pre-commit hooks")
            print(f"  Error: {result.stderr}")
            sys.exit(1)

    except FileNotFoundError:
        print("⚠ pre-commit not found in PATH")
        print("  This should not happen - pre-commit is in dev dependencies")
        sys.exit(1)


if __name__ == "__main__":
    setup_dev_environment()
