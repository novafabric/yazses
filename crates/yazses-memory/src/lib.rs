pub mod embed;
pub mod key;
pub mod store;

pub use embed::{EmbeddingBackend, MockEmbedder};
pub use key::KeyManager;
pub use store::{MemoryRecord, PersonalMemory};

#[cfg(feature = "onnx")]
pub use embed::OnnxEmbedder;

// ── Integration tests ─────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use crate::{embed::MockEmbedder, store::PersonalMemory};
    use std::sync::Arc;

    fn store() -> PersonalMemory {
        PersonalMemory::open_in_memory(Arc::new(MockEmbedder)).unwrap()
    }

    // ── embed ─────────────────────────────────────────────────────────────────

    #[test]
    fn mock_embedder_dimensions() {
        let e = MockEmbedder;
        assert_eq!(crate::embed::EmbeddingBackend::dimensions(&e), 384);
    }

    #[test]
    fn mock_embedder_unit_vector() {
        use crate::embed::EmbeddingBackend;
        let v = MockEmbedder.embed("hello").unwrap();
        assert_eq!(v.len(), 384);
        let sum: f32 = v.iter().sum();
        assert!(
            (sum - 1.0).abs() < 1e-6,
            "should be a unit vector (sum = {sum})"
        );
    }

    #[test]
    fn mock_embedder_different_texts_differ() {
        use crate::embed::EmbeddingBackend;
        let va = MockEmbedder.embed("alpha text").unwrap();
        let vb = MockEmbedder.embed("beta text").unwrap();
        assert_ne!(va, vb, "'a' and 'b' should map to different dimensions");
    }

    // ── store ─────────────────────────────────────────────────────────────────

    #[tokio::test]
    async fn schema_creates_and_opens() {
        let _s = store();
    }

    #[tokio::test]
    async fn commit_returns_positive_rowid() {
        let s = store();
        let rowid = s
            .commit("hello world", "voice", None, &[], 0)
            .await
            .unwrap();
        assert!(rowid > 0);
    }

    #[tokio::test]
    async fn recall_returns_committed_item() {
        let s = store();
        s.commit("alpha document", "voice", None, &[], 0)
            .await
            .unwrap();
        let results = s.recall("alpha query", 5).await.unwrap();
        assert!(!results.is_empty());
        assert_eq!(results[0].source, "voice");
    }

    #[tokio::test]
    async fn recall_orders_by_distance() {
        // MockEmbedder uses first byte as discriminant.
        // "apple" (a=97) and "ant" (a=97) map to the same dim; "banana" (b=98) different.
        let s = store();
        s.commit("apple text", "voice", None, &[], 0).await.unwrap();
        s.commit("banana text", "voice", None, &[], 0)
            .await
            .unwrap();

        // Query "ants" starts with 'a' → same dim as "apple text" → distance 0
        let results = s.recall("ants query", 2).await.unwrap();
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].transcript, "apple text");
        assert!(results[0].distance < results[1].distance);
    }

    #[tokio::test]
    async fn forget_last_removes_recent() {
        let s = store();
        s.commit("recent text", "voice", None, &[], 0)
            .await
            .unwrap();
        let deleted = s.forget_last(1440).await.unwrap(); // last 24 h
        assert_eq!(deleted, 1);
        let after = s.recall("recent", 5).await.unwrap();
        assert!(after.is_empty());
    }

    #[tokio::test]
    async fn sweep_expired_removes_ttl_records() {
        let s = store();
        // Insert with created_at = 0 (Unix epoch), ttl = 1 s: expired long ago.
        {
            use crate::embed::EmbeddingBackend;
            let emb: Vec<u8> = MockEmbedder
                .embed("test")
                .unwrap()
                .iter()
                .flat_map(|f| f.to_le_bytes())
                .collect();
            s.conn.lock().await.execute(
                "INSERT INTO memory(embedding, transcript, source, context_blob, tags, created_at, ttl_seconds)
                 VALUES (?, 'expired item', 'voice', NULL, '[]', 0, 1)",
                rusqlite::params![emb],
            ).unwrap();
        }
        let swept = s.sweep_expired().await.unwrap();
        assert_eq!(swept, 1);
        let remaining = s.recall("test", 5).await.unwrap();
        assert!(remaining.is_empty());
    }
}
