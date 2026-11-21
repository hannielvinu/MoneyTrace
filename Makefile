# MoneyTrace developer commands. Run from the repo root.
PY      ?= python -X utf8
BACKEND := backend
PORT    ?= 8000
BASE_URL ?= http://127.0.0.1:$(PORT)

.PHONY: help dev test acceptance eval eval-classifier eval-rag ingest migrate load deploy usage

help:
	@echo "make dev            run the API locally with reload"
	@echo "make test           unit tests (no network)"
	@echo "make acceptance     end-to-end acceptance test against BASE_URL (server must be running)"
	@echo "make migrate        apply Alembic migrations to DATABASE_URL"
	@echo "make ingest         download + chunk + embed the advisory corpus into pgvector"
	@echo "make eval           classifier benchmark + RAG eval, results saved in backend/results/"
	@echo "make load           load test against BASE_URL, results in backend/results/load/"
	@echo "make deploy         print the Cloud Run deploy steps (see scripts/deploy_cloudrun.sh)"
	@echo "make usage          write the daily help-desk usage summary"

dev:
	cd $(BACKEND) && $(PY) -m uvicorn moneytrace.main:app --reload --port $(PORT)

test:
	cd $(BACKEND) && $(PY) -m pytest -q

acceptance:
	cd $(BACKEND) && MONEYTRACE_BASE_URL=$(BASE_URL) $(PY) test_acceptance.py

migrate:
	cd $(BACKEND) && $(PY) -m alembic upgrade head

ingest:
	cd $(BACKEND) && $(PY) -m rag.ingest

eval: eval-classifier eval-rag

eval-classifier:
	cd $(BACKEND) && $(PY) evaluation/generate_dataset.py && $(PY) evaluation/evaluator.py

eval-rag:
	cd $(BACKEND) && $(PY) -m evaluation.rag_eval

load:
	cd $(BACKEND) && $(PY) scripts/load_test.py --base-url $(BASE_URL)

deploy:
	@echo "Deployment touches your Google Cloud project. Run the steps one by one:"
	@echo "  bash backend/scripts/deploy_cloudrun.sh help"

usage:
	cd $(BACKEND) && $(PY) scripts/usage_summary.py
