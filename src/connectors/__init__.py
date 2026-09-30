"""Shared ingestion framework for the national rebuild.

Every data source is a connector with the same stages (see ``base.Connector``):

    fetch -> register -> clean -> validate -> load -> publish

This package is independent of the frozen Wisconsin pipeline and imports nothing
from it. See ``src/connectors/README.md`` for the contract and how to add a source.
"""
