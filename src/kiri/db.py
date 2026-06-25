import peewee

from kiri import config

# Harness-internal persistence. The agent never reads this; its own long-term
# memory is flat files (see config.MEMORY_DIR). The database is bound once at
# startup (and to a tmp file per test) rather than carried around as a path.

database = peewee.SqliteDatabase(None)

# Every _Base subclass auto-registers here, so bind() creates them all without
# anyone maintaining a hand-written model list.
TABLES = []


class _Base(peewee.Model):
    class Meta:
        database = database

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        TABLES.append(cls)


def bind(path=None):
    database.init(path or config.DB_PATH)
    database.connect(reuse_if_open=True)
    database.create_tables(TABLES)


class Job(_Base):
    # cron is null for one-shot reminders, which fire once and self-delete.
    cron = peewee.TextField(null=True)
    instruction = peewee.TextField()
    channel_id = peewee.IntegerField()
    next_run = peewee.FloatField()
    created = peewee.FloatField()

    class Meta:
        table_name = "jobs"


class Conversation(_Base):
    channel_id = peewee.IntegerField(primary_key=True)
    messages = peewee.TextField()
    summary = peewee.TextField()
    pinned = peewee.TextField()
    last_input_tokens = peewee.IntegerField()

    class Meta:
        table_name = "sessions"


class UsageEvent(_Base):
    ts = peewee.FloatField()
    day = peewee.TextField()
    input_tokens = peewee.IntegerField()
    output_tokens = peewee.IntegerField()

    class Meta:
        table_name = "usage"
