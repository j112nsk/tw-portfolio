-- Пользователи
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    role VARCHAR(20) CHECK (role IN ('reader', 'author', 'editor', 'admin')),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Документы (базовая запись, версии хранятся отдельно)
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    created_by INT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    current_version_id INT, -- ссылка на версию, которая сейчас активна (заполнится позже)
    is_deleted BOOLEAN DEFAULT FALSE
);

-- Версии документа
CREATE TABLE document_versions (
    id SERIAL PRIMARY KEY,
    document_id INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INT NOT NULL,
    content TEXT NOT NULL, -- храним Markdown или HTML
    author_id INT REFERENCES users(id),
    status VARCHAR(20) CHECK (status IN ('draft', 'review', 'approved', 'archived')),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, version_number)
);

-- Теги
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL
);

-- Связь документов с тегами
CREATE TABLE document_tags (
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

-- Просмотры (аналитика)
CREATE TABLE views (
    id SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id),
    viewed_at TIMESTAMP DEFAULT NOW()
);

-- Лог изменений (для security & auditing)
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    action VARCHAR(100), -- 'document_updated', 'version_approved', 'role_changed'
    entity_id INT,
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);