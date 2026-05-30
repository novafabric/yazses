//! Custom vocabulary / dictionary.
//!
//! Lets the user pin domain terms, proper nouns, and code identifiers that ASR
//! routinely mis-spells (e.g. `GitHub`, `Kubernetes`, `kubectl`, `OAuth`). The
//! same list serves two jobs, mirroring what Wispr Flow's dictionary, Windows
//! Voice Access "add to vocabulary", and Aqua Voice's domain tuning do:
//!
//! 1. [`Vocabulary::prompt_hint`] — a biasing string fed into the STT
//!    `initial_prompt` so the recognizer is primed to produce these tokens.
//! 2. [`Vocabulary::correct`] — a deterministic, whole-word, case-insensitive
//!    post-correction that rewrites recognized tokens to their canonical
//!    spelling/casing.
//!
//! Correction operates on single-word tokens (a maximal run of alphanumeric
//! characters); multi-word terms still contribute to the prompt hint. Pure
//! logic, no model — fully unit-tested.

use std::collections::HashMap;

/// A user dictionary of canonical terms.
#[derive(Debug, Clone, Default)]
pub struct Vocabulary {
    /// All terms, in input order (used for the prompt hint).
    terms: Vec<String>,
    /// lowercased single-word token -> canonical spelling (used for correction).
    lookup: HashMap<String, String>,
}

impl Vocabulary {
    /// Build from an iterator of terms. Blank terms are skipped; later entries
    /// win on collision.
    pub fn new(terms: impl IntoIterator<Item = String>) -> Self {
        let mut ordered = Vec::new();
        let mut lookup = HashMap::new();
        for raw in terms {
            let term = raw.trim().to_string();
            if term.is_empty() {
                continue;
            }
            // Only single-word tokens are correctable; all terms bias the prompt.
            if !term.chars().any(char::is_whitespace) {
                lookup.insert(term.to_ascii_lowercase(), term.clone());
            }
            ordered.push(term);
        }
        Self { terms: ordered, lookup }
    }

    /// Parse a delimited string (comma / semicolon / newline separated).
    pub fn parse(s: &str) -> Self {
        Self::new(s.split([',', ';', '\n']).map(|t| t.to_string()))
    }

    /// Build from the `YAZSES_VOCABULARY` env var (the core has no TOML loader
    /// yet). Empty/unset → empty vocabulary.
    pub fn from_env() -> Self {
        match std::env::var("YAZSES_VOCABULARY") {
            Ok(s) => Self::parse(&s),
            Err(_) => Self::default(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.terms.is_empty()
    }

    pub fn len(&self) -> usize {
        self.terms.len()
    }

    /// Biasing string for the STT `initial_prompt`, or `None` when empty.
    pub fn prompt_hint(&self) -> Option<String> {
        if self.terms.is_empty() {
            return None;
        }
        Some(format!("Vocabulary: {}.", self.terms.join(", ")))
    }

    /// Rewrite whole-word, case-insensitive matches to their canonical form.
    /// Non-word characters (spaces, punctuation) are preserved exactly.
    pub fn correct(&self, text: &str) -> String {
        if self.lookup.is_empty() {
            return text.to_string();
        }
        let mut out = String::with_capacity(text.len());
        let mut word = String::new();
        for ch in text.chars() {
            if ch.is_alphanumeric() {
                word.push(ch);
            } else {
                self.flush_word(&mut out, &mut word);
                out.push(ch);
            }
        }
        self.flush_word(&mut out, &mut word);
        out
    }

    fn flush_word(&self, out: &mut String, word: &mut String) {
        if word.is_empty() {
            return;
        }
        match self.lookup.get(&word.to_ascii_lowercase()) {
            Some(canonical) => out.push_str(canonical),
            None => out.push_str(word),
        }
        word.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_splits_on_common_delimiters() {
        let v = Vocabulary::parse("GitHub, Kubernetes; kubectl\nOAuth");
        assert_eq!(v.len(), 4);
        assert!(!v.is_empty());
    }

    #[test]
    fn parse_skips_blanks_and_trims() {
        let v = Vocabulary::parse("  GitHub , , ;  kubectl ");
        assert_eq!(v.len(), 2);
    }

    #[test]
    fn empty_vocabulary_is_a_noop() {
        let v = Vocabulary::default();
        assert!(v.is_empty());
        assert_eq!(v.correct("anything goes here"), "anything goes here");
        assert_eq!(v.prompt_hint(), None);
    }

    #[test]
    fn prompt_hint_lists_all_terms() {
        let v = Vocabulary::parse("GitHub, Node.js, GitHub Actions");
        assert_eq!(
            v.prompt_hint().unwrap(),
            "Vocabulary: GitHub, Node.js, GitHub Actions."
        );
    }

    #[test]
    fn correct_fixes_casing_whole_word_case_insensitively() {
        let v = Vocabulary::parse("GitHub, Kubernetes, OAuth, kubectl");
        assert_eq!(
            v.correct("i pushed to github and configured kubernetes with Kubectl"),
            "i pushed to GitHub and configured Kubernetes with kubectl"
        );
    }

    #[test]
    fn correct_preserves_punctuation_and_spacing() {
        let v = Vocabulary::parse("GitHub");
        assert_eq!(v.correct("(github),  github."), "(GitHub),  GitHub.");
    }

    #[test]
    fn correct_does_not_touch_substrings_inside_other_words() {
        let v = Vocabulary::parse("cat");
        // "category" must not become "Category" — whole-word only.
        assert_eq!(v.correct("the category of cat"), "the category of cat");
    }

    #[test]
    fn correct_ignores_multiword_terms_but_hint_keeps_them() {
        let v = Vocabulary::parse("GitHub Actions");
        // Multi-word term is not applied token-by-token...
        assert_eq!(v.correct("github actions are great"), "github actions are great");
        // ...but it still biases the recognizer.
        assert!(v.prompt_hint().unwrap().contains("GitHub Actions"));
    }
}
