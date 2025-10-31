Installation
============

Requirements
------------

* Python 3.12 or higher
* uv package manager (recommended) or pip

Using uv (Recommended)
----------------------

`uv <https://github.com/astral-sh/uv>`_ is a fast, modern Python package manager that we recommend for development.

Install uv:

.. code-block:: bash

   curl -LsSf https://astral.sh/uv/install.sh | sh

Clone the repository and install dependencies:

.. code-block:: bash

   git clone https://github.com/yourusername/pyfolium.git
   cd pyfolium
   uv sync

This will create a virtual environment and install all dependencies including dev dependencies.

Using pip
---------

If you prefer using pip:

.. code-block:: bash

   git clone https://github.com/yourusername/pyfolium.git
   cd pyfolium
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"

Development Setup
-----------------

For contributors, install pre-commit hooks:

.. code-block:: bash

   uv run pre-commit install

This will run code quality checks (ruff, mypy) before each commit.

Verify Installation
-------------------

Run the test suite to verify everything is working:

.. code-block:: bash

   uv run pytest
