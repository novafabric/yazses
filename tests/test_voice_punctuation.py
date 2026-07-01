from yazses.postprocess.voice_punctuation import apply_voice_punctuation


def test_comma_and_period_attach_to_prior_word():
    assert apply_voice_punctuation("hello comma world period") == "hello, world."


def test_question_and_exclamation():
    assert apply_voice_punctuation("really question mark") == "really?"
    assert apply_voice_punctuation("wow exclamation mark") == "wow!"


def test_colon_and_semicolon():
    assert apply_voice_punctuation("note colon this") == "note: this"
    assert apply_voice_punctuation("a semicolon b") == "a; b"


def test_new_line_and_paragraph():
    assert apply_voice_punctuation("line one new line line two") == "line one\nline two"
    assert apply_voice_punctuation("para one new paragraph para two") == "para one\n\npara two"


def test_multiword_phrase_beats_shorter():
    # "new paragraph" must win over "new line"/none — longest phrase first.
    assert "\n\n" in apply_voice_punctuation("end new paragraph start")
    assert apply_voice_punctuation("full stop test full stop") == ". test."


def test_word_boundary_protects_substrings():
    # "command" contains "comma" but must not be altered.
    assert apply_voice_punctuation("run the command now") == "run the command now"


def test_empty_and_plain_text_unchanged():
    assert apply_voice_punctuation("") == ""
    assert apply_voice_punctuation("just plain words") == "just plain words"
