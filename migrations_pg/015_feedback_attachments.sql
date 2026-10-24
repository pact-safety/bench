-- 015: image attachments on feedback (feedback widget screenshots).
--
-- Bytes live in Postgres (BYTEA) rather than an object store so
-- self-hosters need no extra service. Caps are enforced app-side
-- (<= 3 images per feedback, <= 2 MB each) and belt-and-braces here.

CREATE TABLE IF NOT EXISTS feedback_attachments (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feedback_id  BIGINT NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
    user_id      UUID   NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    filename     TEXT   NOT NULL,
    content_type TEXT   NOT NULL CHECK (content_type IN
                     ('image/png','image/jpeg','image/webp','image/gif')),
    byte_size    INTEGER NOT NULL CHECK (byte_size > 0 AND byte_size <= 2097152),
    bytes        BYTEA  NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_attachments_feedback
    ON feedback_attachments(feedback_id);
