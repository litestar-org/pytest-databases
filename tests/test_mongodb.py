from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "service_fixture",
    [
        "mongodb_service",
    ],
)
def test_service_fixture(pytester: pytest.Pytester, service_fixture: str) -> None:
    pytester.makepyfile(f"""
    import pymongo
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    def test({service_fixture}):
        client = pymongo.MongoClient(
            host={service_fixture}.host,
            port={service_fixture}.port,
            username={service_fixture}.username,
            password={service_fixture}.password,
        )
        client.admin.command("ping")
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "connection_fixture",
    [
        "mongodb_connection",
    ],
)
def test_connection_fixture(pytester: pytest.Pytester, connection_fixture: str) -> None:
    pytester.makepyfile(f"""
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    def test({connection_fixture}):
        db = {connection_fixture}["test_db"]
        collection = db["test_collection"]
        collection.insert_one({{"key": "value"}})
        result = collection.find_one({{"key": "value"}})
        assert result is not None and result["key"] == "value"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases")
    result.assert_outcomes(passed=1)


def test_xdist_isolate_database(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    def test_1(mongodb_database):
        collection = mongodb_database["test_collection"]
        collection.insert_one({"key": "value1"})
        result = collection.find_one({"key": "value1"})
        assert result is not None and result["key"] == "value1"

    def test_2(mongodb_database):
        collection = mongodb_database["test_collection"]
        # If isolation is working, this collection should be empty or not exist
        result = collection.find_one({"key": "value1"})
        assert result is None
        collection.insert_one({"key": "value2"})
        result = collection.find_one({"key": "value2"})
        assert result is not None and result["key"] == "value2"
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)


def test_xdist_isolate_server(pytester: pytest.Pytester) -> None:
    pytester.makepyfile("""
    import pytest
    pytest_plugins = ["pytest_databases.docker.mongodb"]

    @pytest.fixture(scope="session")
    def xdist_mongodb_isolation_level():
        return "server"

    def test_1(mongodb_connection):
        # Operations in one test should not affect the other if server isolation is working,
        # as they would be on different MongoDB server instances.
        db = mongodb_connection["test_db_server_1"]
        collection = db["test_collection"]
        collection.insert_one({"key": "server1"})
        assert collection.count_documents({}) == 1

    def test_2(mongodb_connection):
        db = mongodb_connection["test_db_server_2"] # Different DB name to be sure
        collection = db["test_collection"]
        # This count should be 0 if it's a new server instance
        assert collection.count_documents({}) == 0
        collection.insert_one({"key": "server2"})
        assert collection.count_documents({}) == 1
    """)

    result = pytester.runpytest_subprocess("-p", "pytest_databases", "-n", "2")
    result.assert_outcomes(passed=2)
