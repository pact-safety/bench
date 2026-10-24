use warmup_rust_borrow::vowel_count;

#[test]
fn accepts_literal_and_owned() {
    assert_eq!(vowel_count("Hello"), 2);
    let owned: String = String::from("EDUCATION");
    assert_eq!(vowel_count(&owned), 5);
}

#[test]
fn empty_is_zero() {
    assert_eq!(vowel_count(""), 0);
}

#[test]
fn no_vowels() {
    assert_eq!(vowel_count("rhythm"), 0);
}
