use std::path::Path;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection};
use tokio::sync::Mutex;

use crate::embed::EmbeddingBackend;
use crate::key::KeyManager;

// ── Schema SQL ────────────────────────────────────────────────────────────────

/// 200 MB page cache (adr-007): prevents SQLCipher re-decrypt on every KNN
/// page access at 100k-record scale.
const PRAGMA_CACHE: &str = "PRAGMA cache_size = -200000";

/// Flat table with BLOB embeddings.  Default KNN is an O(n) full-scan in Rust
/// — adequate for Phase 5 at < 100 k records.  Upgrade path: swap the
/// `vec0` virtual table once sqlite-vec packaging is fixed (enable `vec0`
/// feature; schema migration is additive).
const SQL_CREATE: &str = "
    CREATE TABLE IF NOT EXISTS memory (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        embedding    BLOB    NOT NULL,
        transcript   TEXT    NOT NULL,
        source       TEXT    NOT NULL DEFAULT 'voice',
        context_blob TEXT,
        tags         TEXT    NOT NULL DEFAULT '[]',
        created_at   INTEGER NOT NULL,
        ttl_seconds  INTEGER NOT NULL DEFAULT 0
    )
";

// ── Public types ──────────────────────────────────────────────────────────────

/// A single search result returned by `PersonalMemory::recall`.
#[derive(Debug, Clone)]
pub struct MemoryRecord {
    pub rowid: i64,
    pub transcript: String,
    pub source: String,
    pub context_blob: Option<String>,
    pub tags: Vec<String>,
    pub created_at: i64,
    /// L2 distance from the query embedding.
    pub distance: f32,
}

// ── PersonalMemory ────────────────────────────────────────────────────────────

/// On-device encrypted vector memory store (adr-007).
///
/// Backed by SQLite (plain `bundled` by default; `sqlcipher` feature enables
/// AES-256 at rest).  Embeddings are stored as raw f32 BLOB; KNN is a
/// full-table L2 scan in Rust (upgrade to sqlite-vec vec0 pending).
pub struct PersonalMemory {
    pub(crate) conn: Mutex<Connection>,
    embedder: Arc<dyn EmbeddingBackend>,
}

impl PersonalMemory {
    /// Open (or create) the memory database at `db_path`.
    pub fn open(
        db_path: &Path,
        key: Option<&KeyManager>,
        embedder: Arc<dyn EmbeddingBackend>,
    ) -> anyhow::Result<Self> {
        let conn = Connection::open(db_path)?;

        // Set SQLCipher key before any other statement (adr-007).
        #[cfg(feature = "sqlcipher")]
        if let Some(km) = key {
            conn.pragma_update(None, "key", km.sqlcipher_pragma())?;
        }
        #[cfg(not(feature = "sqlcipher"))]
        let _ = key;

        conn.execute_batch(PRAGMA_CACHE)?;
        conn.execute_batch(SQL_CREATE)?;

        tracing::info!(path = %db_path.display(), "PersonalMemory opened");
        Ok(Self {
            conn: Mutex::new(conn),
            embedder,
        })
    }

    /// Convenience: open an in-memory database (for testing).
    pub fn open_in_memory(embedder: Arc<dyn EmbeddingBackend>) -> anyhow::Result<Self> {
        Self::open(Path::new(":memory:"), None, embedder)
    }

    // ── Write ─────────────────────────────────────────────────────────────────

    /// Embed `transcript` and store a memory record.  Returns the new row id.
    pub async fn commit(
        &self,
        transcript: &str,
        source: &str,
        context: Option<&str>,
        tags: &[&str],
        ttl_seconds: u64,
    ) -> anyhow::Result<i64> {
        let embedding = self.embedder.embed(transcript)?;
        let emb_bytes = to_bytes(&embedding);
        let tags_json = serde_json::to_string(tags)?;
        let created_at = unix_now();

        let conn = self.conn.lock().await;
        conn.execute(
            "INSERT INTO memory(embedding, transcript, source, context_blob, tags, created_at, ttl_seconds)
             VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![emb_bytes, transcript, source, context, tags_json, created_at, ttl_seconds as i64],
        )?;
        let rowid = conn.last_insert_rowid();
        tracing::debug!(rowid, %source, "memory committed");
        Ok(rowid)
    }

    // ── Read ──────────────────────────────────────────────────────────────────

    /// Return the `k` nearest memories to `query` by L2 distance.
    ///
    /// Full-table scan in Rust — O(n) but correct.
    /// Upgrade to `vec0` KNN (adr-007) once sqlite-vec packaging is fixed.
    pub async fn recall(&self, query: &str, k: usize) -> anyhow::Result<Vec<MemoryRecord>> {
        let q_emb = self.embedder.embed(query)?;

        let conn = self.conn.lock().await;
        let mut stmt = conn.prepare(
            "SELECT id, embedding, transcript, source, context_blob, tags, created_at
             FROM memory ORDER BY id",
        )?;

        // Collect all rows + compute distance.
        let mut scored: Vec<(f32, MemoryRecord)> = stmt
            .query_map([], |row| {
                let emb_blob: Vec<u8> = row.get(1)?;
                let tags_str: String = row.get(5)?;
                Ok((
                    emb_blob,
                    MemoryRecord {
                        rowid: row.get(0)?,
                        transcript: row.get(2)?,
                        source: row.get(3)?,
                        context_blob: row.get(4)?,
                        tags: serde_json::from_str(&tags_str).unwrap_or_default(),
                        created_at: row.get(6)?,
                        distance: 0.0,
                    },
                ))
            })?
            .filter_map(|r| r.ok())
            .map(|(emb_bytes, mut rec)| {
                let emb = from_bytes(&emb_bytes);
                let dist = l2_distance(&q_emb, &emb);
                rec.distance = dist;
                (dist, rec)
            })
            .collect();

        scored.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(k);
        Ok(scored.into_iter().map(|(_, r)| r).collect())
    }

    // ── Delete ────────────────────────────────────────────────────────────────

    /// Delete records committed within the last `minutes` minutes.
    pub async fn forget_last(&self, minutes: u64) -> anyhow::Result<usize> {
        let cutoff = unix_now() - (minutes * 60) as i64;
        let conn = self.conn.lock().await;
        let n = conn.execute("DELETE FROM memory WHERE created_at >= ?", [cutoff])?;
        tracing::info!(deleted = n, minutes, "forget_last complete");
        Ok(n)
    }

    /// Delete expired records (`ttl_seconds > 0` and past expiry).
    pub async fn sweep_expired(&self) -> anyhow::Result<usize> {
        let conn = self.conn.lock().await;
        let now = unix_now();
        let n = conn.execute(
            "DELETE FROM memory WHERE ttl_seconds > 0 AND (created_at + ttl_seconds) < ?",
            [now],
        )?;
        if n > 0 {
            tracing::info!(deleted = n, "swept expired memory records");
        }
        Ok(n)
    }
}

// ── Embedding serialisation ───────────────────────────────────────────────────

fn to_bytes(v: &[f32]) -> Vec<u8> {
    v.iter().flat_map(|f| f.to_le_bytes()).collect()
}

fn from_bytes(b: &[u8]) -> Vec<f32> {
    b.chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

fn l2_distance(a: &[f32], b: &[f32]) -> f32 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (x - y).powi(2))
        .sum::<f32>()
        .sqrt()
}

fn unix_now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}
