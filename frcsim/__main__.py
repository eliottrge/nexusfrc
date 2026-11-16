from .youtube import main

# Guard needed: worker processes re-import this module on Windows.
if __name__ == "__main__":
    main()
