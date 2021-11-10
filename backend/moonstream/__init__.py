try:
    from .reporter import reporter
    from .version import MOONSTREAM_VERSION

    # Reporting
    reporter.tags.append(f"version:{MOONSTREAM_VERSION}")
    reporter.system_report(publish=True)
    reporter.setup_excepthook(publish=True)
except:
    # Pass it to be able import MOONSTREAM_VERSION in setup.py with pip
    pass
