# RepoMind. Run `make setup` once, then `make check-04` whenever you like.

PY ?= .venv/bin/python

.PHONY: setup test ping audit reset check-04 bounds-smoke

setup:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt
	@echo "ready. Next: copy your Assignment 3 model into settings.yaml and its price line into pricing.yaml, set your key, then make ping."

test:            ## the harness's own tests; they spend no tokens
	$(PY) -m unittest discover -s tests -t .

ping:            ## your key, your model, tool calling, its price line, and your five definitions in one request
	$(PY) -m harness.ping

audit:           ## Assignment 3's schema audit of tools/*.json; no model
	$(PY) tools/audit_schemas.py

reset:           ## before each crash matrix: archive the tracker's database to tracker/archive/; runs/ stays
	$(PY) -m harness.tracker reset

bounds-smoke:    ## the agent way against the model that never stops; free
	$(PY) run.py --way agent --backend never-stops --set dev --runs 1

check-04:        ## the Assignment 4 checker
	$(PY) checks/check_04.py
