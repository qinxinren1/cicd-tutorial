"""Allow: python -m jobpilot after `pip install -e .` from the job-pilot repo root."""

from jobpilot.discover import main

if __name__ == "__main__":
    main()
