//! Deterministic punctuation & capitalization polish (no LLM).
//!
//! Applied to dictated text on the default/`verbatim` path so the no-LLM output
//! still gets the baseline tidy-up users expect — the same mechanical fixes
//! Microsoft's on-device "Fluid Dictation" performs (capitalize sentences, fix
//! spacing around punctuation), and the cheap front half of any ASR
//! punctuation-restoration pipeline. Pure, allocation-light, fully tested.
//!
//! Conservative by design: it changes casing and whitespace-around-punctuation
//! only. It never adds, removes, or reorders words.

/// Polish capitalization and punctuation spacing. Returns `""` for blank input.
pub fn polish_mechanics(text: &str) -> String {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    let capitalized = capitalize_and_fix_i(trimmed);
    drop_space_before_punct(&capitalized)
}

/// Treat a run of alphanumerics or apostrophes as one "word"; everything else
/// is a separator. Capitalize the first word of each sentence and rewrite the
/// pronoun "i" / "i'm" / "i'll" / … to its capitalized form.
fn capitalize_and_fix_i(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut word = String::new();
    let mut at_sentence_start = true;

    for ch in text.chars() {
        if ch.is_alphanumeric() || ch == '\'' || ch == '\u{2019}' {
            word.push(ch);
        } else {
            flush_word(&mut out, &mut word, &mut at_sentence_start);
            out.push(ch);
            if matches!(ch, '.' | '!' | '?') {
                at_sentence_start = true;
            }
        }
    }
    flush_word(&mut out, &mut word, &mut at_sentence_start);
    out
}

fn flush_word(out: &mut String, word: &mut String, at_sentence_start: &mut bool) {
    if word.is_empty() {
        return;
    }
    let mut w = fix_pronoun_i(word);
    if *at_sentence_start {
        w = capitalize_first(&w);
        *at_sentence_start = false;
    }
    out.push_str(&w);
    word.clear();
}

/// "i" → "I", "i'm" → "I'm", etc. Leaves anything not starting with a lone "i"
/// followed by an apostrophe (or being exactly "i") untouched.
fn fix_pronoun_i(word: &str) -> String {
    let lower = word.to_ascii_lowercase();
    if lower == "i" {
        return "I".to_string();
    }
    if lower.starts_with("i'") || lower.starts_with("i\u{2019}") {
        let mut c = word.chars();
        match c.next() {
            Some(_) => format!("I{}", c.as_str()),
            None => word.to_string(),
        }
    } else {
        word.to_string()
    }
}

fn capitalize_first(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

/// Remove whitespace immediately before sentence punctuation: "hello ," → "hello,".
fn drop_space_before_punct(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for ch in text.chars() {
        if matches!(ch, ',' | '.' | '!' | '?' | ';' | ':') {
            while out.ends_with(' ') || out.ends_with('\t') {
                out.pop();
            }
        }
        out.push(ch);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_and_blank_return_empty() {
        assert_eq!(polish_mechanics(""), "");
        assert_eq!(polish_mechanics("   "), "");
    }

    #[test]
    fn capitalizes_first_word() {
        assert_eq!(polish_mechanics("hello there"), "Hello there");
    }

    #[test]
    fn capitalizes_after_sentence_punctuation() {
        assert_eq!(
            polish_mechanics("hello there. how are you? fine! ok"),
            "Hello there. How are you? Fine! Ok"
        );
    }

    #[test]
    fn fixes_standalone_pronoun_i() {
        assert_eq!(
            polish_mechanics("yesterday i went and i'm tired and i'll rest"),
            "Yesterday I went and I'm tired and I'll rest"
        );
    }

    #[test]
    fn does_not_capitalize_i_inside_words() {
        // "in" / "is" must not be touched.
        assert_eq!(polish_mechanics("it is in india"), "It is in india");
    }

    #[test]
    fn removes_space_before_punctuation() {
        assert_eq!(
            polish_mechanics("hello , world . done !"),
            "Hello, world. Done!"
        );
    }

    #[test]
    fn preserves_internal_capitalized_tokens() {
        // It only uppercases; it never lowercases an existing capital (e.g. GitHub).
        assert_eq!(polish_mechanics("push to GitHub now"), "Push to GitHub now");
    }
}
