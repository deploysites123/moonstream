from setuptools import find_packages, setup

from moonstream.version import MOONSTREAM_VERSION

long_description = ""
with open("README.md") as ifp:
    long_description = ifp.read()

setup(
    name="moonstream",
    version=MOONSTREAM_VERSION,
    packages=find_packages(),
    install_requires=[
        "appdirs~=1.4.4",
        "boto3~=1.20.2",
        "bugout~=0.1.18",
        "fastapi~=0.70.0",
        "moonstreamdb==0.2.0",
        "humbug~=0.2.7",
        "pydantic~=1.8.2",
        "python-dateutil~=2.8.2",
        "python-multipart~=0.0.5"
        "uvicorn~=0.15.0",
        "web3~=5.24.0",
    ],
    extras_require={
        "dev": ["black", "isort", "mypy", "types-requests", "types-python-dateutil"],
        "distribute": ["setuptools", "twine", "wheel"],
    },
    package_data={"moonstream": ["py.typed"]},
    zip_safe=False,
    description="The Bugout blockchain inspector API.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Bugout.dev",
    author_email="engineering@bugout.dev",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Software Development :: Libraries",
    ],
    url="https://github.com/bugout-dev/moonstream",
    entry_points={"console_scripts": ["mnstr=moonstream.admin.cli:main"]},
)
