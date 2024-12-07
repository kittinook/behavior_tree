from setuptools import setup, find_packages

setup(
    name="behavior-tree",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "asyncio>=3.4.3",
        "pyyaml>=6.0",
    ],
)

