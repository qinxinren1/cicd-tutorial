"""Allow: python -m jobpilot_enrich after `pip install -e .` from the job-pilot repo root."""

from jobpilot_enrich.enrich import main

if __name__ == "__main__":
    main()
