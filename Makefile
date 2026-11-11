.PHONY: run test lint

run:
	python -m backend.app

test:
	python -m unittest discover -s tests -v

lint:
	@python -c "import subprocess, sys; has_ruff = subprocess.call(['where', 'ruff'] if sys.platform == 'win32' else ['which', 'ruff'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0; sys.exit(subprocess.call(['ruff', 'check', '.']) if has_ruff else print('ruff not installed, skipping lint'))"

