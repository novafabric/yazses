//! Spoken formatting commands ("new line", "new paragraph", "open paren", …).
//!
//! Every mainstream dictation product (Apple Dictation, Windows Voice Access,
//! Dragon, nerd-dictation) lets you speak structural tokens you can't easily
//! pronounce. This is the deterministic rewrite for the `type_text` branch.
//!
//! Deliberately conservative: only an unambiguous, opt-in phrase set is
//! recognized, matched whole-word and case-insensitively, so ordinary prose is
//! never mangled. Pure logic, fully tested.

/// Two-word spoken commands → their literal replacement.
const TWO_WORD: &[(&str, &str, Replacement)] = &[
    ("new", "line", Replacement::NewlineSingle),
    ("new", "paragraph", Replacement::NewlineDouble),
    ("open", "paren", Replacement::Open("(")),
    ("open", "parenthesis", Replacement::Open("(")),
    ("close", "paren", Replacement::Close(")")),
    ("close", "parenthesis", Replacement::Close(")")),
    ("open", "bracket", Replacement::Open("[")),
    ("close", "bracket", Replacement::Close("]")),
    ("open", "brace", Replacement::Open("{")),
    ("close", "brace", Replacement::Close("}")),
];

#[derive(Clone, Copy)]
enum Replacement {
    NewlineSingle,
    NewlineDouble,
    /// Opening delimiter — attaches to the following word ("(x").
    Open(&'static str),
    /// Closing delimiter — attaches to the preceding word ("x)").
    Close(&'static str),
}

#[derive(Debug, PartialEq)]
enum Tok {
    Word(String),
    Sep(String),
}

fn tokenize(text: &str) -> Vec<Tok> {
    let mut toks = Vec::new();
    let mut word = String::new();
    let mut sep = String::new();
    for ch in text.chars() {
        if ch.is_alphanumeric() {
            if !sep.is_empty() {
                toks.push(Tok::Sep(std::mem::take(&mut sep)));
            }
            word.push(ch);
        } else {
            if !word.is_empty() {
                toks.push(Tok::Word(std::mem::take(&mut word)));
            }
            sep.push(ch);
        }
    }
    if !word.is_empty() {
        toks.push(Tok::Word(word));
    }
    if !sep.is_empty() {
        toks.push(Tok::Sep(sep));
    }
    toks
}

/// Rewrite recognized spoken-formatting phrases. When `enabled` is false the
/// input is returned unchanged.
pub fn apply_dictation_commands(text: &str, enabled: bool) -> String {
    if !enabled || text.is_empty() {
        return text.to_string();
    }
    let toks = tokenize(text);
    let mut out = String::with_capacity(text.len());
    let mut i = 0;

    while i < toks.len() {
        // Try a two-word phrase: Word, whitespace-only Sep, Word.
        if let Tok::Word(w1) = &toks[i] {
            if i + 2 < toks.len() {
                if let (Tok::Sep(mid), Tok::Word(w2)) = (&toks[i + 1], &toks[i + 2]) {
                    if mid.chars().all(char::is_whitespace) {
                        if let Some(rep) = lookup_two_word(w1, w2) {
                            let swallow_following = apply_replacement(&mut out, rep);
                            i += 3;
                            // Absorb the separator after the phrase so newlines and
                            // opening delimiters don't leave a stray space.
                            if swallow_following {
                                if let Some(Tok::Sep(s)) = toks.get(i) {
                                    if s.chars().all(char::is_whitespace) {
                                        i += 1;
                                    }
                                }
                            }
                            continue;
                        }
                    }
                }
            }
            out.push_str(w1);
            i += 1;
        } else if let Tok::Sep(s) = &toks[i] {
            out.push_str(s);
            i += 1;
        }
    }
    out
}

fn lookup_two_word(w1: &str, w2: &str) -> Option<Replacement> {
    let (a, b) = (w1.to_ascii_lowercase(), w2.to_ascii_lowercase());
    TWO_WORD
        .iter()
        .find(|(x, y, _)| *x == a && *y == b)
        .map(|(_, _, r)| *r)
}

/// Apply `rep` to `out`; returns `true` if the separator following the matched
/// phrase should be swallowed (newlines and opening delimiters).
fn apply_replacement(out: &mut String, rep: Replacement) -> bool {
    match rep {
        Replacement::NewlineSingle | Replacement::NewlineDouble => {
            trim_trailing_blanks(out);
            out.push('\n');
            if matches!(rep, Replacement::NewlineDouble) {
                out.push('\n');
            }
            true
        }
        Replacement::Open(s) => {
            out.push_str(s);
            true
        }
        Replacement::Close(s) => {
            trim_trailing_blanks(out);
            out.push_str(s);
            false
        }
    }
}

fn trim_trailing_blanks(out: &mut String) {
    while out.ends_with(' ') || out.ends_with('\t') {
        out.pop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_is_passthrough() {
        assert_eq!(
            apply_dictation_commands("write new line here", false),
            "write new line here"
        );
    }

    #[test]
    fn new_line_becomes_newline() {
        assert_eq!(
            apply_dictation_commands("first line new line second line", true),
            "first line\nsecond line"
        );
    }

    #[test]
    fn new_paragraph_becomes_double_newline() {
        assert_eq!(
            apply_dictation_commands("intro new paragraph body", true),
            "intro\n\nbody"
        );
    }

    #[test]
    fn paren_and_bracket_literals() {
        // Opening delimiters attach to the next word; closing to the previous.
        assert_eq!(
            apply_dictation_commands("call open paren x close paren", true),
            "call (x)"
        );
        assert_eq!(
            apply_dictation_commands("arr open bracket 0 close bracket", true),
            "arr [0]"
        );
    }

    #[test]
    fn case_insensitive_match() {
        assert_eq!(
            apply_dictation_commands("done New Line next", true),
            "done\nnext"
        );
    }

    #[test]
    fn does_not_touch_partial_or_unknown_phrases() {
        // "newline" as one word is not a command; "new day" is unknown.
        assert_eq!(
            apply_dictation_commands("a newline and a new day", true),
            "a newline and a new day"
        );
    }

    #[test]
    fn leaves_ordinary_text_untouched() {
        let s = "the quick brown fox, jumps!";
        assert_eq!(apply_dictation_commands(s, true), s);
    }
}
