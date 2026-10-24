use warmup_rust_result::parse_and_sum;

#[test]
fn happy_path() {
    assert_eq!(parse_and_sum("3,4"), Ok(7));
    assert_eq!(parse_and_sum(" 10, -5 "), Ok(5));
}

#[test]
fn left_failure() {
    let err = parse_and_sum("x,4").unwrap_err();
    assert!(err.contains("left:"), "got: {}", err);
}

#[test]
fn right_failure() {
    let err = parse_and_sum("3,y").unwrap_err();
    assert!(err.contains("right:"), "got: {}", err);
}

#[test]
fn wrong_arity() {
    assert_eq!(parse_and_sum("1,2,3"), Err("expected exactly one comma".to_string()));
    assert_eq!(parse_and_sum("42"), Err("expected exactly one comma".to_string()));
}
