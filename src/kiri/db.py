import peewee
from playhouse.migrate import SqliteMigrator
from playhouse.migrate import migrate as run_migrations

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


SCHEMA_VERSION = 1


def bind(path=None):
    database.init(path or config.DB_PATH)
    database.connect(reuse_if_open=True)
    fresh = not database.get_tables()
    database.create_tables(TABLES)
    if not fresh:
        _migrate()
    database.pragma("user_version", SCHEMA_VERSION)


def _migrate():
    version = database.pragma("user_version") or _baseline()
    if version >= SCHEMA_VERSION:
        return

    migrator = SqliteMigrator(database)
    if version < 1:
        run_migrations(
            migrator.add_column("usage", "cache_write_tokens", UsageEvent.cache_write_tokens),
            migrator.add_column("usage", "cache_read_tokens", UsageEvent.cache_read_tokens),
        )


def _baseline():
    # A database older than user_version reports 0 even when it already has the columns.
    columns = {column.name for column in database.get_columns("usage")}
    return 1 if "cache_write_tokens" in columns else 0


class Job(_Base):
    # Explicit so type checkers see the primary key peewee would add anyway.
    id = peewee.AutoField()
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
    id = peewee.AutoField()
    ts = peewee.FloatField()
    day = peewee.TextField()
    # Uncached prompt tokens only. Total prompt = input + cache_write + cache_read.
    input_tokens = peewee.IntegerField()
    output_tokens = peewee.IntegerField()
    # Nullable so they can be added to a database that predates them.
    cache_write_tokens = peewee.IntegerField(default=0, null=True)
    cache_read_tokens = peewee.IntegerField(default=0, null=True)

    class Meta:
        table_name = "usage"
