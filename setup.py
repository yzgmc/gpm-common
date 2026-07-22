from setuptools import setup, find_packages

setup(
    name="gpm-common",
    version="1.0.0",
    description="Game Push Manager shared library",
    packages=find_packages(),
    install_requires=["pydantic>=2.0.0"],
    python_requires=">=3.9",
)
