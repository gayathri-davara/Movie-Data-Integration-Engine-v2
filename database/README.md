# Database schema

- `schema_v1.sql` is the proposed production SQLite schema.
- It is not yet connected to the current Flask/JSON pipeline.
- Evaluation labels derived from `links.csv` must remain in a separate evaluation store.

To smoke-test manually:

```bash
python -c "import sqlite3; c=sqlite3.connect('movie_integration.db'); c.executescript(open('database/schema_v1.sql', encoding='utf-8').read()); print(c.execute('PRAGMA foreign_key_check').fetchall()); c.close()"
```

Every application connection must execute `PRAGMA foreign_keys = ON` because SQLite does not enable FK enforcement by default per connection.
