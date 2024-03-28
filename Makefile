.DEFAULT_GOAL:=help
.ONESHELL:
ENV_PREFIX		        =.venv/bin/
VENV_EXISTS           =	$(shell python3 -c "if __import__('pathlib').Path('.venv/bin/activate').exists(): print('yes')")
BUILD_DIR             =dist
SRC_DIR               =src
BASE_DIR              =$(shell pwd)

.EXPORT_ALL_VARIABLES:

ifndef VERBOSE
.SILENT:
endif


help:  ## Display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)


# =============================================================================
# Developer Utils
# =============================================================================
install-pipx: 										## Install pipx
	@python3 -m pip install --upgrade --user pipx

install-hatch: 										## Install Hatch, UV, and Ruff
	@pipx install hatch --force
	@pipx inject hatch ruff uv hatch-pip-compile hatch-vcs hatch-mypyc mypy --include-deps --include-apps --force

configure-hatch: 										## Configure Hatch defaults
	@hatch config set dirs.env.virtual .direnv
	@hatch config set dirs.env.pip-compile .direnv

upgrade-hatch: 										## Update Hatch, UV, and Ruff
	@pipx upgrade hatch --include-injected

install: 										## Install the project and all dependencies
	@if [ "$(VENV_EXISTS)" ]; then echo "=> Removing existing virtual environment"; $(MAKE) destroy-venv; fi
	@$(MAKE) clean
	@if ! pipx --version > /dev/null; then echo '=> Installing `pipx`'; $(MAKE) install-pipx ; fi
	@if ! hatch --version > /dev/null; then echo '=> Installing `hatch` with `pipx`'; $(MAKE) install-hatch ; fi
	@if ! hatch-pip-compile --version > /dev/null; then echo '=> Updating `hatch` and installing plugins'; $(MAKE) upgrade-hatch ; fi
	@echo "=> Creating Python environments..."
	@$(MAKE) configure-hatch
	@hatch env create local
	@echo "=> Install complete! Note: If you want to re-install re-run 'make install'"


.PHONY: upgrade
upgrade:       										## Upgrade all dependencies to the latest stable versions
	@echo "=> Updating all dependencies"
	@hatch-pip-compile --upgrade --all
	@echo "=> Python Dependencies Updated"
	@hatch run lint:pre-commit autoupdate
	@echo "=> Updated Pre-commit"


.PHONY: clean
clean: 														## remove all build, testing, and static documentation files
	@echo "=> Cleaning working directory"
	@rm -rf .pytest_cache .ruff_cache .hypothesis build/ dist/ .eggs/ .coverage coverage.xml coverage.json htmlcov/ .mypy_cache
	@find . -name '*.egg-info' -exec rm -rf {} +
	@find . -name '*.egg' -exec rm -f {} +
	@find . -name '*.pyc' -exec rm -f {} +
	@find . -name '*.pyo' -exec rm -f {} +
	@find . -name '*~' -exec rm -f {} +
	@find . -name '__pycache__' -exec rm -rf {} +
	@find . -name '.pytest_cache' -exec rm -rf {} +
	@find . -name '.ipynb_checkpoints' -exec rm -rf {} +
	@echo "=> Source cleaned successfully"

deep-clean: clean destroy-venv							## Clean everything up
	@hatch python remove all
	@echo "=> Hatch environments pruned and python installations trimmed"
	@uv cache clean
	@echo "=> UV Cache cleaned successfully"

destroy-venv: 											## Destroy the virtual environment
	@hatch env prune
	@hatch env remove lint
	@rm -Rf .venv
	@rm -Rf .direnv

.PHONY: build
build: clean        ## Build and package the collectors
	@echo "=> Building package..."
	@hatch build
	@echo "=> Package build complete..."


###############
# docs        #
###############
.PHONY: serve-docs
serve-docs:       ## Serve HTML documentation
	@hatch run docs:serve

.PHONY: docs
docs:       ## generate HTML documentation and serve it to the browser
	@hatch run docs:build


# =============================================================================
# Tests, Linting, Coverage
# =============================================================================
.PHONY: lint
lint: 												## Runs pre-commit hooks; includes ruff linting, codespell, black
	@echo "=> Running pre-commit process"
	@hatch run lint:fix
	@echo "=> Pre-commit complete"

.PHONY: test
test:  												## Run the tests
	@echo "=> Running test cases"
	@hatch run test:cov
	@echo "=> Tests complete"
