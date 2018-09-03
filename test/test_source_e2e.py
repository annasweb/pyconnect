from time import sleep
from typing import Any, Callable, List, Tuple

from confluent_kafka import KafkaError
from confluent_kafka.avro import AvroConsumer
import pytest

from pyconnect.config import SourceConfig
from test.utils import PyConnectTestSource
# noinspection PyUnresolvedReferences
from test.utils import cluster_hosts, topic


SourceFactory = Callable[..., PyConnectTestSource]


@pytest.fixture
def source_factory(topic, cluster_hosts) -> SourceFactory:
    """
    Creates a factory, that can be used to create readily usable instances of :class:`test.utils.PyConnectTestSource`.
    """
    topic_id, _ = topic

    config = SourceConfig(dict(
        bootstrap_servers=cluster_hosts['broker'],
        schema_registry=cluster_hosts['schema-registry'],
        offset_topic=f'{topic_id}_offsets',
        offset_commit_interval=5,
        topic=topic_id
    ))

    def source_factory_() -> PyConnectTestSource:
        source = PyConnectTestSource(config)
        return source

    yield source_factory_


Record = Tuple[Any, Any]
RecordList = List[Record]
ConsumeAll = Callable[..., RecordList]

@pytest.fixture
def consume_all(topic, cluster_hosts) -> ConsumeAll:
    """
    Creates a function that consumes and returns all messages for the current test's topic.
    """
    topic_id, _ = topic

    consumer = AvroConsumer({
        'bootstrap.servers': cluster_hosts['broker'],
        'schema.registry.url':  cluster_hosts['schema-registry'],
        'group.id': f'{topic_id}_consumer',
        'enable.partition.eof': False,
        "default.topic.config": {
            "auto.offset.reset": "earliest"
        }
    })
    consumer.subscribe([topic_id])

    def consume_all_() -> RecordList:
        records = []
        while True:
            msg = consumer.poll(timeout=2)
            if msg is None:
                break
            if msg.error() is not None:
                assert msg.error().code() == KafkaError._PARTITION_EOF
                break
            records.append((msg.key(), msg.value()))
        return records

    yield consume_all_
    consumer.close()


@pytest.fixture
def records() -> RecordList:
    """
    Just a list of simple records, ready to be used as messages.
    """
    return [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5)
    ]


@pytest.mark.e2e
def test_produce_messages(source_factory: SourceFactory, records: RecordList, consume_all: ConsumeAll):
    source = source_factory().with_records(records)

    source.run()
    source._producer.flush()
    sleep(1)
    consumed_records = consume_all()

    assert set(records) == set(consumed_records)


@pytest.mark.e2e
def test_resume_producing(source_factory: SourceFactory, consume_all: ConsumeAll):
    first_records = [(1, 1), (2, 2), (3, 3)]
    first_source = source_factory().with_records(first_records)

    false_first_records = [(-1, -1), (-2, -2), (-3, -3)]
    second_records = [(4, 4), (5, 5), (6, 6)]
    second_source = source_factory().with_records(false_first_records + second_records)

    first_source.run()
    second_source.run()
    consumed_records = consume_all()

    assert set(consumed_records) == set(first_records + second_records)