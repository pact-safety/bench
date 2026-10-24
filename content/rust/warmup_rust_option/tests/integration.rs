use warmup_rust_option::{second_char_or_dash, second_to_uppercase};

#[test]
fn second_or_default() {
    assert_eq!(second_char_or_dash("hello"), 'e');
    assert_eq!(second_char_or_dash("a"), '-');
    assert_eq!(second_char_or_dash(""), '-');
}

#[test]
fn upper_or_none() {
    assert_eq!(second_to_uppercase("hello"), Some('E'));
    assert_eq!(second_to_uppercase("a"), None);
    assert_eq!(second_to_uppercase(""), None);
}
