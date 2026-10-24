use greedy_tokenizer::tokenize;

#[test]
fn longest_match_wins() {
    // "the" (len 3) wins over "th" (len 2) at position 0.
    let vocab = ["t", "h", "th", "the", "is", " ", "i", "s"];
    let out = tokenize(&vocab, "this").unwrap();
    // "this" -> "th" (2), "i" (6), "s" (7) — "the" is len 3 but "thi" is not in vocab so "th" wins
    assert_eq!(out, vec![2, 6, 7]);
}

#[test]
fn picks_longest_at_every_position() {
    let vocab = ["a", "ab", "c"];
    let out = tokenize(&vocab, "abc").unwrap();
    assert_eq!(out, vec![1, 2]); // "ab" then "c"
}

#[test]
fn errors_at_first_unmatched_position() {
    let vocab = ["a", "b"];
    let err = tokenize(&vocab, "abxab").unwrap_err();
    assert_eq!(err, 2);
}

#[test]
fn empty_input_is_empty_output() {
    let vocab = ["a"];
    assert_eq!(tokenize(&vocab, "").unwrap(), Vec::<usize>::new());
}
