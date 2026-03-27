-- Versioned migration (Flyway naming matches Java backend: V{version}__description.sql)
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL DEFAULT ''
);
