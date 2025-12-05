# Echoroo - Python Backend

**Echoroo** is an open-source web-based audio annotation tool designed to facilitate audio data labeling and annotation, with a special focus on aiding machine learning model development.

For additional details on installing the entire application and its usage, refer to the main [README](https://github.com/okamoto-group/echoroo).

For the latest updates and detailed documentation, check out the project documentation.

## Installation

### With Pip

The most straightforward method to set up the backend is from source code.

### From Source Code

Clone the repository:

```bash
git clone https://github.com/okamoto-group/echoroo.git
```

Install the package:

```bash
cd echoroo/back
pip install .
```

### With Docker

Run Echoroo inside a Docker container.
Build the container by cloning the repository and executing:

```bash
git clone https://github.com/okamoto-group/echoroo.git
docker build -t echoroo .
```

Once the build is complete, run the container with:

```bash
docker run -p 5000:5000 echoroo
```

### Development Environment

We manage Echoroo's development with `uv`.

1. Follow the official [installation instructions](https://docs.astral.sh/uv/#highlights) to get `uv` on your machine.

2. Clone the repository:

```bash
git clone https://github.com/okamoto-group/echoroo.git
```

3. Navigate to the backend directory and install dependencies:

```bash
cd echoroo/back
uv sync
```

4. Start the development server:

```bash
make serve-dev
```

or

```bash
ECHOROO_DEV=true uv run python -m echoroo
```
