import unittest

from sqlalchemy import create_engine, inspect, text

from app.database import ensure_schema


class SchemaMigrationTests(unittest.TestCase):
    def test_legacy_dates_migrate_once_without_altering_reminder_dates(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)'))
                connection.execute(text('CREATE TABLE person_certificates (id INTEGER PRIMARY KEY, issue_date DATE, expiry_date DATE)'))
                connection.execute(text("INSERT INTO person_certificates VALUES (1, '2026-09-30', '2027-09-29')"))
            ensure_schema(engine)
            self.assertIn('identity_number', {item['name'] for item in inspect(engine).get_columns('people')})
            with engine.begin() as connection:
                row = connection.execute(text('SELECT validity_start_date, validity_end_date, expiry_date FROM person_certificates')).one()
                self.assertEqual(tuple(row), ('2026-09-30', '2027-09-29', '2027-09-29'))
                connection.execute(text('UPDATE person_certificates SET validity_start_date = NULL, validity_end_date = NULL'))
            ensure_schema(engine)
            with engine.connect() as connection:
                row = connection.execute(text('SELECT validity_start_date, validity_end_date, expiry_date FROM person_certificates')).one()
                self.assertEqual(tuple(row), (None, None, '2027-09-29'))
        finally:
            engine.dispose()
