# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

.PHONY: test gateway benchmark-core benchmark-gcp figures deploy

test:
	pytest -v

gateway:
	uvicorn app.service:app --host 0.0.0.0 --port 8080 --reload

benchmark-core:
	python3 benchmarks/run_all_experiments.py

benchmark-gcp:
	python3 benchmarks/run_gcp_platform_experiments.py

figures:
	python3 benchmarks/generate_figures.py

deploy:
	./deploy/deploy_cloud_run.sh
