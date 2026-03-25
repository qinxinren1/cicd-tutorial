"""Allow: python -m jobpilot_tailor after ``pip install -e ".[tailor]"``."""

from jobpilot_tailor.tailor import main

if __name__ == "__main__":
    main()
