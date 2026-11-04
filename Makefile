.PHONY: dev test sample openapi

dev:
	docker compose up --build

test:
	cd backend && pytest
	cd cdisc-mcp && pytest
	cd workbench-mcp && pytest
	cd sdtm-runner && pytest
	cd frontend && npm test
	cd frontend && npm run build

sample:
	python samples/generate_blank_crf.py

openapi:
	cd frontend && npm run generate:api
