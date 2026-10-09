# offline-power-lab :: build / test / demo entry points.
#
# NOTE: no `mkdir -p` anywhere - make.exe on Windows does not ship a shell, so
# every directory is created by the Python code itself (encoding="utf-8").

PY ?= python
OUT ?= results

.PHONY: all help test demo demo-corrected design stress loop safety emi budget clean version

help:
	@echo "make test            - run the full self-check suite (no third-party deps)"
	@echo "make demo            - run the default design end to end and write $(OUT)/"
	@echo "make demo-corrected  - run the corrected part set (passes every check)"
	@echo "make design          - flyback main circuit only"
	@echo "make clean           - remove generated output and __pycache__ directories"

all: test demo demo-corrected

test:
	$(PY) test/test_all.py

demo:
	$(PY) main.py all --out $(OUT)

demo-corrected:
	$(PY) demo_corrected.py --out $(OUT)

design:
	$(PY) main.py design

stress:
	$(PY) main.py stress

loop:
	$(PY) main.py loop

safety:
	$(PY) main.py safety

emi:
	$(PY) main.py emi

budget:
	$(PY) main.py budget

version:
	$(PY) -c "import opl; print(opl.__version__)"

clean:
	$(PY) -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('$(OUT)', '__pycache__', 'opl/__pycache__', 'test/__pycache__')]"
